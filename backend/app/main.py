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
import uuid
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.analysis_worker import progress_events, run_analysis
from app.config import settings
from app.db import engine, init_db
from app.epub_parser import EpubParseError, extract_text
from app.models import Character, Project, Segment
from app.tts_client import tts_health
from app.voices import list_presets

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


@app.get("/projects/{project_id}/analysis-stream", response_class=EventSourceResponse)
async def analysis_stream(project_id: str) -> AsyncIterable[ServerSentEvent]:
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
    """WIZ-02 rename/edit, WIZ-03 voice assign (persistence only — the eager
    preview-generation side effect on a voice-field change is Task 2)."""
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

        session.add(character)
        session.commit()
        session.refresh(character)
        return _serialize_character(character)


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

    return result
