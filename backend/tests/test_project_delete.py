"""DELETE /projects/{id}: removes the project row, its characters/segments
(no FK cascade in models.py, so this is the only cleanup path), and every
on-disk artifact (segment audio, character preview, project output).

Runs entirely against TTS_BACKEND=mock/LLM_BACKEND=mock — no GPU needed.
"""

from __future__ import annotations

import os
import threading
import time
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
# Persistent portal (see test_immediate_cancel.py/test_generation_lock.py):
# a background batch-generation task spawned by one request must survive
# into the DELETE request that cancels it, which requires both calls to
# share the same event loop.
client = TestClient(app)
client.__enter__()

_SLOW_SLEEP_SECONDS = 0.3


def _make_interruptible_synthesize(stop_event: threading.Event) -> callable:
    """Mirrors test_immediate_cancel.py's helper of the same name: polls
    stop_event instead of blocking unconditionally, so tts_client.cancel()
    actually shortens the call — needed to prove the true-kill contract
    rather than something structurally impossible for a plain sleep."""

    def _synthesize(text: str, speaker: str, instruct: str | None = None) -> bytes:
        deadline = time.time() + _SLOW_SLEEP_SECONDS
        while time.time() < deadline:
            if stop_event.is_set():
                raise RuntimeError("synthesize interrupted by cancel")
            time.sleep(0.01)
        return b"SLOW-BYTES"

    return _synthesize


def _make_cancel_spy(calls: list, stop_event: threading.Event) -> callable:
    """Mirrors test_immediate_cancel.py's helper of the same name."""

    def _cancel() -> None:
        calls.append(True)
        stop_event.set()

    return _cancel


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


def test_delete_project_true_kills_in_flight_generation(monkeypatch):
    """CR-01 regression: DELETE must use the same true-kill sequence as
    POST /generate/cancel (request_stop + tts_client.cancel + await task),
    not raw task.cancel(). Raw task.cancel() on a task awaiting
    run_in_threadpool doesn't wait for the underlying call, releasing the
    generation lock while a real synth is still orphaned in the background
    — this test proves tts_client.cancel() actually fires, and that the
    lock is free (not orphaned) immediately after the delete responds."""
    cancel_calls: list = []
    stop_event = threading.Event()
    monkeypatch.setattr("app.main.synthesize", _make_interruptible_synthesize(stop_event))
    monkeypatch.setattr("app.tts_client.cancel", _make_cancel_spy(cancel_calls, stop_event))

    project_id = uuid.uuid4().hex
    character_id = uuid.uuid4().hex
    segment_id = uuid.uuid4().hex
    with Session(engine) as session:
        session.add(
            Project(id=project_id, filename="t.txt", source_text="Hello.", status="ready")
        )
        session.add(
            Character(
                id=character_id,
                project_id=project_id,
                name="Narrator",
                description="the narrator",
                is_narrator=True,
                voice_instructions="",
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
            )
        )
        session.commit()

    start = client.post(f"/projects/{project_id}/generate")
    assert start.status_code == 202
    time.sleep(0.1)
    assert client.get("/generation-status").json()["active"] is True

    response = client.delete(f"/projects/{project_id}")
    assert response.status_code == 204

    assert cancel_calls, "tts_client.cancel() was not invoked by the delete path"

    # No orphaned lock left behind — the very next request can claim it
    # immediately, proving delete_project awaited the real stop rather than
    # releasing the lock the instant task.cancel() was issued.
    assert client.get("/generation-status").json()["active"] is False
