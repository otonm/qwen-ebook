"""Per-segment generation, content-hash cache, and edit-invalidates tests
(Plan 03-01, updated 03-08): POST /segments/{id}/generate, PATCH
/segments/{id} invalidate-only (GEN-03, D-06 reversed during 03 UAT — see
03-CONTEXT.md), cache hit/bust via compute_cache_key (GEN-02), and the
generation_version last-request-wins guard (Pitfall 2).

Runs entirely against TTS_BACKEND=mock so it needs no GPU — same discipline
as test_wizard_endpoints.py. Segments are seeded directly through a Session
rather than running the full analysis pipeline.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

os.environ.setdefault("LLM_BACKEND", "mock")
os.environ.setdefault("TTS_BACKEND", "mock")

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Character, Project, Segment  # noqa: E402

init_db()
# Enter the TestClient's context (not the bare `TestClient(app)` other
# modules use) so the fire-and-forget background regen tasks (a genuine
# cross-thread run_in_threadpool() hop) get a persistent portal/event loop
# to complete on — same reasoning as test_wizard_endpoints.py.
client = TestClient(app)
client.__enter__()


def _seed_segment(text: str = "Hello there.", voice_instructions: str = "calm") -> dict:
    """Create a Project + narrator Character + one Segment directly through
    a Session — no need to run the full analysis pipeline for these tests."""
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
                voice_instructions=voice_instructions,
            )
        )
        session.commit()

    return {
        "project_id": project_id,
        "character_id": character_id,
        "segment_id": segment_id,
    }


def _get_segment(segment_id: str) -> Segment:
    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        assert segment is not None
        session.expunge(segment)
        return segment


# --- POST /segments/{id}/generate ----------------------------------------


def test_generate_segment_produces_audio():
    seed = _seed_segment()
    segment_id = seed["segment_id"]

    response = client.post(f"/segments/{segment_id}/generate")
    assert response.status_code == 200
    assert response.json()["generation_status"] == "complete"

    segment = _get_segment(segment_id)
    assert segment.audio_path is not None
    assert Path(segment.audio_path).is_file()
    assert segment.cache_key is not None

    audio_response = client.get(f"/segments/{segment_id}/audio.wav")
    assert audio_response.status_code == 200
    assert audio_response.headers["content-type"] == "audio/wav"
    assert len(audio_response.content) > 0


# --- PATCH /segments/{id} — cache hit/bust (GEN-02/GEN-03) ---------------


def test_regenerate_only_on_edit_reuses_cache():
    """A patch never regenerates (see test_patch_invalidates_without_
    regenerating below), so "cache reuse" is now exercised directly at the
    generate endpoint: calling POST .../generate twice with no edit in
    between must hit the cache (no rewrite, same file/mtime)."""
    seed = _seed_segment()
    segment_id = seed["segment_id"]

    assert client.post(f"/segments/{segment_id}/generate").status_code == 200

    before = _get_segment(segment_id)
    audio_path_before = before.audio_path
    cache_key_before = before.cache_key
    mtime_before = Path(audio_path_before).stat().st_mtime_ns

    second_response = client.post(f"/segments/{segment_id}/generate")
    assert second_response.status_code == 200

    after = _get_segment(segment_id)
    assert after.cache_key == cache_key_before
    assert after.audio_path == audio_path_before
    assert Path(after.audio_path).stat().st_mtime_ns == mtime_before


def test_edit_text_busts_cache():
    seed = _seed_segment()
    segment_id = seed["segment_id"]

    assert client.post(f"/segments/{segment_id}/generate").status_code == 200
    cache_key_before = _get_segment(segment_id).cache_key

    patch_response = client.patch(
        f"/segments/{segment_id}", json={"text": "A brand new line."}
    )
    assert patch_response.status_code == 200
    # Invalidate-only: no synthesis happens as a side effect of the patch.
    assert _get_segment(segment_id).audio_path is None

    generate_response = client.post(f"/segments/{segment_id}/generate")
    assert generate_response.status_code == 200

    after = _get_segment(segment_id)
    assert after.generation_status == "complete"
    assert after.cache_key != cache_key_before


# --- generation_version last-request-wins guard (Pitfall 2) --------------


def test_patch_bumps_generation_version(monkeypatch):
    """Two rapid PATCHes must leave generation_version incremented by 2,
    with no synthesis call fired by either — a patch invalidates only."""

    call_count = {"n": 0}

    def _counting_synthesize(text: str, speaker: str) -> bytes:
        call_count["n"] += 1
        return b"SHOULD-NOT-BE-CALLED"

    monkeypatch.setattr("app.main.synthesize", _counting_synthesize)

    seed = _seed_segment(text="original")
    segment_id = seed["segment_id"]
    version_before = _get_segment(segment_id).generation_version

    first = client.patch(f"/segments/{segment_id}", json={"text": "edit one"})
    assert first.status_code == 200
    second = client.patch(f"/segments/{segment_id}", json={"text": "edit two"})
    assert second.status_code == 200

    segment = _get_segment(segment_id)
    assert segment.generation_version == version_before + 2
    assert segment.generation_status == "pending"
    assert segment.audio_path is None
    assert call_count["n"] == 0


# --- Patch invalidates only, no auto-regeneration (GEN-03/D-06 reversed) -


def test_patch_invalidates_without_regenerating(monkeypatch):
    call_count = {"n": 0}

    def _counting_synthesize(text: str, speaker: str) -> bytes:
        call_count["n"] += 1
        return b"AUDIO-BYTES"

    monkeypatch.setattr("app.main.synthesize", _counting_synthesize)

    seed = _seed_segment()
    segment_id = seed["segment_id"]

    assert client.post(f"/segments/{segment_id}/generate").status_code == 200
    assert call_count["n"] == 1
    generated = _get_segment(segment_id)
    assert generated.audio_path is not None
    old_audio_path = generated.audio_path

    patch_response = client.patch(
        f"/segments/{segment_id}", json={"text": "A different line."}
    )
    assert patch_response.status_code == 200
    body = patch_response.json()
    assert body["generation_status"] == "pending"
    assert body["audio_path"] is None

    # No synthesis call happened as a side effect of the patch.
    assert call_count["n"] == 1

    patched = _get_segment(segment_id)
    assert patched.generation_status == "pending"
    assert patched.audio_path is None
    # The stale file was unlinked, not just detached from the row.
    assert not Path(old_audio_path).exists()


# --- POST /segments/bulk-reassign (TBL-03) --------------------------------


def _seed_second_character(project_id: str, name: str = "Other") -> str:
    character_id = uuid.uuid4().hex
    with Session(engine) as session:
        session.add(
            Character(
                id=character_id,
                project_id=project_id,
                name=name,
                description="a second character",
                is_narrator=False,
                voice_instructions="",
            )
        )
        session.commit()
    return character_id


def test_bulk_reassign_updates_all_rows():
    seed = _seed_segment()
    project_id = seed["project_id"]
    target_id = _seed_second_character(project_id)

    seed2 = _seed_segment()
    with Session(engine) as session:
        segment = session.get(Segment, seed2["segment_id"])
        segment.project_id = project_id
        session.add(segment)
        session.commit()

    response = client.post(
        "/segments/bulk-reassign",
        json={
            "segment_ids": [seed["segment_id"], seed2["segment_id"]],
            "character_id": target_id,
        },
    )
    assert response.status_code == 200
    assert response.json()["updated"] == 2

    for segment_id in (seed["segment_id"], seed2["segment_id"]):
        segment = _get_segment(segment_id)
        assert segment.character_id == target_id


def test_bulk_reassign_bumps_generation_version():
    seed = _seed_segment()
    project_id = seed["project_id"]
    target_id = _seed_second_character(project_id)
    version_before = _get_segment(seed["segment_id"]).generation_version

    response = client.post(
        "/segments/bulk-reassign",
        json={"segment_ids": [seed["segment_id"]], "character_id": target_id},
    )
    assert response.status_code == 200

    segment = _get_segment(seed["segment_id"])
    assert segment.generation_version == version_before + 1


def test_bulk_reassign_rejects_cross_project():
    seed = _seed_segment()
    other_seed = _seed_segment()
    other_target_id = _seed_second_character(other_seed["project_id"])
    character_id_before = _get_segment(seed["segment_id"]).character_id

    response = client.post(
        "/segments/bulk-reassign",
        json={
            "segment_ids": [seed["segment_id"]],
            "character_id": other_target_id,
        },
    )
    assert 400 <= response.status_code < 500

    segment = _get_segment(seed["segment_id"])
    assert segment.character_id == character_id_before


# --- POST /projects/{id}/generate — resumable batch (GEN-05) -------------


def _seed_project_with_segments(texts: list[str]) -> tuple[str, list[str]]:
    """Create a Project + one narrator Character + one Segment per entry in
    `texts`, ordered 0..N-1. Returns (project_id, [segment_id, ...])."""
    project_id = uuid.uuid4().hex
    character_id = uuid.uuid4().hex
    segment_ids = [uuid.uuid4().hex for _ in texts]

    with Session(engine) as session:
        session.add(
            Project(
                id=project_id,
                filename="batch.txt",
                source_text="\n".join(texts),
                status="ready",
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
            )
        )
        for order, (segment_id, text) in enumerate(zip(segment_ids, texts, strict=True)):
            session.add(
                Segment(
                    id=segment_id,
                    project_id=project_id,
                    order=order,
                    character_id=character_id,
                    text=text,
                    voice_instructions="calm",
                )
            )
        session.commit()

    return project_id, segment_ids


def _wait_for_terminal(segment_ids: list[str], timeout: float = 5.0) -> None:
    """Poll until every segment in `segment_ids` reaches a terminal
    generation_status ("complete" or "error"), or `timeout` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        statuses = [_get_segment(sid).generation_status for sid in segment_ids]
        if all(status in ("complete", "error") for status in statuses):
            return
        time.sleep(0.05)


