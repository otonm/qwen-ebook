"""POST /projects/{id}/model (05-02 Task 3, CFG-04): validates model_id,
claims the single-flight lock, drives the swap via tts_client.load_model,
and on success invalidates every segment (D-05/D-06) and every character
preview (RESEARCH Pitfall 4). A failed load leaves the project row, cached
audio, and previews all untouched (D-02) and releases the lock.

Runs entirely against TTS_BACKEND=mock/LLM_BACKEND=mock — no GPU needed;
tts_client.load_model is monkeypatched directly so no real HTTP call
happens either way.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

os.environ.setdefault("LLM_BACKEND", "mock")
os.environ.setdefault("TTS_BACKEND", "mock")

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import main as app_main  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Character, Project, Segment  # noqa: E402

init_db()
client = TestClient(app)
client.__enter__()


def _seed_project_with_files(tmp_path: Path, tts_model: str = "1.7b") -> dict:
    project_id = uuid.uuid4().hex
    character_id = uuid.uuid4().hex
    segment_id = uuid.uuid4().hex

    segment_audio = tmp_path / f"{segment_id}.wav"
    preview_audio = tmp_path / f"{character_id}.wav"
    for path in (segment_audio, preview_audio):
        path.write_bytes(b"RIFF....WAVEfmt ")

    with Session(engine) as session:
        session.add(
            Project(
                id=project_id,
                filename="t.txt",
                source_text="Hello.",
                status="ready",
                tts_model=tts_model,
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
                cache_key="stale-key",
                generation_status="complete",
                generation_version=3,
            )
        )
        session.commit()

    return {
        "project_id": project_id,
        "character_id": character_id,
        "segment_id": segment_id,
        "segment_audio": segment_audio,
        "preview_audio": preview_audio,
    }


def test_rejects_unknown_model_id(tmp_path: Path):
    seeded = _seed_project_with_files(tmp_path)

    response = client.post(f"/projects/{seeded['project_id']}/model", json={"model_id": "13b"})

    assert response.status_code == 422
    assert client.get("/generation-status").json() == {"active": False}


def test_swap_invalidates_segments_and_previews(tmp_path: Path, monkeypatch):
    seeded = _seed_project_with_files(tmp_path, tts_model="1.7b")
    calls = []
    monkeypatch.setattr(app_main.tts_client, "load_model", lambda model_id: calls.append(model_id))

    response = client.post(f"/projects/{seeded['project_id']}/model", json={"model_id": "0.6b"})

    assert response.status_code == 200
    body = response.json()
    assert body["tts_model"] == "0.6b"
    assert calls == ["0.6b"]

    segment = body["segments"][0]
    assert segment["generation_status"] == "pending"
    assert segment["audio_path"] is None

    character = body["characters"][0]
    assert character["preview_audio_path"] is None

    with Session(engine) as session:
        db_segment = session.exec(
            select(Segment).where(Segment.project_id == seeded["project_id"])
        ).first()
        assert db_segment.cache_key is None
        assert db_segment.generation_version == 4

    assert not seeded["segment_audio"].exists()
    assert not seeded["preview_audio"].exists()
    assert client.get("/generation-status").json() == {"active": False}


def test_failed_load_leaves_project_untouched_and_releases_lock(tmp_path: Path, monkeypatch):
    seeded = _seed_project_with_files(tmp_path, tts_model="1.7b")

    def _raise(model_id: str) -> None:
        raise RuntimeError("swap failed: OOM")

    monkeypatch.setattr(app_main.tts_client, "load_model", _raise)

    response = client.post(f"/projects/{seeded['project_id']}/model", json={"model_id": "0.6b"})

    assert response.status_code == 502

    project = client.get(f"/projects/{seeded['project_id']}").json()
    assert project["tts_model"] == "1.7b"  # D-02: unchanged
    assert project["segments"][0]["generation_status"] == "complete"  # untouched
    assert project["segments"][0]["audio_path"] == str(seeded["segment_audio"])
    assert seeded["segment_audio"].exists()  # never unlinked
    assert seeded["preview_audio"].exists()

    # Lock released despite the failure — a subsequent call is not 409'd.
    assert client.get("/generation-status").json() == {"active": False}


def test_rejects_when_another_generation_holds_the_lock(tmp_path: Path, monkeypatch):
    seeded = _seed_project_with_files(tmp_path)
    assert app_main.try_claim_generation("segment:unrelated")
    try:
        response = client.post(
            f"/projects/{seeded['project_id']}/model", json={"model_id": "0.6b"}
        )
        assert response.status_code == 409
    finally:
        app_main.release_generation()
