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

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

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
    if not chunks:
        raise HTTPException(
            status_code=400, detail="Upload contains no synthesizable text"
        )

    # Server-generated identifier — never derived from the client-supplied
    # filename, so it can't be used for path traversal.
    project_id = uuid.uuid4().hex
    upload_dir = Path(settings.UPLOAD_DIR)
    output_dir = Path(settings.OUTPUT_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # WR-01: chunk WAVs are intermediate scratch files — no longer needed
    # once the join succeeds, and must not be left behind (orphaned,
    # growing disk usage forever) if any step below fails partway through.
    # The `finally` below removes whatever chunk files were actually
    # written, whether the request ends in success or an HTTPException.
    chunk_paths: list[str] = []
    try:
        for index, chunk_text in enumerate(chunks):
            # T-03-02: a TTS-container failure/timeout must surface as a
            # clean HTTP error to the client, not an unhandled 500 or an
            # indefinite hang. tts_client.synthesize() itself applies
            # bounded httpx timeouts (Plan 01); this wiring translates the
            # raised client error into the appropriate gateway status code.
            try:
                # CR-02: synthesize() is a blocking (sync httpx) call with
                # up to a 300s read timeout — run it in the threadpool so
                # it doesn't freeze the single event loop for the whole app
                # while it waits.
                chunk_audio = await run_in_threadpool(
                    synthesize, chunk_text, settings.TTS_DEFAULT_SPEAKER
                )
            except httpx.TimeoutException as exc:
                raise HTTPException(
                    status_code=504, detail="TTS service timed out"
                ) from exc
            except httpx.HTTPStatusError as exc:
                # WR-02: distinguish the TTS container's own 4xx client/
                # config errors (e.g. an unsupported TTS_DEFAULT_SPEAKER,
                # oversized chunk text) from a genuine 5xx/connectivity
                # failure — collapsing both into the same generic 502
                # "unavailable" message hides the real cause.
                if exc.response.status_code < 500:
                    raise HTTPException(
                        status_code=502,
                        detail=f"TTS service rejected request: {exc.response.text}",
                    ) from exc
                raise HTTPException(
                    status_code=502, detail="TTS service unavailable"
                ) from exc
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=502, detail="TTS service unavailable"
                ) from exc
            chunk_path = upload_dir / f"{project_id}_chunk_{index:04d}.wav"
            await run_in_threadpool(chunk_path.write_bytes, chunk_audio)
            chunk_paths.append(str(chunk_path))

        output_path = output_dir / f"{project_id}.{settings.OUTPUT_FORMAT}"
        await run_in_threadpool(
            join_wavs, chunk_paths, str(output_path), fmt=settings.OUTPUT_FORMAT
        )
    finally:
        for chunk_path_str in chunk_paths:
            Path(chunk_path_str).unlink(missing_ok=True)

    media_type = "audio/wav" if settings.OUTPUT_FORMAT == "wav" else "audio/mpeg"
    output_bytes = await run_in_threadpool(output_path.read_bytes)
    return Response(content=output_bytes, media_type=media_type)
