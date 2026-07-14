"""Regression tests for GEN-06/GEN-07/GEN-08: true-kill cancellation across
all three generation paths (segment, character preview, batch).

Runs entirely against TTS_BACKEND=mock/LLM_BACKEND=mock — no GPU needed.
Mock synthesis can't be interrupted mid-call the way real ROCm inference
can (there is no decode loop to abort — the mock backend returns a fixed
WAV instantly, so these tests monkeypatch a slow synthesize to simulate an
in-flight call long enough to cancel against). What these tests prove is
the TRUE-KILL CONTRACT: tts_client.cancel() fires on the right path
(a spy replaces it), the local task is stopped, the lock is held until the
underlying call is truly done (Pitfall 2), and a stopped row settles to
"pending" (never "error") with no stuck state. The actual mid-decode abort
timing on real ROCm hardware is hardware-verified separately by 04-01's
spike_cancel_hw.py (~46ms decode-loop stop), not re-proven here.
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
# Persistent portal (see test_generation_lock.py) so fire-and-forget
# background tasks survive across calls and share the same event loop as
# requests issued from a background Python thread below.
client = TestClient(app)
client.__enter__()

_SLOW_SLEEP_SECONDS = 0.3


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


def _slow_synthesize(text: str, speaker: str, instruct: str | None = None) -> bytes:
    """A non-interruptible slow synth — used only by the hold-until-
    stopped test below, which deliberately wants NOTHING to shorten the
    call, to prove the lock stays held for the call's full real duration
    regardless of whether an interrupt landed."""
    time.sleep(_SLOW_SLEEP_SECONDS)
    return b"SLOW-BYTES"


def _make_interruptible_synthesize(stop_event: threading.Event) -> callable:
    """Simulates tts_service's real StoppingCriteria decode loop (04-01):
    polls `stop_event` instead of blocking unconditionally, raising as
    soon as it's set. This is what makes tts_client.cancel() actually
    SHORTEN the call in these tests, mirroring the real HTTP-boundary
    mechanism (server observes the cancel, the client's blocking call
    unblocks promptly) closely enough to meaningfully test the true-kill
    contract, rather than testing something structurally impossible for
    an unconditional sleep to satisfy."""

    def _synthesize(text: str, speaker: str, instruct: str | None = None) -> bytes:
        deadline = time.time() + _SLOW_SLEEP_SECONDS
        while time.time() < deadline:
            if stop_event.is_set():
                raise RuntimeError("synthesize interrupted by cancel")
            time.sleep(0.01)
        return b"SLOW-BYTES"

    return _synthesize


def _make_cancel_spy(calls: list, stop_event: threading.Event | None = None) -> callable:
    """A tts_client.cancel() replacement that records it was invoked
    instead of actually POSTing anywhere (mock backend's real cancel() is
    a no-op anyway — this spy proves the CALL SITE fires, not the HTTP
    behavior, which 04-02's own tests already cover). When paired with
    _make_interruptible_synthesize, also sets `stop_event` so the
    in-flight mock call actually observes the interrupt."""

    def _cancel() -> None:
        calls.append(True)
        if stop_event is not None:
            stop_event.set()

    return _cancel


# --- Segment path (GEN-06/GEN-07) ------------------------------------------


def test_segment_cancel_true_kills_and_resets_to_pending(monkeypatch):
    cancel_calls: list = []
    stop_event = threading.Event()
    monkeypatch.setattr("app.main.synthesize", _make_interruptible_synthesize(stop_event))
    monkeypatch.setattr("app.tts_client.cancel", _make_cancel_spy(cancel_calls, stop_event))

    seed = _seed_project_with_segment()
    segment_id = seed["segment_id"]

    start = client.post(f"/segments/{segment_id}/generate")
    assert start.status_code == 202
    assert start.json()["status"] == "generating"
    time.sleep(0.1)  # let it claim the lock and start "synthesizing"

    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        assert segment.generation_status == "generating"

    cancel = client.post(f"/segments/{segment_id}/generate/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    assert cancel_calls, "tts_client.cancel() was not invoked by the segment cancel path"

    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        # A user stop is not a failure — reset to "pending", never "error".
        assert segment.generation_status == "pending"

    _wait_for_idle()


def test_segment_cancel_does_not_mask_an_unrelated_genuine_failure(monkeypatch):
    """WR-01 regression: cancel_segment_generation must not blanket-reset
    any non-"complete" status to "pending". Here the task fails for a
    genuinely unrelated reason and is allowed to settle *before* any cancel
    is requested (no request_stop() has fired for this label), so
    regenerate_segment's own exception handler correctly writes "error".
    A cancel call arriving afterward must leave that error untouched —
    not silently relabel it as a clean stop just because the label was
    touched.

    Note: deliberately does NOT race the cancel against the failure (see
    generation_worker._stop_requested's docstring / 04-03's own
    request_stop design) — if a stop is requested for a label while
    regenerate_segment's exception handler is concurrently deciding
    pending-vs-error for that same label, the flag alone can't distinguish
    "this failure was caused by the cancel" from "coincidental timing";
    that is a separate, pre-existing ambiguity in regenerate_segment
    itself, not the redundant-reset bug this test targets."""

    def _always_fails(text: str, speaker: str, instruct: str | None = None) -> bytes:
        raise RuntimeError("unrelated backend crash — nothing to do with cancellation")

    monkeypatch.setattr("app.main.synthesize", _always_fails)

    seed = _seed_project_with_segment()
    segment_id = seed["segment_id"]

    start = client.post(f"/segments/{segment_id}/generate")
    assert start.status_code == 202
    _wait_for_idle()  # let the unrelated failure settle before any cancel

    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        assert segment.generation_status == "error"
        assert segment.generation_error == "TTS synthesis failed"

    cancel = client.post(f"/segments/{segment_id}/generate/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "not_running"

    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        # The genuine error must survive — never overwritten to "pending"
        # just because a cancel call was later issued against this label.
        assert segment.generation_status == "error"
        assert segment.generation_error == "TTS synthesis failed"

    # No stuck "generating" row — a fresh generate succeeds immediately.
    fresh = client.post(f"/segments/{segment_id}/generate")
    assert fresh.status_code == 202
    _wait_for_idle()


def test_segment_cancel_when_nothing_running_is_noop():
    seed = _seed_project_with_segment()
    response = client.post(f"/segments/{seed['segment_id']}/generate/cancel")
    assert response.status_code == 200
    assert response.json() == {"status": "not_running"}


# --- Character-preview path (GEN-06/GEN-07) --------------------------------


def test_preview_cancel_true_kills_and_releases_lock(monkeypatch):
    cancel_calls: list = []
    stop_event = threading.Event()
    monkeypatch.setattr("app.main.synthesize", _make_interruptible_synthesize(stop_event))
    monkeypatch.setattr("app.tts_client.cancel", _make_cancel_spy(cancel_calls, stop_event))

    seed = _seed_project_with_segment()
    character_id = seed["character_id"]

    start = client.post(f"/characters/{character_id}/preview")
    assert start.status_code == 200
    assert start.json()["status"] == "generating"
    time.sleep(0.1)

    assert client.get("/generation-status").json()["active"] is True

    cancel = client.post(f"/characters/{character_id}/preview/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    assert cancel_calls, "tts_client.cancel() was not invoked by the preview cancel path"

    _wait_for_idle()

    # No per-character status column to reset — the cancelled generation
    # never got the chance to write a preview file, so the absent
    # preview_audio_path already reflects "no preview".
    with Session(engine) as session:
        character = session.get(Character, character_id)
        assert character.preview_audio_path is None

    # The slot is free — a fresh preview trigger succeeds immediately.
    fresh = client.post(f"/characters/{character_id}/preview")
    assert fresh.status_code == 200
    _wait_for_idle()


def test_preview_cancel_when_nothing_running_is_noop():
    seed = _seed_project_with_segment()
    response = client.post(f"/characters/{seed['character_id']}/preview/cancel")
    assert response.status_code == 200
    assert response.json() == {"status": "not_running"}


# --- Batch path (GEN-08, D-01) ----------------------------------------------


def test_batch_cancel_true_kills_in_flight_segment(monkeypatch):
    """Extends test_generation_lock.py's test_lock_releases_after_batch_
    cancel with the true-kill assertion: tts_client.cancel() must actually
    fire, proving the currently-synthesizing segment is killed, not just
    the queue of remaining segments (D-01)."""
    cancel_calls: list = []
    stop_event = threading.Event()
    monkeypatch.setattr("app.main.synthesize", _make_interruptible_synthesize(stop_event))
    monkeypatch.setattr("app.tts_client.cancel", _make_cancel_spy(cancel_calls, stop_event))

    seed = _seed_project_with_segment()
    project_id = seed["project_id"]

    start = client.post(f"/projects/{project_id}/generate")
    assert start.status_code == 202
    time.sleep(0.1)
    assert client.get("/generation-status").json()["active"] is True

    cancel = client.post(f"/projects/{project_id}/generate/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    assert cancel_calls, "tts_client.cancel() was not invoked by the batch cancel path"

    _wait_for_idle()

    # No stuck "generating" row — a fresh per-row generate on the same
    # segment succeeds immediately after the cancel.
    fresh = client.post(f"/segments/{seed['segment_id']}/generate")
    assert fresh.status_code == 202
    _wait_for_idle()


# --- Hold-until-stopped (Pitfall 2) ------------------------------------------


def test_lock_stays_active_until_cancel_settles(monkeypatch):
    """GET /generation-status must keep reporting active:true for the
    FULL duration of a cancel — the lock is only released via the task's
    own done-callback once the underlying call has truly finished, never
    merely because task.cancel() was issued. Proven by running the cancel
    call on a background thread (it blocks on `await task` inside the
    handler for the mock synth's full sleep duration, mirroring the real
    HTTP-boundary case where a threadpool call can't be forcibly
    interrupted) and polling /generation-status concurrently."""
    monkeypatch.setattr("app.main.synthesize", _slow_synthesize)

    seed = _seed_project_with_segment()
    segment_id = seed["segment_id"]

    start = client.post(f"/segments/{segment_id}/generate")
    assert start.status_code == 202
    time.sleep(0.1)
    assert client.get("/generation-status").json()["active"] is True

    results: dict = {}

    def _run_cancel() -> None:
        results["cancel"] = client.post(f"/segments/{segment_id}/generate/cancel")

    thread = threading.Thread(target=_run_cancel)
    thread.start()

    # The cancel handler is still awaiting the task's true stop (the mock
    # synth's run_in_threadpool call can't be forcibly interrupted, same
    # as the real httpx-to-tts_service call — task.cancel() only takes
    # effect once the underlying blocking call returns) — the lock must
    # still report active while that's in flight.
    time.sleep(_SLOW_SLEEP_SECONDS * 0.4)
    assert client.get("/generation-status").json()["active"] is True

    thread.join()
    assert results["cancel"].status_code == 200
    assert results["cancel"].json()["status"] == "cancelled"

    # Only once the cancel call has actually returned is the task truly
    # done and the lock free.
    assert client.get("/generation-status").json()["active"] is False

    _wait_for_idle()
