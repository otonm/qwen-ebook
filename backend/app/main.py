"""FastAPI app: POST /projects orchestrates upload -> chunk -> synthesize ->
join -> download.

Hardening (T-01-01/T-01-02/T-01-04, RESEARCH.md Security Domain V5/V12):
  - All server-side filenames are generated with uuid4() — UploadFile.filename
    is never used to build a filesystem path (path-traversal safe).
  - Uploads are read in bounded chunks and rejected with 413 once they exceed
    MAX_UPLOAD_BYTES, instead of buffering an unbounded body fully in memory.
  - The UTF-8 decode is guarded; a UnicodeDecodeError becomes a clean 400
    instead of an unhandled 500 stack trace leak.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.audio_join import join_wavs
from app.chunking import chunk_paragraphs
from app.config import settings
from app.tts_client import synthesize

app = FastAPI()

_READ_CHUNK_SIZE = 1024 * 1024  # 1 MiB


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


@app.post("/projects")
async def create_project(file: UploadFile = File(...)):  # noqa: B008 (FastAPI DI pattern)
    raw_bytes = await _read_upload_bounded(file, settings.MAX_UPLOAD_BYTES)

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Upload must be UTF-8 text") from exc

    chunks = chunk_paragraphs(text, target_len=settings.CHUNK_TARGET_LEN)

    # Server-generated identifier — never derived from the client-supplied
    # filename, so it can't be used for path traversal.
    project_id = uuid.uuid4().hex
    upload_dir = Path(settings.UPLOAD_DIR)
    output_dir = Path(settings.OUTPUT_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    chunk_paths: list[str] = []
    for index, chunk_text in enumerate(chunks):
        chunk_audio = synthesize(chunk_text, settings.TTS_DEFAULT_SPEAKER)
        chunk_path = upload_dir / f"{project_id}_chunk_{index:04d}.wav"
        chunk_path.write_bytes(chunk_audio)
        chunk_paths.append(str(chunk_path))

    output_path = output_dir / f"{project_id}.{settings.OUTPUT_FORMAT}"
    join_wavs(chunk_paths, str(output_path), fmt=settings.OUTPUT_FORMAT)

    media_type = "audio/wav" if settings.OUTPUT_FORMAT == "wav" else "audio/mpeg"
    return Response(content=output_path.read_bytes(), media_type=media_type)
