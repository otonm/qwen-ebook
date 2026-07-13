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
import contextlib
import logging
import uuid
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.analysis_worker import has_pending_queue, progress_events, run_analysis
from app.cache_key import compute_cache_key
from app.config import settings
from app.db import engine, init_db
from app.epub_parser import EpubParseError, extract_text
from app.generation_worker import (
    _running_generations,
    generation_progress_events,
    get_generation_task,
    has_pending_generation_queue,
    is_generation_running,
    push_generation_event,
    run_batch_generation,
)
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
# FastAPI's dependency-injection parsing requires `File(...)` as a literal
# default; the call is never actually "reused at definition time" the way
# B008 warns about — FastAPI resolves it per-request. Framework requirement,
# not a mistake — see CLAUDE.md Conventions.
async def create_project(file: UploadFile = File(...)):  # noqa: B008
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


def _serialize_segment(segment: Segment, character_name: str | None) -> dict:
    return {
        "id": segment.id,
        "order": segment.order,
        "character_id": segment.character_id,
        "character_name": character_name,
        "text": segment.text,
        "voice_instructions": segment.voice_instructions,
        "generation_status": segment.generation_status,
        "generation_error": segment.generation_error,
        "audio_path": segment.audio_path,
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
        # CFG-01: the joined batch-generation output (plan 03-03) and the
        # server's fixed output format/codec choice — both needed by the
        # config panel, neither previously exposed over the API.
        "output_path": project.output_path,
        "output_format": settings.OUTPUT_FORMAT,
        "characters": [_serialize_character(character) for character in characters],
        "segments": [
            _serialize_segment(
                segment,
                character_by_id[segment.character_id].name
                if segment.character_id in character_by_id
                else None,
            )
            for segment in sorted(segments, key=lambda s: s.order)
        ],
    }


@app.get("/projects")
async def list_projects() -> list[dict]:
    """PERS-02: thin project list for the landing screen — id/filename/
    status/created_at only, no character/segment payload. Reads the
    existing Project table (created_at was already added in plan 03-01),
    no schema change. Newest first."""
    with Session(engine) as session:
        projects = session.exec(select(Project).order_by(Project.created_at.desc())).all()
        return [
            {
                "id": project.id,
                "filename": project.filename,
                "status": project.status,
                "created_at": project.created_at,
            }
            for project in projects
        ]


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


