"""FastAPI app: POST /projects orchestrates upload -> chunk -> synthesize ->
join -> download.

Task 2 implements the happy path; Task 3 adds upload-size/UTF-8/path-safety
hardening on top of this.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import Response

from app.audio_join import join_wavs
from app.chunking import chunk_paragraphs
from app.config import settings
from app.tts_client import synthesize

app = FastAPI()


@app.post("/projects")
async def create_project(file: UploadFile = File(...)):  # noqa: B008 (FastAPI DI pattern)
    raw_bytes = await file.read()
    text = raw_bytes.decode("utf-8")

    chunks = chunk_paragraphs(text, target_len=settings.CHUNK_TARGET_LEN)

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