def test_batch_generates_all_pending():
    project_id, segment_ids = _seed_project_with_segments(["One.", "Two.", "Three."])

    response = client.post(f"/projects/{project_id}/generate")
    assert response.status_code == 202

    _wait_for_terminal(segment_ids)

    for segment_id in segment_ids:
        segment = _get_segment(segment_id)
        assert segment.generation_status == "complete"
        assert segment.audio_path is not None
        assert Path(segment.audio_path).is_file()


def test_batch_skips_complete_rows():
    project_id, segment_ids = _seed_project_with_segments(["One.", "Two."])

    # Pre-generate the first segment via the per-row endpoint so it has a
    # real, cache-valid audio file on disk before the batch runs.
    assert client.post(f"/segments/{segment_ids[0]}/generate").status_code == 200
    before = _get_segment(segment_ids[0])
    mtime_before = Path(before.audio_path).stat().st_mtime_ns

    response = client.post(f"/projects/{project_id}/generate")
    assert response.status_code == 202

    _wait_for_terminal(segment_ids)

    after = _get_segment(segment_ids[0])
    assert after.audio_path == before.audio_path
    assert Path(after.audio_path).stat().st_mtime_ns == mtime_before

    second = _get_segment(segment_ids[1])
    assert second.generation_status == "complete"
    assert second.audio_path is not None