@app.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str) -> Response:
    """Delete a project and every generated artifact under it: the
    project's joined output file, each character's voice preview, and
    each segment's generated audio. No FK cascade exists on these tables
    (models.py), so children are deleted explicitly before the parent row.

    A live batch generation for this project is cancelled first (same
    cancel path as POST /generate/cancel) so its background task can't
    keep writing rows/files the delete just removed out from under it."""
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

    task = get_generation_task(project_id)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    for path in (
        [project.output_path]
        + [c.preview_audio_path for c in characters]
        + [s.audio_path for s in segments]
    ):
        if path:
            Path(path).unlink(missing_ok=True)

    with Session(engine) as session:
        for segment in segments:
            session.delete(session.get(Segment, segment.id))
        for character in characters:
            session.delete(session.get(Character, character.id))
        session.delete(session.get(Project, project_id))
        session.commit()

    return Response(status_code=204)


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
    (voice_preset and/or voice_instructions present) INVALIDATES the stale
    preview (bumps voice_version, clears preview_audio_path) but does NOT
    auto-fire regeneration — mirrors patch_segment's GEN-03 invalidate-only
    pattern. The user triggers a fresh preview explicitly via
    POST /characters/{id}/preview (trigger_character_preview)."""
    voice_changed = patch.voice_preset is not None or patch.voice_instructions is not None

    old_preview_path: str | None = None
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
            old_preview_path = character.preview_audio_path
            character.preview_audio_path = None

        session.add(character)
        session.commit()
        session.refresh(character)
        result = _serialize_character(character)

    if old_preview_path:
        Path(old_preview_path).unlink(missing_ok=True)

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
    except Exception:
        # Broad catch is deliberate: this runs as a fire-and-forget background
        # task (asyncio.create_task) with no caller to propagate to — a failed
        # preview must never crash the task or take down the event loop.
        logger.exception(f"preview generation failed for character {character_id}")
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


@app.post("/characters/{character_id}/preview")
async def trigger_character_preview(character_id: str) -> dict:
    """CFG-03 Config Panel on-demand preview trigger: a character whose
    voice was never (re)saved via PATCH /characters/{id} has a permanently
    null preview_audio_path, since that's otherwise the only path that ever
    calls _generate_preview. Bumps voice_version (same race guard
    _generate_preview already relies on) and kicks off preview generation
    as a tracked background task — reuses _generate_preview as-is, same
    create_task + _background_tasks pattern patch_character uses."""
    with Session(engine) as session:
        character = session.get(Character, character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Character not found")
        character.voice_version += 1
        session.add(character)
        session.commit()
        version = character.voice_version

    task = asyncio.create_task(_generate_preview(character_id, version))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"status": "generating"}


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


class UndoMergeCharacter(BaseModel):
    id: str
    project_id: str
    name: str
    description: str
    is_narrator: bool
    voice_preset: str | None
    voice_instructions: str
    voice_version: int
    had_preview: bool


class UndoMergeRequest(BaseModel):
    character: UndoMergeCharacter
    segment_ids: list[str]


@app.post("/characters/{character_id}/merge")
async def merge_character(character_id: str, body: MergeRequest) -> dict:
    """WIZ-02 merge: reassign source's segments to target, delete source.

    Explicit two-chosen-ids user action — no fuzzy character matching.
    Returns an `undo` snapshot the client can hand back to POST
    /characters/undo-merge to reverse this single merge.
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
        undo_snapshot = {
            "character": {
                "id": source.id,
                "project_id": source.project_id,
                "name": source.name,
                "description": source.description,
                "is_narrator": source.is_narrator,
                "voice_preset": source.voice_preset,
                "voice_instructions": source.voice_instructions,
                "voice_version": source.voice_version,
                "had_preview": source_preview_path is not None,
            },
        }

        segments = list(
            session.exec(select(Segment).where(Segment.character_id == source_id)).all()
        )
        undo_snapshot["segment_ids"] = [segment.id for segment in segments]
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
        result["undo"] = undo_snapshot

    # WR-05: the merged-away source's preview WAV is no longer referenced
    # by any row — clean it up from disk same as _generate_preview's own
    # stale-preview cleanup, or every merge leaks one file under
    # PREVIEW_DIR. Undoing the merge regenerates a fresh preview instead
    # of trying to resurrect this exact file.
    if source_preview_path:
        Path(source_preview_path).unlink(missing_ok=True)

    return result


