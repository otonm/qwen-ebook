"""Internal TTS client.

Switches on settings.TTS_BACKEND:
  - "mock": returns a short silent WAV built with stdlib `wave`/`struct` —
    no torch, no numpy, no GPU. Lets the whole pipeline be built/tested
    without ROCm hardware.
  - "http": POSTs to the isolated GPU-scoped TTS container's /synthesize
    endpoint per the locked internal contract (01-SKELETON.md). This
    backend package must never `import torch` / `import qwen_tts` directly
    (DEPL-01 GPU/CPU isolation boundary) — all GPU work crosses this HTTP
    boundary instead.
"""

from __future__ import annotations

import io
import struct
import wave

import httpx

from app.config import settings

_MOCK_SAMPLE_RATE = 24000
_MOCK_DURATION_SECONDS = 0.3
_MOCK_SAMPLE_WIDTH_BYTES = 2  # 16-bit PCM


def _mock_wav_bytes() -> bytes:
    """Build a short silent mono 16-bit PCM WAV entirely from the stdlib."""
    n_frames = int(_MOCK_SAMPLE_RATE * _MOCK_DURATION_SECONDS)
    silence = struct.pack("<h", 0) * n_frames

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(_MOCK_SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(_MOCK_SAMPLE_RATE)
        wav_file.writeframes(silence)
    return buf.getvalue()


def synthesize(text: str, speaker: str, instruct: str | None = None) -> bytes:
    """Return WAV bytes for `text` spoken by `speaker`, optionally steered
    by free-text `instruct` (tone/delivery — e.g. "sad and aggressive").
    The CustomVoice model supports a chosen speaker AND instruct steering
    together, not either/or (qwen-tts's generate_custom_voice(text,
    speaker, instruct=...) — see tts_service/model.py)."""
    if settings.TTS_BACKEND == "mock":
        return _mock_wav_bytes()

    if settings.TTS_BACKEND == "http":
        response = httpx.post(
            f"{settings.TTS_SERVICE_URL}/synthesize",
            json={"text": text, "speaker": speaker, "instruct": instruct},
            timeout=httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0),
        )
        response.raise_for_status()
        return response.content

    raise ValueError(f"Unknown TTS_BACKEND: {settings.TTS_BACKEND!r}")


def tts_health() -> bool:
    """Return True when the TTS backend is ready to synthesize."""
    if settings.TTS_BACKEND == "mock":
        return True

    if settings.TTS_BACKEND == "http":
        try:
            response = httpx.get(f"{settings.TTS_SERVICE_URL}/healthz", timeout=5.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    return False