def test_batch_resets_stale_generating():
    project_id, segment_ids = _seed_project_with_segments(["One."])

    # Simulate a crash mid-synthesis: the row is stuck "generating" with no
    # audio ever written.
    with Session(engine) as session:
        segment = session.get(Segment, segment_ids[0])
        segment.generation_status = "generating"
        session.add(segment)
        session.commit()

    response = client.post(f"/projects/{project_id}/generate")
    assert response.status_code == 202

    _wait_for_terminal(segment_ids)

    segment = _get_segment(segment_ids[0])
    assert segment.generation_status == "complete"
    assert segment.audio_path is not None
    assert Path(segment.audio_path).is_file()


def test_batch_continues_past_error(monkeypatch):
    from app.tts_client import synthesize as real_synthesize

    def _flaky_synthesize(text: str, speaker: str) -> bytes:
        if "boom" in text:
            raise RuntimeError("synthetic synthesis failure")
        return real_synthesize(text, speaker)

    monkeypatch.setattr("app.main.synthesize", _flaky_synthesize)

    project_id, segment_ids = _seed_project_with_segments(
        ["Segment one.", "boom segment.", "Segment three."]
    )

    response = client.post(f"/projects/{project_id}/generate")
    assert response.status_code == 202

    _wait_for_terminal(segment_ids)

    failing = _get_segment(segment_ids[1])
    assert failing.generation_status == "error"
    assert failing.generation_error is not None

    for segment_id in (segment_ids[0], segment_ids[2]):
        segment = _get_segment(segment_id)
        assert segment.generation_status == "complete"
        assert segment.audio_path is not None


# --- GET /projects — project list (PERS-02) -------------------------------


def test_list_projects_returns_saved_projects():
    seed1 = _seed_segment()
    time.sleep(0.01)  # ensure a distinct created_at ordering vs seed2
    seed2 = _seed_segment()

    response = client.get("/projects")
    assert response.status_code == 200
    body = response.json()

    by_id = {p["id"]: p for p in body}
    assert seed1["project_id"] in by_id
    assert seed2["project_id"] in by_id
    for project in body:
        assert set(project.keys()) == {"id", "filename", "status", "created_at"}

    # Newest first.
    index1 = next(i for i, p in enumerate(body) if p["id"] == seed1["project_id"])
    index2 = next(i for i, p in enumerate(body) if p["id"] == seed2["project_id"])
    assert index2 < index1


def test_list_projects_empty(monkeypatch):
    """The shared projects.db already has rows from other tests in this
    module, so a genuinely empty list can only be exercised against an
    isolated engine — swap app.main.engine for a throwaway in-memory one
    for the duration of this test (same monkeypatch-a-main-module-global
    pattern as test_patch_bumps_generation_version's synthesize swap)."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel

    # StaticPool: a bare "sqlite://" in-memory DB is otherwise per-connection
    # (SQLAlchemy opens a fresh connection per Session, each getting its own
    # empty memory DB) — StaticPool pins the whole engine to one connection
    # so the table created below is actually visible to the request below.
    empty_engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(empty_engine)
    monkeypatch.setattr("app.main.engine", empty_engine)

    response = client.get("/projects")
    assert response.status_code == 200
    assert response.json() == []