@app.post("/characters/undo-merge")
async def undo_merge_character(body: UndoMergeRequest) -> dict:
    """Reverses the most recent POST /characters/{id}/merge using the
    `undo` snapshot from that response. Recreates the source character
    with its original id and fields, and reassigns the given segment ids
    back to it.

    # ponytail: stateless single-shot undo — the snapshot lives in the
    # client, not a server-side undo stack. Only the merge that produced
    # this exact snapshot can be undone; upgrade to a server-tracked
    # history if multi-step undo is ever needed.
    """
    character = body.character
    with Session(engine) as session:
        if session.get(Character, character.id) is not None:
            raise HTTPException(status_code=409, detail="Character already exists")
        # WR-01: this snapshot is fully client-supplied — verify project_id
        # refers to a real project and every segment_id belongs to it
        # before mutating anything, mirroring bulk_reassign_segments'/
        # merge_character's ownership checks. Otherwise a malformed or
        # crafted request could fabricate a character in an arbitrary
        # project and reassign arbitrary segments onto it.
        if session.get(Project, character.project_id) is None:
            raise HTTPException(status_code=404, detail="Project not found")

        segments = list(
            session.exec(select(Segment).where(Segment.id.in_(body.segment_ids))).all()
        )
        if len(segments) != len(body.segment_ids):
            raise HTTPException(status_code=404, detail="Segment not found")
        if any(segment.project_id != character.project_id for segment in segments):
            raise HTTPException(
                status_code=400, detail="Segment does not belong to the character's project"
            )

        restored = Character(
            id=character.id,
            project_id=character.project_id,
            name=character.name,
            description=character.description,
            is_narrator=character.is_narrator,
            voice_preset=character.voice_preset,
            voice_instructions=character.voice_instructions,
            voice_version=character.voice_version,
        )
        session.add(restored)

        for segment in segments:
            segment.character_id = character.id
            session.add(segment)

        session.commit()
        session.refresh(restored)
        result = _serialize_character(restored)

    if character.had_preview:
        task = asyncio.create_task(
            _generate_preview(character.id, character.voice_version)
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return result


class SegmentPatch(BaseModel):
    character_id: str | None = None
    voice_instructions: str | None = None
    text: str | None = None


@app.patch("/segments/{segment_id}")
async def patch_segment(segment_id: str, patch: SegmentPatch) -> dict:
    """TBL-01/02 editable-cell commit. GEN-03 (D-06 REVERSED during 03 UAT
    — see 03-CONTEXT.md): an edit INVALIDATES the row's stale audio (clears
    it, marks the row pending) but does NOT auto-fire a background
    regeneration — the user triggers that manually via the per-row or
    Generate All controls."""
    any_changed = (
        patch.character_id is not None
        or patch.voice_instructions is not None
        or patch.text is not None
    )

    old_audio_path: str | None = None
    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        if segment is None:
            raise HTTPException(status_code=404, detail="Segment not found")

        if patch.character_id is not None:
            # WR-02: mirror bulk_reassign_segments' existence/ownership
            # check — an unchecked character_id here silently degrades to
            # character_name: null / a best-guess fallback speaker instead
            # of erroring (SQLite foreign keys aren't enabled).
            new_character = session.get(Character, patch.character_id)
            if new_character is None:
                raise HTTPException(status_code=404, detail="Character not found")
            if new_character.project_id != segment.project_id:
                raise HTTPException(
                    status_code=400, detail="Character does not belong to the segment's project"
                )
            segment.character_id = patch.character_id
        if patch.voice_instructions is not None:
            segment.voice_instructions = patch.voice_instructions
        if patch.text is not None:
            segment.text = patch.text
        if any_changed:
            segment.generation_version += 1
            segment.generation_status = "pending"
            segment.generation_error = None
            # Clear the stale audio — a cleared audio_path is sufficient to
            # force a cache miss on the next manual generate (it recomputes
            # the cache key from live DB state and checks the file exists
            # on disk); cache_key itself is left for regenerate_segment to
            # recompute, same as everywhere else.
            old_audio_path = segment.audio_path
            segment.audio_path = None

        session.add(segment)
        session.commit()
        session.refresh(segment)
        character = session.get(Character, segment.character_id)
        result = _serialize_segment(segment, character.name if character else None)

    if old_audio_path:
        # Mirrors regenerate_segment's post-commit unlink pattern — the
        # invalidated file must not leak on disk.
        Path(old_audio_path).unlink(missing_ok=True)

    return result


def _resolve_segment_speaker(segment: Segment, character: Character | None) -> str:
    """Same preset-then-best-guess-fallback resolution _generate_preview
    uses for characters (T-02-10/D-17: only a preset name, no per-request
    free-text instruct steering), applied at segment granularity so the
    segment's own Voice Instructions cell — not just the character's — can
    steer the fallback guess."""
    speaker = character.voice_preset if character else None
    if not speaker:
        fallback_text = segment.voice_instructions or (
            character.description if character else ""
        )
        speaker = best_guess_preset(fallback_text) or ""
    return speaker


async def regenerate_segment(segment_id: str, version: int) -> None:
    """Recomputes the GEN-02 content-hash cache key from *current* DB state
    (Pitfall 3 — never trust a stored cache_key as ground truth) and
    synthesizes only on a miss. Writes back only if `generation_version`
    still equals `version` when it finishes (Pitfall 2 last-request-wins
    guard, mirrors _generate_preview)."""
    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        if segment is None:
            return
        character = session.get(Character, segment.character_id)
        speaker = _resolve_segment_speaker(segment, character)
        cache_key = compute_cache_key(speaker, segment.voice_instructions, segment.text)
        text = segment.text
        existing_cache_key = segment.cache_key
        existing_audio_path = segment.audio_path

    if (
        existing_cache_key == cache_key
        and existing_audio_path
        and Path(existing_audio_path).is_file()
    ):
        # Cache hit — reuse the audio already on disk, no synth call.
        with Session(engine) as session:
            segment = session.get(Segment, segment_id)
            if segment is None or segment.generation_version != version:
                return
            segment.generation_status = "complete"
            segment.cache_key = cache_key
            session.add(segment)
            session.commit()
        return

    try:
        wav_bytes = await run_in_threadpool(synthesize, text, speaker)
    except Exception:
        # Broad catch is deliberate: this runs as a fire-and-forget
        # background task with no caller to propagate to.
        logger.exception(f"segment generation failed for segment {segment_id}")
        with Session(engine) as session:
            segment = session.get(Segment, segment_id)
            if segment is None or segment.generation_version != version:
                return
            segment.generation_status = "error"
            segment.generation_error = "TTS synthesis failed"
            session.add(segment)
            session.commit()
        return

    segments_dir = Path(settings.OUTPUT_DIR) / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    # Server-generated uuid filename — never derived from segment text
    # (T-03-01).
    audio_path = segments_dir / f"{uuid.uuid4().hex}.wav"
    audio_path.write_bytes(wav_bytes)

    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        if segment is None or segment.generation_version != version:
            # A newer PATCH landed while this generation was in flight —
            # discard the now-stale file (Pitfall 2 last-request-wins).
            audio_path.unlink(missing_ok=True)
            return

        old_path = segment.audio_path
        segment.audio_path = str(audio_path)
        segment.cache_key = cache_key
        segment.generation_status = "complete"
        segment.generation_error = None
        session.add(segment)
        session.commit()

    if old_path and old_path != str(audio_path):
        Path(old_path).unlink(missing_ok=True)


@app.post("/segments/{segment_id}/generate")
async def generate_segment(segment_id: str) -> dict:
    """TBL-04 on-demand per-row generate. Awaits the regenerate helper
    synchronously (single-row scope, no need for a fire-and-forget task
    here) and returns the segment's resulting status.

    T-03-26: a row already 'generating' (via an earlier per-row click or a
    batch run currently on this row) is rejected with 409 rather than
    starting a second concurrent regenerate_segment for the same row —
    that second call would race the first and get stomped by the worker's
    stale-'generating' reset."""
    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        if segment is None:
            raise HTTPException(status_code=404, detail="Segment not found")
        if segment.generation_status == "generating":
            raise HTTPException(status_code=409, detail="Segment is already generating")
        segment.generation_status = "generating"
        session.add(segment)
        session.commit()
        version = segment.generation_version

    await regenerate_segment(segment_id, version)

    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        if segment is None:
            raise HTTPException(status_code=404, detail="Segment not found")
        character = session.get(Character, segment.character_id)
        return _serialize_segment(segment, character.name if character else None)


class BulkReassignRequest(BaseModel):
    segment_ids: list[str]
    character_id: str


@app.post("/segments/bulk-reassign")
async def bulk_reassign_segments(body: BulkReassignRequest) -> dict:
    """TBL-03 bulk toolbar action. Mirrors merge_character's ownership
    discipline (T-03-04): every segment must belong to the target
    character's project, or the whole request is rejected and nothing is
    changed. Only bumps generation_version to mark rows stale — batch
    regen is plan 03-03's job, not this endpoint's."""
    with Session(engine) as session:
        target = session.get(Character, body.character_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Character not found")

        segments = list(
            session.exec(select(Segment).where(Segment.id.in_(body.segment_ids))).all()
        )
        if len(segments) != len(body.segment_ids):
            raise HTTPException(status_code=404, detail="Segment not found")
        if any(segment.project_id != target.project_id for segment in segments):
            raise HTTPException(
                status_code=400, detail="Segment does not belong to the target's project"
            )

        for segment in segments:
            segment.character_id = target.id
            segment.generation_version += 1
            session.add(segment)
        session.commit()

    return {"updated": len(segments)}


@app.get("/segments/{segment_id}/audio.wav")
async def get_segment_audio(segment_id: str) -> Response:
    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        if segment is None:
            raise HTTPException(status_code=404, detail="Segment not found")
        audio_path = segment.audio_path

    if not audio_path or not Path(audio_path).is_file():
        raise HTTPException(status_code=409, detail="Audio not ready")

    return Response(content=Path(audio_path).read_bytes(), media_type="audio/wav")


@app.post("/projects/{project_id}/generate", status_code=202)
async def generate_project(project_id: str) -> dict:
    """CFG-03/GEN-05: kick off (or resume) the whole-project batch
    generation run as a background task and return immediately — progress
    is pushed over generation_stream. Fires even if a previous run already
    completed; run_batch_generation's own stale-reset + per-segment cache
    check make a re-invocation on an already-complete project a fast no-op
    join, which is exactly what "Resume Generation" needs.

    T-03-25/T-03-26: a second call while a run is already live for this
    project is rejected without spawning another task — two concurrent
    run_batch_generation passes would race each other's row writes, and
    the worker's own crash-leftover stale-reset would misfire against
    genuinely in-flight rows. Still 202 (accepted, just not started) —
    the frontend only needs the status string to tell the two cases apart."""
    with Session(engine) as session:
        if session.get(Project, project_id) is None:
            raise HTTPException(status_code=404, detail="Project not found")

    if is_generation_running(project_id):
        return {"status": "already_running"}

    task = asyncio.create_task(run_batch_generation(project_id))
    _running_generations[project_id] = task
    _background_tasks.add(task)

    def _cleanup(completed_task: asyncio.Task, project_id: str = project_id) -> None:
        _background_tasks.discard(completed_task)
        if _running_generations.get(project_id) is completed_task:
            _running_generations.pop(project_id, None)

    task.add_done_callback(_cleanup)

    return {"status": "started"}


@app.post("/projects/{project_id}/generate/cancel")
async def cancel_generation(project_id: str) -> dict:
    """T-03-27: cancel a live batch run. No-ops ({"status": "not_running"})
    if nothing is running for this project.

    # ponytail: tts_client.synthesize() is a sync httpx.post wrapped in
    # run_in_threadpool (300s read timeout) — a Python thread can't be
    # forcibly interrupted, so cancelling the segment currently mid-synth
    # only takes effect once that HTTP call returns; this stops progression
    # to the NEXT segment, it does not abort the in-flight one. Upgrade
    # path if that ceiling ever matters: an async httpx client with real
    # request cancellation, or a cancel endpoint on the TTS service itself.
    """
    task = get_generation_task(project_id)
    if task is None:
        return {"status": "not_running"}

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    with Session(engine) as session:
        still_generating = session.exec(
            select(Segment)
            .where(Segment.project_id == project_id)
            .where(Segment.generation_status == "generating")
        ).all()
        for segment in still_generating:
            segment.generation_status = "pending"
            session.add(segment)
        session.commit()

    # "done" (not "error") with a non-"ready" status: useGenerationStream
    # already treats any non-"ready" done payload as settling to "idle" —
    # no new client event type needed.
    await push_generation_event(project_id, "done", {"status": "cancelled"})

    return {"status": "cancelled"}


@app.get("/projects/{project_id}/generation-stream", response_class=EventSourceResponse)
async def generation_stream(
    project_id: str, _exists: None = Depends(_require_project_exists)
) -> AsyncIterable[ServerSentEvent]:
    """Mirrors analysis_stream's shape (WR-02's "already terminal, no
    pending queue" fast path) but drains generation_progress_events with
    the {segment_id, n, total, status} schema instead of analysis's
    {stage, n, total}."""
    if not has_pending_generation_queue(project_id):
        # No batch run in flight and nothing buffered to drain — either
        # nothing has been triggered yet, or a prior run's terminal event
        # was already consumed. The client reads current per-segment status
        # from GET /projects/{id} in either case.
        yield ServerSentEvent(data={"status": "idle"}, event="done")
        return

    async for event_type, payload in generation_progress_events(project_id):
        yield ServerSentEvent(data=payload, event=event_type)


# Serve the built React app (DEPL-02: this backend is the single process
# the whole app runs as). Mounted LAST so every API route above is matched
# first; only paths no @app route claims (the SPA's "/", its JS/CSS
# bundles) fall through to here. check_dir=False: local dev has no built
# frontend/dist (uses `npm run dev` instead) — without it, StaticFiles
# raises at import time and breaks every test that imports app.main.
app.mount(
    "/",
    StaticFiles(directory=settings.STATIC_DIR, html=True, check_dir=False),
    name="static",
)
