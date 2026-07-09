"""Integration test against the REAL two-container Podman pod (backend +
GPU-scoped tts, started via `bash deploy/run-local.sh`), not the in-process
FastAPI TestClient used by test_e2e.py.

Skipped (not failed) when the pod is not reachable at BACKEND_URL, so the
plain `uv run pytest tests/` suite stays green on machines without the pod
running (e.g. this dev host most of the time, or a GPU-less CI runner).

Positive case (GEN-04): a multi-paragraph upload that forces multiple
chunks produces more total joined audio than a single-chunk upload —
proving multiple chunks were really synthesized and concatenated in order,
not just one chunk returned as-is.

Negative case (T-03-02): stopping the TTS container and then uploading
must return a clean 502/504 gateway error, not a hang or a bare 500 —
this exercises the app/main.py wiring around app/tts_client.py's bounded
httpx timeouts.
"""

from __future__ import annotations

import io
import os
import subprocess
import time
import wave

import httpx
import pytest

# 127.0.0.1, not "localhost": on this host, rootless Podman's pasta port
# forwarding resets IPv6 (::1) loopback connections while IPv4 works fine,
# and "localhost" resolves to ::1 first — using the literal IPv4 address
# sidesteps that resolver ordering entirely.
BACKEND_URL = os.environ.get("INTEGRATION_BACKEND_URL", "http://127.0.0.1:8000")
TTS_CONTAINER_NAME = os.environ.get("INTEGRATION_TTS_CONTAINER", "qwen-ebook-tts")

pytestmark = pytest.mark.integration


def _pod_reachable() -> bool:
    try:
        response = httpx.get(f"{BACKEND_URL}/docs", timeout=2.0)
        return response.status_code < 500
    except httpx.HTTPError:
        return False


requires_pod = pytest.mark.skipif(
    not _pod_reachable(),
    reason=(
        f"Two-container pod not reachable at {BACKEND_URL} — "
        "start it first with `bash deploy/run-local.sh`"
    ),
)


def _wav_duration_seconds(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        return wav_file.getnframes() / float(wav_file.getframerate())


def _upload_text(text: str) -> httpx.Response:
    files = {"file": ("sample.txt", text.encode("utf-8"), "text/plain")}
    return httpx.post(
        f"{BACKEND_URL}/projects",
        files=files,
        timeout=httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0),
    )


def _wait_for_backend(timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _pod_reachable():
            return
        time.sleep(3)


@requires_pod
def test_upload_returns_valid_wav_with_multiple_chunks_joined():
    # Forces multiple chunks at the default CHUNK_TARGET_LEN=800: three
    # ~650-char paragraphs, well over 800 chars combined.
    paragraph = (
        "The narrator begins the story here, describing the scene in vivid "
        "and careful detail so the chunker has plenty of real text to work "
        "with. "
    ) * 6
    multi_chunk_text = "\n\n".join([paragraph.strip()] * 3)

    multi_response = _upload_text(multi_chunk_text)
    assert multi_response.status_code == 200, multi_response.text
    assert multi_response.headers["content-type"].startswith("audio/")
    multi_body = multi_response.content
    assert multi_body[0:4] == b"RIFF"
    assert multi_body[8:12] == b"WAVE"

    single_response = _upload_text("A short single sentence.")
    assert single_response.status_code == 200, single_response.text
    single_body = single_response.content
    assert single_body[0:4] == b"RIFF"
    assert single_body[8:12] == b"WAVE"

    multi_duration = _wav_duration_seconds(multi_body)
    single_duration = _wav_duration_seconds(single_body)
    assert multi_duration > single_duration, (
        "Multi-paragraph upload (multiple chunks) should produce more total "
        f"joined audio than a single-chunk upload (multi={multi_duration}s, "
        f"single={single_duration}s) — GEN-04 join-in-order proof"
    )


@requires_pod
def test_tts_container_down_returns_gateway_error_not_a_hang():
    stopped = False
    try:
        result = subprocess.run(
            ["podman", "stop", "-t", "5", TTS_CONTAINER_NAME],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(
                f"Could not stop TTS container '{TTS_CONTAINER_NAME}' for the "
                f"negative test: {result.stderr.strip()}"
            )
        stopped = True

        response = _upload_text("A short sentence while the TTS container is down.")
        assert response.status_code in (502, 504), (
            f"Expected 502/504 with the TTS container down, got "
            f"{response.status_code}: {response.text}"
        )
    finally:
        if stopped:
            subprocess.run(
                ["podman", "start", TTS_CONTAINER_NAME], capture_output=True, text=True
            )
            # Give the model a moment to finish reloading before any other
            # test (or a human running the checkpoint next) hits it.
            _wait_for_backend(timeout_seconds=180)
