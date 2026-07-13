"""Wizard backend endpoint tests (Plan 02-04): preset voice list, character
PATCH/merge (WIZ-02/WIZ-03), and explicit-trigger race-safe voice-preview
generation + serving (WIZ-04/WIZ-05, Pitfall 5). PATCH invalidates a stale
preview but never auto-generates — generation only fires via
POST /characters/{id}/preview.

Runs entirely against LLM_BACKEND=mock/TTS_BACKEND=mock so it needs no
network/GPU/Grok key, same discipline as test_analysis_pipeline.py.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("LLM_BACKEND", "mock")
os.environ.setdefault("TTS_BACKEND", "mock")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
# Enter the TestClient's context (rather than the bare `TestClient(app)`
# other test modules use) so a single portal/event loop persists across
# every call in this module — needed here (unlike the other test modules)
# because eager preview generation is a fire-and-forget asyncio task that
# does a genuine cross-thread run_in_threadpool() hop; a fresh portal spun
# up per call (the bare-TestClient default) tears its loop down the moment
# each request returns, orphaning that task before the threadpool hop ever
# completes.
client = TestClient(app)
client.__enter__()

# Mock analyze() always returns exactly two characters ("Narrator" +
# "Alex") for a >=3-paragraph text — see app/analysis_client.py
# _mock_analyze(). Reused here to seed a project with two characters +
# segments without hand-rolling a second fixture pipeline.
SAMPLE_TEXT = (
    "The old lighthouse keeper watched the storm roll in from the north.\n\n"
    '"We should leave now," said Maria, gripping the rail. "The tide will '
    'not wait for us."\n\n'
    "He nodded slowly, and together they climbed down the wet stone steps."
)


def _wait_for_ready(project_id: str, timeout_seconds: float = 5.0) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"/projects/{project_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in ("ready", "error"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"Project {project_id} did not settle within {timeout_seconds}s")


def _seed_project() -> dict:
    """Create a project via the mock analysis pipeline and wait for it to
    have two persisted characters + segments."""
    files = {"file": ("sample.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")}
    create_response = client.post("/projects", files=files)
    assert create_response.status_code == 201
    project_id = create_response.json()["id"]
    project = _wait_for_ready(project_id)
    assert project["status"] == "ready"
    assert len(project["characters"]) == 2
    return project


# --- GET /voices -------------------------------------------------------


def test_voices_returns_nonempty_preset_list():
    response = client.get("/voices")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) > 0
    for voice in body:
        assert "name" in voice
        assert "label" in voice


# --- PATCH /characters/{id} ---------------------------------------------


def test_patch_character_renames_and_persists():
    project = _seed_project()
    character_id = project["characters"][0]["id"]

    response = client.patch(f"/characters/{character_id}", json={"name": "Renamed"})
    assert response.status_code == 200

    updated = client.get(f"/projects/{project['id']}").json()
    character = next(c for c in updated["characters"] if c["id"] == character_id)
    assert character["name"] == "Renamed"


def test_patch_character_edits_description_and_persists():
    project = _seed_project()
    character_id = project["characters"][0]["id"]

    response = client.patch(
        f"/characters/{character_id}", json={"description": "A new backstory."}
    )
    assert response.status_code == 200

    updated = client.get(f"/projects/{project['id']}").json()
    character = next(c for c in updated["characters"] if c["id"] == character_id)
    assert character["description"] == "A new backstory."


def test_patch_character_assigns_voice_and_persists():
    project = _seed_project()
    character_id = project["characters"][0]["id"]

    response = client.patch(
        f"/characters/{character_id}",
        json={"voice_preset": "", "voice_instructions": "a warm, gentle tone"},
    )
    assert response.status_code == 200

    updated = client.get(f"/projects/{project['id']}").json()
    character = next(c for c in updated["characters"] if c["id"] == character_id)
    assert character["voice_preset"] == ""
    assert character["voice_instructions"] == "a warm, gentle tone"


def test_patch_unknown_character_404s():
    response = client.patch("/characters/does-not-exist", json={"name": "X"})
    assert response.status_code == 404


# --- POST /characters/{id}/merge ----------------------------------------


def test_merge_reassigns_segments_and_deletes_source():
    project = _seed_project()
    source, target = project["characters"][0], project["characters"][1]
    source_segment_count = sum(
        1 for s in project["segments"] if s["character_id"] == source["id"]
    )
    assert source_segment_count > 0
    total_segments_before = len(project["segments"])

    response = client.post(f"/characters/{source['id']}/merge", json={"target_id": target["id"]})
    assert response.status_code == 200

    updated = client.get(f"/projects/{project['id']}").json()
    assert len(updated["characters"]) == 1
    assert len(updated["segments"]) == total_segments_before
    assert all(s["character_id"] == target["id"] for s in updated["segments"])

    # source id is gone — further operations against it 404.
    patch_response = client.patch(f"/characters/{source['id']}", json={"name": "ghost"})
    assert patch_response.status_code == 404


def test_merge_unknown_ids_404s():
    project = _seed_project()
    character_id = project["characters"][0]["id"]

    response = client.post(f"/characters/{character_id}/merge", json={"target_id": "nope"})
    assert response.status_code == 404


# --- Explicit-trigger voice preview generation + serving (WIZ-04/WIZ-05) -


def _wait_for_preview(character_id: str, timeout_seconds: float = 5.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"/characters/{character_id}/preview.wav")
        if response.status_code == 200:
            return
        time.sleep(0.05)
    raise TimeoutError(f"Character {character_id} preview not ready within {timeout_seconds}s")


def test_preview_not_ready_returns_409():
    project = _seed_project()
    character_id = project["characters"][0]["id"]

    response = client.get(f"/characters/{character_id}/preview.wav")

    assert response.status_code == 409


def test_patch_voice_invalidates_but_does_not_auto_generate():
    """A voice-field PATCH (preset or instructions) must NOT eagerly kick
    off generation — the user triggers a fresh preview explicitly via
    POST /characters/{id}/preview. This mirrors GEN-03's invalidate-only
    contract for segments."""
    project = _seed_project()
    character_id = project["characters"][0]["id"]

    # Establish a preview first via the explicit trigger.
    trigger = client.post(f"/characters/{character_id}/preview")
    assert trigger.status_code == 200
    _wait_for_preview(character_id)
    assert client.get(f"/characters/{character_id}/preview.wav").status_code == 200

    # A voice-field PATCH invalidates the now-stale preview...
    response = client.patch(f"/characters/{character_id}", json={"voice_preset": ""})
    assert response.status_code == 200

    # ...but does not regenerate it automatically. Give any accidental
    # background task a moment to (not) run before asserting.
    time.sleep(0.3)
    assert client.get(f"/characters/{character_id}/preview.wav").status_code == 409

    # The user's explicit trigger still works and produces a real preview.
    trigger_again = client.post(f"/characters/{character_id}/preview")
    assert trigger_again.status_code == 200
    _wait_for_preview(character_id)
    preview_response = client.get(f"/characters/{character_id}/preview.wav")
    assert preview_response.status_code == 200
    assert preview_response.headers["content-type"] == "audio/wav"
    assert len(preview_response.content) > 0


def test_patch_non_voice_field_leaves_existing_preview_intact():
    """Renaming a character (no voice_preset/voice_instructions in the
    patch) must not touch an already-generated preview."""
    project = _seed_project()
    character_id = project["characters"][0]["id"]

    assert client.post(f"/characters/{character_id}/preview").status_code == 200
    _wait_for_preview(character_id)

    response = client.patch(f"/characters/{character_id}", json={"name": "Renamed"})
    assert response.status_code == 200

    assert client.get(f"/characters/{character_id}/preview.wav").status_code == 200


def test_trigger_preview_generates_on_demand():
    """CFG-03 Config Panel: a character whose voice was never (re)saved via
    PATCH has no preview until POST /characters/{id}/preview is called."""
    project = _seed_project()
    character_id = project["characters"][0]["id"]

    assert client.get(f"/characters/{character_id}/preview.wav").status_code == 409

    response = client.post(f"/characters/{character_id}/preview")
    assert response.status_code == 200
    assert response.json()["status"] == "generating"

    _wait_for_preview(character_id)

    preview_response = client.get(f"/characters/{character_id}/preview.wav")
    assert preview_response.status_code == 200
    assert preview_response.headers["content-type"] == "audio/wav"
    assert len(preview_response.content) > 0


def test_trigger_preview_missing_character_404s():
    response = client.post("/characters/does-not-exist/preview")
    assert response.status_code == 404


def test_rapid_preview_trigger_race_last_wins(monkeypatch):
    """Pitfall 5: a slow first generation must not clobber a faster,
    newer second generation's preview once both settle. Now that PATCH no
    longer auto-generates, the race is driven by two rapid explicit
    POST /characters/{id}/preview calls against two different presets."""

    def _controlled_synthesize(text: str, speaker: str) -> bytes:
        if speaker == "slow":
            time.sleep(0.3)
            return b"SLOW-PREVIEW-BYTES"
        time.sleep(0.02)
        return b"FAST-PREVIEW-BYTES"

    monkeypatch.setattr("app.main.synthesize", _controlled_synthesize)

    project = _seed_project()
    character_id = project["characters"][0]["id"]

    assign_slow = client.patch(f"/characters/{character_id}", json={"voice_preset": "slow"})
    assert assign_slow.status_code == 200
    first = client.post(f"/characters/{character_id}/preview")
    assert first.status_code == 200

    assign_fast = client.patch(f"/characters/{character_id}", json={"voice_preset": "fast"})
    assert assign_fast.status_code == 200
    second = client.post(f"/characters/{character_id}/preview")
    assert second.status_code == 200

    # Give both background generations (slow ~0.3s, fast ~0.02s) time to
    # fully settle before asserting the final state.
    time.sleep(0.5)

    preview_response = client.get(f"/characters/{character_id}/preview.wav")
    assert preview_response.status_code == 200
    assert preview_response.content == b"FAST-PREVIEW-BYTES"


# --- POST /characters/undo-merge (WR-01) --------------------------------


def test_undo_merge_rejects_segment_from_other_project():
    """WR-01: the undo snapshot is entirely client-supplied — a segment_id
    that doesn't belong to the restored character's project must be
    rejected, not silently reassigned."""
    project = _seed_project()
    source_id, target_id = project["characters"][0]["id"], project["characters"][1]["id"]

    merge_response = client.post(f"/characters/{source_id}/merge", json={"target_id": target_id})
    assert merge_response.status_code == 200
    undo = merge_response.json()["undo"]

    other_project = _seed_project()
    other_segment_id = other_project["segments"][0]["id"]

    response = client.post(
        "/characters/undo-merge",
        json={"character": undo["character"], "segment_ids": [other_segment_id]},
    )
    assert 400 <= response.status_code < 500

    # Rejected — the fabricated character must not have been created; a
    # subsequent legitimate undo-merge with this same snapshot still
    # succeeds (would 409 "already exists" if the invalid call had leaked
    # a created row).
    retry = client.post(
        "/characters/undo-merge",
        json={"character": undo["character"], "segment_ids": undo["segment_ids"]},
    )
    assert retry.status_code == 200


def test_undo_merge_restores_character_and_segments():
    """Baseline happy path for the endpoint WR-01 adds validation to."""
    project = _seed_project()
    source_id, target_id = project["characters"][0]["id"], project["characters"][1]["id"]

    merge_response = client.post(f"/characters/{source_id}/merge", json={"target_id": target_id})
    assert merge_response.status_code == 200
    undo = merge_response.json()["undo"]

    response = client.post(
        "/characters/undo-merge",
        json={"character": undo["character"], "segment_ids": undo["segment_ids"]},
    )
    assert response.status_code == 200
    assert response.json()["id"] == source_id
