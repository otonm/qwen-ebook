"""Unit tests for app.tts_client.cancel() (04-02 Task 2).

cancel() is best-effort: it must never raise into its caller, since the
caller (generation_worker's cancel path, landed in 04-03) still needs to
release the global generation lock even if the cancel POST itself fails.

Runs entirely against TTS_BACKEND=mock by default — no GPU needed. The
"http" branch is exercised by monkeypatching httpx.post directly, so no
real network call happens.
"""

from __future__ import annotations

import os
from dataclasses import replace

os.environ.setdefault("LLM_BACKEND", "mock")
os.environ.setdefault("TTS_BACKEND", "mock")

import httpx  # noqa: E402

from app import tts_client  # noqa: E402
from app.config import settings  # noqa: E402


def test_cancel_noops_on_mock_backend(monkeypatch):
    monkeypatch.setattr(tts_client, "settings", replace(settings, TTS_BACKEND="mock"))

    def _unexpected_post(*args, **kwargs):
        raise AssertionError("cancel() must not POST when TTS_BACKEND=mock")

    monkeypatch.setattr(httpx, "post", _unexpected_post)

    assert tts_client.cancel() is None  # does not raise, does not call httpx.post


def test_cancel_swallows_httpx_error_on_http_backend(monkeypatch):
    monkeypatch.setattr(
        tts_client,
        "settings",
        replace(settings, TTS_BACKEND="http", TTS_SERVICE_URL="http://fake-tts:8001"),
    )

    def _raising_post(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raising_post)

    tts_client.cancel()  # must not raise despite the httpx error above


def test_cancel_posts_to_cancel_endpoint_on_http_backend(monkeypatch):
    monkeypatch.setattr(
        tts_client,
        "settings",
        replace(settings, TTS_BACKEND="http", TTS_SERVICE_URL="http://fake-tts:8001"),
    )

    calls = []

    class _FakeResponse:
        def raise_for_status(self):
            pass

    def _capturing_post(url, **kwargs):
        calls.append(url)
        return _FakeResponse()

    monkeypatch.setattr(httpx, "post", _capturing_post)

    tts_client.cancel()

    assert calls == ["http://fake-tts:8001/cancel"]
