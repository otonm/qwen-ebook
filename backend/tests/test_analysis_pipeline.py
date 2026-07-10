"""End-to-end test for the upload -> background analysis -> persisted
cast+segments pipeline, against the mock LLM backend (LLM_BACKEND=mock) so
it requires no network/GPU/Grok key.

This is the RED test for Task 3 of Plan 02-01: it must fail before
analysis_client.py/token_estimate.py/analysis_worker.py and the rewritten
POST /projects exist, and pass once Task 3 implements them.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("LLM_BACKEND", "mock")
os.environ.setdefault("TTS_BACKEND", "mock")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402

# TestClient(app) without `with` skips the app's lifespan (where init_db()
# normally runs), so call it explicitly here — SQLModel's create_all is
# idempotent, safe to call again if a real app process already ran it.
init_db()
client = TestClient(app)

SAMPLE_TEXT = (
    "The old lighthouse keeper watched the storm roll in from the north.\n\n"
    '"We should leave now," said Maria, gripping the rail. "The tide will '
    'not wait for us."\n\n'
    "He nodded slowly, and together they climbed down the wet stone steps."
)


def _wait_for_ready(project_id: str, timeout_seconds: float = 5.0) -> dict:
    """Poll GET /projects/{id} until the background analysis task settles."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"/projects/{project_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in ("ready", "error"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"Project {project_id} did not settle within {timeout_seconds}s")


def test_upload_returns_201_analyzing_without_blocking():
    files = {"file": ("sample.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")}

    response = client.post("/projects", files=files)

    assert response.status_code == 201
    body = response.json()
    assert "id" in body
    # The request must return immediately — before the background task has
    # necessarily finished — so status here is whatever it was at return
    # time, not required to already be "ready".
    assert body["status"] in ("analyzing", "ready")


def test_analysis_completes_and_is_retrievable_with_ordered_segments():
    files = {"file": ("sample.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")}
    create_response = client.post("/projects", files=files)
    assert create_response.status_code == 201
    project_id = create_response.json()["id"]

    project = _wait_for_ready(project_id)

    assert project["status"] == "ready"
    assert len(project["characters"]) >= 1
    assert len(project["segments"]) >= 1

    orders = [segment["order"] for segment in project["segments"]]
    assert orders == sorted(orders)

    for segment in project["segments"]:
        assert segment.get("character_name") or segment.get("character_id")
        assert segment["voice_instructions"]


def test_analysis_stream_emits_progress_then_done():
    files = {"file": ("sample.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")}
    create_response = client.post("/projects", files=files)
    assert create_response.status_code == 201
    project_id = create_response.json()["id"]

    with client.stream("GET", f"/projects/{project_id}/analysis-stream") as response:
        assert response.status_code == 200
        events: list[str] = []
        for line in response.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if "done" in events:
                break

    assert "progress" in events
    assert events[-1] == "done"


def test_mock_backend_never_calls_openrouter(monkeypatch):
    from app import analysis_client

    def _fail_if_constructed(*args, **kwargs):
        raise AssertionError("LLM_BACKEND=mock must never construct an OpenRouter HTTP client")

    monkeypatch.setattr(analysis_client.httpx, "AsyncClient", _fail_if_constructed)

    files = {"file": ("sample.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")}
    create_response = client.post("/projects", files=files)
    project_id = create_response.json()["id"]
    _wait_for_ready(project_id)  # would raise via the monkeypatch above if _real_analyze ran


def test_new_characters_default_voice_instructions_from_description():
    files = {"file": ("sample.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")}
    create_response = client.post("/projects", files=files)
    project_id = create_response.json()["id"]

    project = _wait_for_ready(project_id)

    for character in project["characters"]:
        assert character["voice_instructions"]
