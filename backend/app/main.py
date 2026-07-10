"""FastAPI app: POST /projects creates a Project immediately (status
"analyzing") and spawns a background asyncio task that detects the cast +
segments and persists them; GET /projects/{id} reads the result back;
GET /projects/{id}/analysis-stream pushes live progress over SSE.

Hardening (T-02-01/T-02-02, RESEARCH.md Security Domain, carried over from
Phase 1):
  - Uploads are read in bounded chunks and rejected with 413 once they
    exceed MAX_UPLOAD_BYTES, instead of buffering an unbounded body fully
    in memory.
  - Project ids are server-generated uuid4().hex — never derived from the
    client-supplied filename.
  - The UTF-8 decode is guarded; a UnicodeDecodeError becomes a clean 400
    instead of an unhandled 500 stack trace leak.

The prior Phase 1 shape of this endpoint (chunk -> synthesize -> ffmpeg
join -> download the audio synchronously) is retired here — Phase 2
replaces it with the analysis-first flow above; Phase 3 reintroduces
per-segment audio generation against the reviewed cast (ROADMAP.md).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.analysis_worker import has_pending_queue, progress_events, run_analysis
from app.config import settings
from app.db import engine, init_db
from app.epub_parser import EpubParseError, extract_text
from app.models import Character, Project, Segment
from app.tts_client import synthesize, tts_health
from app.voices import best_guess_preset, list_presets

logger = logging.getLogger(__name__)

_READ_CHUNK_SIZE = 1024 * 1024  # 1 MiB

# Fire-and-forget background tasks must be held onto until they finish, or
# they risk premature garbage collection mid-run (asyncio's own documented
# footgun) — this set exists purely to hold a reference, per-task removal
# via add_done_callback.
_background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> Response:
    """Backend readiness probe: can the backend currently reach its
    configured TTS backend."""
    ok = await run_in_threadpool(tts_health)
    if not ok:
        raise HTTPException(status_code=503, detail="TTS backend unavailable")
    return Response(status_code=200)


async def _read_upload_bounded(file: UploadFile, max_bytes: int) -> bytes:
    """Read `file` in bounded chunks, raising HTTPException(413) as soon as
    the cap is exceeded rather than buffering an oversized body fully."""
    buffer = bytearray()
    while True:
        chunk = await file.read(_READ_CHUNK_SIZE)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Upload exceeds the {max_bytes}-byte limit",
            )
    return bytes(buffer)


@app.post("/projects", status_code=201)
async def create_project(file: UploadFile = File(...)):  # noqa: B008 (FastAPI DI pattern)
    # T-02-04 (zip-bomb): the bounded read below must run — and reject an
    # oversized *compressed* upload — before extract_text ever calls
    # epub.read_epub, which is the point decompression happens.
    raw_bytes = await _read_upload_bounded(file, settings.MAX_UPLOAD_BYTES)

    filename = file.filename or "upload.txt"
    is_epub = filename.lower().endswith(".epub") or file.content_type in (
        "application/epub+zip",
        "application/epub",
    )

    if is_epub:
        try:
            # CPU-bound (zip decompress + XML parse for every chapter) —
            # offload to the threadpool so it doesn't block the event loop
            # on a large book, same discipline as the synthesize/join calls
            # elsewhere in this module.
            text = await run_in_threadpool(extract_text, raw_bytes)
        except EpubParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Upload must be UTF-8 text") from exc

    if not text.strip():
        raise HTTPException(status_code=400, detail="Upload contains no analyzable text")

    # Server-generated identifier — never derived from the client-supplied
    # filename, so it can't be used for path traversal.
    project_id = uuid.uuid4().hex

    with Session(engine) as session:
        project = Project(
            id=project_id,
            filename=filename,
            source_text=text,
            status="analyzing",
        )
        session.add(project)
        session.commit()

    task = asyncio.create_task(run_analysis(project_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"id": project_id, "status": "analyzing"}


def _serialize_character(character: Character) -> dict:
    return {
        "id": character.id,
        "name": character.name,
        "description": character.description,
        "is_narrator": character.is_narrator,
        "voice_preset": character.voice_preset,
        "voice_instructions": character.voice_instructions,
        "preview_audio_path": character.preview_audio_path,
    }


def _serialize_project(
    project: Project, characters: list[Character], segments: list[Segment]
) -> dict:
    character_by_id = {character.id: character for character in characters}
    return {
        "id": project.id,
        "filename": project.filename,
        "status": project.status,
        "error_detail": project.error_detail,
        "characters": [_serialize_character(character) for character in characters],
        "segments": [
            {
                "id": segment.id,
                "order": segment.order,
                "character_id": segment.character_id,
                "character_name": (
                    character_by_id[segment.character_id].name
                    if segment.character_id in character_by_id
                    else None
                ),
                "text": segment.text,
                "voice_instructions": segment.voice_instructions,
            }
            for segment in sorted(segments, key=lambda s: s.order)
        ],
    }


@app.get("/projects/{project_id}")
async def get_project(project_id: str):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")

        characters = list(
            session.exec(select(Character).where(Character.project_id == project_id)).all()
        )
        segments = list(
            session.exec(select(Segment).where(Segment.project_id == project_id)).all()
        )
        return _serialize_project(project, characters, segments)


async def _require_project_exists(project_id: str) -> None:
    """404 guard for `analysis_stream` (WR-02).

    Deliberately a FastAPI dependency, not a check inside the endpoint
    body: `analysis_stream` is an async-generator path operation (SSE), and
    raising HTTPException from inside such a generator is swallowed by the
    SSE producer's task group instead of becoming a clean HTTP error
    response — a dependency runs (and can fail) before the generator is
    ever entered, so it's the only place this 404 works correctly.
    """
    with Session(engine) as session:
        if session.get(Project, project_id) is None:
            raise HTTPException(status_code=404, detail="Project not found")


@app.get("/projects/{project_id}/analysis-stream", response_class=EventSourceResponse)
async def analysis_stream(
    project_id: str, _exists: None = Depends(_require_project_exists)
) -> AsyncIterable[ServerSentEvent]:
    # WR-02: if analysis already finished *and* its terminal event was
    # already drained by an earlier subscriber (no pending queue left),
    # serve the current state directly instead of blocking forever on a
    # fresh, permanently-empty queue — this is also what previously leaked
    # a Queue entry in analysis_worker._progress_queues for the life of the
    # process. A still-pending queue (analysis just finished but nobody's
    # consumed the buffered events yet) is drained normally below so early
    # progress events aren't skipped.
    with Session(engine) as session:
        project = session.get(Project, project_id)
        status = project.status
        error_detail = project.error_detail

    if status in ("ready", "error") and not has_pending_queue(project_id):
        if status == "ready":
            yield ServerSentEvent(data={"status": "ready"}, event="done")
        else:
            yield ServerSentEvent(data={"detail": error_detail}, event="error")
        return

    async for event_type, payload in progress_events(project_id):
        yield ServerSentEvent(data=payload, event=event_type)


@app.get("/voices")
async def get_voices() -> list[dict]:
    """WIZ-03: the wizard's preset voice picker list."""
    return list_presets()


class CharacterPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    voice_preset: str | None = None
    voice_instructions: str | None = None


@app.patch("/characters/{character_id}")
async def patch_character(character_id: str, patch: CharacterPatch) -> dict:
    """WIZ-02 rename/edit, WIZ-03 voice assign. A voice-field change
    (voice_preset and/or voice_instructions present) bumps voice_version
    and eagerly kicks off race-safe preview generation (WIZ-04/WIZ-05,
    Pitfall 5) — see _generate_preview."""
    voice_changed = patch.voice_preset is not None or patch.voice_instructions is not None

    with Session(engine) as session:
        character = session.get(Character, character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Character not found")

        if patch.name is not None:
            character.name = patch.name
        if patch.description is not None:
            character.description = patch.description
        if patch.voice_preset is not None:
            character.voice_preset = patch.voice_preset
        if patch.voice_instructions is not None:
            character.voice_instructions = patch.voice_instructions
        if voice_changed:
            character.voice_version += 1

        session.add(character)
        session.commit()
        session.refresh(character)
        result = _serialize_character(character)
        version = character.voice_version

    if voice_changed:
        task = asyncio.create_task(_generate_preview(character_id, version))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return result


async def _generate_preview(character_id: str, version: int) -> None:
    """Synthesize the WIZ-04 intro line for `character_id` and write it as
    its preview WAV, but ONLY if `character_id`'s voice_version still
    equals `version` when generation completes (Pitfall 5 last-request-wins
    race guard) — a newer PATCH landing mid-generation must win, not the
    generation that happens to finish first.
    """
    with Session(engine) as session:
        character = session.get(Character, character_id)
        if character is None:
            return
        name = character.name
        description = (character.description or "").strip()
        # T-02-10/D-17: the actual /synthesize wire contract (Phase 1) only
        # takes a preset speaker name, no free-text instruct parameter.
        # # ponytail: when no preset is explicitly chosen, best_guess_preset
        # resolves the free-text voice_instructions to a preset name instead
        # — the "free-text steering" this phase ships is pre-fill + best-
        # guess preset selection, not real per-request instruct-steering
        # (which Phase 1's TTS surface doesn't support; D-17 explicitly
        # defers that to VoiceDesign).
        speaker = character.voice_preset
        if not speaker:
            # "" (the sole shipped preset's persisted value, WIZ-03) means
            # "auto-selected" just as much as None does — falling back only
            # on None let a touched-but-unchanged preset dropdown silently
            # defeat best-guess voice selection (CR-02).
            speaker = best_guess_preset(character.voice_instructions or description) or ""

    intro_line = f"Hi, my name is {name} and I am a {description}."

    try:
        wav_bytes = await run_in_threadpool(synthesize, intro_line, speaker)
    except Exception:  # noqa: BLE001 - a failed preview must never crash the background task
        logger.exception("preview generation failed for character %s", character_id)
        return

    preview_dir = Path(settings.PREVIEW_DIR)
    preview_dir.mkdir(parents=True, exist_ok=True)
    # Server-generated uuid filename — never derived from any client string
    # (T-02-10).
    preview_path = preview_dir / f"{uuid.uuid4().hex}.wav"
    preview_path.write_bytes(wav_bytes)

    with Session(engine) as session:
        character = session.get(Character, character_id)
        if character is None or character.voice_version != version:
            # A newer PATCH landed while this generation was in flight —
            # discard the now-stale file (Pitfall 5 last-request-wins).
            preview_path.unlink(missing_ok=True)
            return

        old_path = character.preview_audio_path
        character.preview_audio_path = str(preview_path)
        session.add(character)
        session.commit()

    if old_path and old_path != str(preview_path):
        Path(old_path).unlink(missing_ok=True)


@app.get("/characters/{character_id}/preview.wav")
async def get_character_preview(character_id: str) -> Response:
    with Session(engine) as session:
        character = session.get(Character, character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Character not found")
        preview_path = character.preview_audio_path

    if not preview_path or not Path(preview_path).is_file():
        raise HTTPException(status_code=409, detail="Preview not ready")

    return Response(content=Path(preview_path).read_bytes(), media_type="audio/wav")


class MergeRequest(BaseModel):
    target_id: str


@app.post("/characters/{character_id}/merge")
async def merge_character(character_id: str, body: MergeRequest) -> dict:
    """WIZ-02 merge: reassign source's segments to target, delete source.

    Explicit two-chosen-ids user action — no fuzzy character matching.
    """
    source_id, target_id = character_id, body.target_id
    if source_id == target_id:
        raise HTTPException(status_code=400, detail="Cannot merge a character into itself")

    with Session(engine) as session:
        source = session.get(Character, source_id)
        target = session.get(Character, target_id)
        if source is None or target is None or source.project_id != target.project_id:
            raise HTTPException(status_code=404, detail="Character not found")

        source_preview_path = source.preview_audio_path

        segments = list(
            session.exec(select(Segment).where(Segment.character_id == source_id)).all()
        )
        for segment in segments:
            segment.character_id = target_id
            session.add(segment)

        session.delete(source)
        session.commit()
        session.refresh(target)

        segment_count = len(
            session.exec(select(Segment).where(Segment.character_id == target_id)).all()
        )
        result = _serialize_character(target)
        result["segment_count"] = segment_count

    # WR-05: the merged-away source's preview WAV is no longer referenced
    # by any row — clean it up from disk same as _generate_preview's own
    # stale-preview cleanup, or every merge leaks one file under
    # PREVIEW_DIR.
    if source_preview_path:
        Path(source_preview_path).unlink(missing_ok=True)

    return result
