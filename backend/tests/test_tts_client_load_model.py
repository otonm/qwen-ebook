"""Unit tests for app.tts_client.load_model() (05-02 Task 2).

Unlike cancel(), load_model() must PROPAGATE failures (D-02: the swap
handler needs to see the exception to revert to the still-resident model
and leave the project row untouched) — the opposite discipline from
cancel()'s best-effort swallow, so it gets its own dedicated test file
mirroring test_tts_client_cancel.py's structure.

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
import pytest  # noqa: E402

from app import tts_client  # noqa: E402
from app.config import settings  # noqa: E402


def test_load_model_noops_on_mock_backend(monkeypatch):
    monkeypatch.setattr(tts_client, "settings", replace(settings, TTS_BACKEND="mock"))

    def _unexpected_post(*args, **kwargs):
        raise AssertionError("load_model() must not POST when TTS_BACKEND=mock")

    monkeypatch.setattr(httpx, "post", _unexpected_post)

    assert tts_client.load_model("0.6b") is None


def test_load_model_posts_to_load_endpoint_on_http_backend(monkeypatch):
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

    tts_client.load_model("1.7b")

    assert calls == ["http://fake-tts:8001/model/1.7b/load"]


def test_load_model_propagates_httpx_error_on_http_backend(monkeypatch):
    """Opposite of cancel()'s swallow-and-log discipline: a failed load
    MUST raise so the caller can apply D-02 (revert dropdown, leave the
    project row untouched, release the lock)."""
    monkeypatch.setattr(
        tts_client,
        "settings",
        replace(settings, TTS_BACKEND="http", TTS_SERVICE_URL="http://fake-tts:8001"),
    )

    def _raising_post(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raising_post)

    with pytest.raises(httpx.ConnectError):
        tts_client.load_model("0.6b")


def test_load_model_propagates_bad_status_on_http_backend(monkeypatch):
    monkeypatch.setattr(
        tts_client,
        "settings",
        replace(settings, TTS_BACKEND="http", TTS_SERVICE_URL="http://fake-tts:8001"),
    )

    class _FailingResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "500 error", request=None, response=None
            )

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FailingResponse())

    with pytest.raises(httpx.HTTPStatusError):
        tts_client.load_model("0.6b")


def test_load_model_raises_on_unknown_backend(monkeypatch):
    monkeypatch.setattr(tts_client, "settings", replace(settings, TTS_BACKEND="bogus"))

    with pytest.raises(ValueError, match="Unknown TTS_BACKEND"):
        tts_client.load_model("1.7b")
