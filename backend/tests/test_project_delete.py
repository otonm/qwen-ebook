"""DELETE /projects/{id}: removes the project row, its characters/segments
(no FK cascade in models.py, so this is the only cleanup path), and every
on-disk artifact (segment audio, character preview, project output).

Runs entirely against TTS_BACKEND=mock/LLM_BACKEND=mock — no GPU needed.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

os.environ.setdefault("LLM_BACKEND", "mock")
os.environ.setdefault("TTS_BACKEND", "mock")

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Character, Project, Segment  # noqa: E402

init_db()
client = TestClient(app)


def _seed_project_with_files(tmp_path: Path) -> dict:
    project_id = uuid.uuid4().hex
    character_id = uuid.uuid4().hex
    segment_id = uuid.uuid4().hex

    segment_audio = tmp_path / f"{segment_id}.wav"
    preview_audio = tmp_path / f"{character_id}.wav"
    output_audio = tmp_path / f"{project_id}.wav"
    for path in (segment_audio, preview_audio, output_audio):
        path.write_bytes(b"RIFF....WAVEfmt ")

    with Session(engine) as session:
        session.add(
            Project(
                id=project_id,
                filename="t.txt",
                source_text="Hello.",
                status="ready",
                output_path=str(output_audio),
            )
        )
        session.add(
            Character(
                id=character_id,
                project_id=project_id,
                name="Narrator",
                description="the narrator",
                is_narrator=True,
                voice_instructions="",
                preview_audio_path=str(preview_audio),
            )
        )
        session.add(
            Segment(
                id=segment_id,
                project_id=project_id,
                order=0,
                character_id=character_id,
                text="Hello.",
                voice_instructions="calm",
                audio_path=str(segment_audio),
            )
        )
        session.commit()

    return {
        "project_id": project_id,
        "segment_audio": segment_audio,
        "preview_audio": preview_audio,
        "output_audio": output_audio,
    }


def test_delete_project_removes_row_and_files(tmp_path: Path):
    seeded = _seed_project_with_files(tmp_path)
    project_id = seeded["project_id"]

    response = client.delete(f"/projects/{project_id}")
    assert response.status_code == 204

    assert client.get(f"/projects/{project_id}").status_code == 404
    assert not any(p["id"] == project_id for p in client.get("/projects").json())

    for path in (seeded["segment_audio"], seeded["preview_audio"], seeded["output_audio"]):
        assert not path.exists()

    with Session(engine) as session:
        assert (
            session.exec(select(Segment).where(Segment.project_id == project_id)).first()
            is None
        )
        assert (
            session.exec(select(Character).where(Character.project_id == project_id)).first()
            is None
        )


def test_delete_project_missing_returns_404():
    response = client.delete(f"/projects/{uuid.uuid4().hex}")
    assert response.status_code == 404
