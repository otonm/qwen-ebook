"""Global single-flight generation lock (generation_worker.try_claim_
generation): only one generation — a character preview, a per-row segment,
or a whole batch run, in ANY project — may be in flight across the app at
once. Every other generation-triggering endpoint is rejected with 409
(character preview / per-row segment) or {"status": "busy"} (batch start)
while the slot is held, and GET /generation-status reflects it live.

Runs entirely against TTS_BACKEND=mock/LLM_BACKEND=mock — no GPU needed.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

os.environ.setdefault("LLM_BACKEND", "mock")
os.environ.setdefault("TTS_BACKEND", "mock")

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Character, Project, Segment  # noqa: E402

init_db()
# Persistent portal (see test_generation.py/test_wizard_endpoints.py) so
# fire-and-forget background tasks (character preview, batch) survive
# across calls, and so requests issued from a background Python thread
# below share the same event loop as the main thread's calls.
client = TestClient(app)
client.__enter__()


def _seed_project_with_segment(text: str = "Hello there.") -> dict:
    project_id = uuid.uuid4().hex
    character_id = uuid.uuid4().hex
    segment_id = uuid.uuid4().hex
    with Session(engine) as session:
        session.add(
            Project(id=project_id, filename="t.txt", source_text=text, status="ready")
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
                text=text,
                voice_instructions="calm",
            )
        )
        session.commit()
    return {"project_id": project_id, "character_id": character_id, "segment_id": segment_id}


def _wait_for_idle(timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not client.get("/generation-status").json()["active"]:
            return
        time.sleep(0.05)
    raise TimeoutError(f"generation lock still held after {timeout}s")


def test_generation_status_idle_when_nothing_running():
    _wait_for_idle()
    assert client.get("/generation-status").json() == {"active": False}


def test_segment_generate_blocks_character_preview_across_projects(monkeypatch):
    """Proves the lock is GLOBAL (not per-project): a slow per-row segment
    generate in project A blocks a character preview trigger in an
    unrelated project B while it's in flight."""

    def _slow_synthesize(text: str, speaker: str) -> bytes:
        time.sleep(0.3)
        return b"SEGMENT-BYTES"

    monkeypatch.setattr("app.main.synthesize", _slow_synthesize)

    project_a = _seed_project_with_segment()
    project_b = _seed_project_with_segment()

    results: dict[str, object] = {}

    def _run_segment_generate():
        results["segment"] = client.post(f"/segments/{project_a['segment_id']}/generate")

    thread = threading.Thread(target=_run_segment_generate)
    thread.start()
    time.sleep(0.1)  # let the segment generate claim the lock and start "synthesizing"

    assert client.get("/generation-status").json()["active"] is True

    blocked = client.post(f"/characters/{project_b['character_id']}/preview")
    assert blocked.status_code == 409

    thread.join()
    assert results["segment"].status_code == 200
    _wait_for_idle()


def test_character_preview_blocks_segment_generate_while_in_flight(monkeypatch):
    """The reverse direction: a slow character preview blocks a per-row
    segment generate attempt in the SAME project while it's in flight."""

    def _slow_synthesize(text: str, speaker: str) -> bytes:
        time.sleep(0.3)
        return b"PREVIEW-BYTES"

    monkeypatch.setattr("app.main.synthesize", _slow_synthesize)

    seed = _seed_project_with_segment()

    trigger = client.post(f"/characters/{seed['character_id']}/preview")
    assert trigger.status_code == 200
    # Fire-and-forget: give the background task a moment to actually claim
    # the lock and start "synthesizing" before probing it.
    time.sleep(0.1)

    assert client.get("/generation-status").json()["active"] is True

    blocked = client.post(f"/segments/{seed['segment_id']}/generate")
    assert blocked.status_code == 409

    _wait_for_idle()
    # Segment was never flipped to "generating" by the rejected attempt —
    # a normal generate call now succeeds cleanly.
    assert client.post(f"/segments/{seed['segment_id']}/generate").status_code == 200


def test_batch_generation_blocks_per_row_generate_in_different_project(monkeypatch):
    """A whole batch run claims the lock for its FULL duration (not just
    per-segment) — a per-row generate in an unrelated project is rejected
    for as long as the batch is running."""

    def _slow_synthesize(text: str, speaker: str) -> bytes:
        time.sleep(0.15)
        return b"BATCH-BYTES"

    monkeypatch.setattr("app.main.synthesize", _slow_synthesize)

    project_id = uuid.uuid4().hex
    character_id = uuid.uuid4().hex
    segment_ids = [uuid.uuid4().hex, uuid.uuid4().hex]
    with Session(engine) as session:
        session.add(
            Project(id=project_id, filename="batch.txt", source_text="a\nb", status="ready")
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
        for order, segment_id in enumerate(segment_ids):
            session.add(
                Segment(
                    id=segment_id,
                    project_id=project_id,
                    order=order,
                    character_id=character_id,
                    text=f"line {order}",
                    voice_instructions="calm",
                )
            )
        session.commit()

    other = _seed_project_with_segment()

    start = client.post(f"/projects/{project_id}/generate")
    assert start.status_code == 202
    assert start.json()["status"] == "started"
    time.sleep(0.05)

    assert client.get("/generation-status").json()["active"] is True

    blocked = client.post(f"/segments/{other['segment_id']}/generate")
    assert blocked.status_code == 409

    busy = client.post(f"/projects/{project_id}/generate")
    assert busy.json()["status"] in ("already_running", "busy")

    _wait_for_idle(timeout=10.0)
    assert client.post(f"/segments/{other['segment_id']}/generate").status_code == 200


def test_lock_releases_after_batch_cancel(monkeypatch):
    """Cancelling a live batch must still release the global slot (via the
    task's done-callback) — otherwise every other generation control would
    stay disabled forever after a Stop."""

    def _slow_synthesize(text: str, speaker: str) -> bytes:
        time.sleep(1.0)
        return b"SLOW-BYTES"

    monkeypatch.setattr("app.main.synthesize", _slow_synthesize)

    seed = _seed_project_with_segment()
    start = client.post(f"/projects/{seed['project_id']}/generate")
    assert start.status_code == 202
    time.sleep(0.1)
    assert client.get("/generation-status").json()["active"] is True

    cancel = client.post(f"/projects/{seed['project_id']}/generate/cancel")
    assert cancel.status_code == 200

    _wait_for_idle()
    assert client.post(f"/segments/{seed['segment_id']}/generate").status_code == 200
