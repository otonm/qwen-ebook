"""Per-segment generation, content-hash cache, and regenerate-on-edit tests
(Plan 03-01): POST /segments/{id}/generate, PATCH /segments/{id} auto-
regen-on-blur (GEN-03/D-06), cache hit/bust via compute_cache_key (GEN-02),
and the generation_version last-request-wins guard (Pitfall 2).

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
    seed = _seed_segment()
    segment_id = seed["segment_id"]
    character_id = seed["character_id"]

    assert client.post(f"/segments/{segment_id}/generate").status_code == 200

    before = _get_segment(segment_id)
    audio_path_before = before.audio_path
    cache_key_before = before.cache_key
    mtime_before = Path(audio_path_before).stat().st_mtime_ns

    # PATCH with the exact same values already on the row — a no-op edit
    # that still bumps generation_version and fires a background regen,
    # but must resolve to the same cache key (cache hit, no rewrite).
    patch_response = client.patch(
        f"/segments/{segment_id}",
        json={
            "character_id": character_id,
            "voice_instructions": "calm",
            "text": "Hello there.",
        },
    )
    assert patch_response.status_code == 200

    time.sleep(0.3)  # let the background regen (cache hit) settle

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

    time.sleep(0.3)  # let the background regen (cache miss) settle

    after = _get_segment(segment_id)
    assert after.generation_status == "complete"
    assert after.cache_key != cache_key_before


# --- generation_version last-request-wins guard (Pitfall 2) --------------


def test_patch_bumps_generation_version(monkeypatch):
    """Two rapid PATCHes must leave generation_version incremented by 2,
    and a slower stale in-flight regen (older version) must not clobber
    the faster, newer regen's audio once both settle — mirrors
    test_wizard_endpoints.py's test_rapid_reassignment_race_last_wins."""

    def _controlled_synthesize(text: str, speaker: str) -> bytes:
        if "slow" in text:
            time.sleep(0.3)
            return b"SLOW-AUDIO-BYTES"
        time.sleep(0.02)
        return b"FAST-AUDIO-BYTES"

    monkeypatch.setattr("app.main.synthesize", _controlled_synthesize)

    seed = _seed_segment(text="original")
    segment_id = seed["segment_id"]
    version_before = _get_segment(segment_id).generation_version

    first = client.patch(f"/segments/{segment_id}", json={"text": "slow edit"})
    assert first.status_code == 200
    second = client.patch(f"/segments/{segment_id}", json={"text": "fast edit"})
    assert second.status_code == 200

    # Give both background regenerations (slow ~0.3s, fast ~0.02s) time to
    # fully settle before asserting the final state.
    time.sleep(0.5)

    segment = _get_segment(segment_id)
    assert segment.generation_version == version_before + 2
    assert Path(segment.audio_path).read_bytes() == b"FAST-AUDIO-BYTES"
