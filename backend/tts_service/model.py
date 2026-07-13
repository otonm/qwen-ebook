"""Qwen3-TTS-1.7B-CustomVoice model wrapper.

Loaded ONCE at module import time (process startup) and held resident —
never reload per request (RESEARCH.md Pattern 1 / Anti-Pattern: reloading
the 1.7B model per call is the documented anti-pattern to avoid).
"""

import io
import logging

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

logger = logging.getLogger("tts_service.model")

MODEL_NAME = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"

# D-04: single default CustomVoice speaker preset, used as the fallback
# whenever a request doesn't specify one. Chosen once at startup below
# after the model loads and its supported speaker list is known.
# Independent of instruct: every request can still supply its own
# free-text instruct steering regardless of which speaker is in play.
DEFAULT_SPEAKER: str | None = None

logger.info("Loading %s (this can take 1-2 minutes on first run)...", MODEL_NAME)

# ROCm-safe attention. NOT the qwen-tts README's own default of
# "flash_attention_2" (CUDA-only, unsafe/unavailable on ROCm) — sdpa is
# mandatory per CLAUDE.md / RESEARCH.md Pattern 1.
model = Qwen3TTSModel.from_pretrained(
    MODEL_NAME,
    device_map="cuda:0",
    dtype=torch.bfloat16,
    attn_implementation="sdpa",
)

_supported_speakers = model.get_supported_speakers()
logger.info("Supported speakers: %s", _supported_speakers)

# D-04 (Claude's discretion): pick a sensible narrator-style preset. Fall
# back to the first entry if no obviously-better narrator-labelled preset
# exists — qwen-tts's own speaker list is the source of truth here, not a
# hand-rolled allowlist (RESEARCH.md Don't Hand-Roll).
_narrator_candidates = [
    s for s in _supported_speakers if "narrat" in s.lower()
]
DEFAULT_SPEAKER = _narrator_candidates[0] if _narrator_candidates else _supported_speakers[0]
logger.info("Default speaker chosen: %s", DEFAULT_SPEAKER)

MAX_TEXT_LENGTH = 4000  # defensive cap; backend pre-chunks to ~800 chars (T-02-02)


def get_supported_speakers() -> list[str]:
    return _supported_speakers


def synthesize_wav(text: str, speaker: str | None = None, instruct: str | None = None) -> bytes:
    """Synthesize `text` with the given (or default) speaker, optionally
    steered by free-text `instruct` (tone/delivery), return WAV bytes.

    Raises ValueError on empty text, text exceeding MAX_TEXT_LENGTH, or an
    unsupported speaker. Speaker validation is NOT hand-rolled here — it is
    surfaced directly from qwen-tts's own `_validate_speakers` (called
    internally by `generate_custom_voice`), which raises `ValueError` on an
    unsupported speaker (RESEARCH.md Don't Hand-Roll).
    """
    if not text or not text.strip():
        raise ValueError("text must not be empty")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"text exceeds max length of {MAX_TEXT_LENGTH} characters")

    chosen_speaker = speaker or DEFAULT_SPEAKER

    # generate_custom_voice(text, speaker, instruct=None, ...) ->
    # (List[np.ndarray], sample_rate: int) — verified directly from the
    # qwen-tts==0.1.1 wheel (qwen3_tts_model.py): CustomVoice takes a
    # predefined speaker id "optionally controlled by instruction text",
    # so a blank/whitespace-only instruct is passed through as None rather
    # than an empty string (treated identically by the model, but None is
    # the more honest "no instruction" signal).
    wavs, sample_rate = model.generate_custom_voice(
        text=text,
        speaker=chosen_speaker,
        instruct=instruct.strip() if instruct and instruct.strip() else None,
    )
    audio_array = wavs[0]

    buf = io.BytesIO()
    sf.write(buf, audio_array, sample_rate, format="WAV")
    return buf.getvalue()


def keepalive_matmul() -> None:
    """Tiny on-device matmul used by server.py's periodic GPU keepalive.

    AMD's power management (DPM) downclocks an idle GPU; a periodic matmul
    keeps the device in a higher power state so the first real request
    after an idle gap doesn't pay a latency spike. This is a known
    ROCm-specific gotcha, not part of the official qwen-tts API surface
    (independently corroborated by the community
    groxaxo/Qwen3-TTS-Openai-Fastapi FastAPI wrapper around this same
    qwen-tts package).
    """
    a = torch.randn(64, 64, device="cuda")
    b = torch.randn(64, 64, device="cuda")
    (a @ b).sum()
