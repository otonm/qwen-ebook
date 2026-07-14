"""Qwen3-TTS-1.7B-CustomVoice model wrapper.

Loaded ONCE at module import time (process startup) and held resident —
never reload per request (RESEARCH.md Pattern 1 / Anti-Pattern: reloading
the 1.7B model per call is the documented anti-pattern to avoid).
"""

import io
import logging
import threading
import time

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel
from transformers import StoppingCriteria, StoppingCriteriaList

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

# D-01/D-02 immediate-cancel machinery (ARCHITECTURE.md "Capability 1 —
# Immediate Cancel"). A single process-wide Event is correct — not a
# per-request cancellation registry — because the backend's global
# try_claim_generation/release_generation lock already guarantees at most
# one synthesize_wav call in flight anywhere in the app at a time.
_cancel_event = threading.Event()


class _CancelStoppingCriteria(StoppingCriteria):
    """Checked once per autoregressive decode step by Transformers'
    generate() loop (reached via generate_custom_voice(**kwargs) ->
    model.generate(..., stopping_criteria=...)). Returns True the moment
    request_cancel() has been called, aborting generation promptly instead
    of running the full segment to completion."""

    def __init__(self) -> None:
        self._call_count = 0
        self._first_call_at = time.monotonic()

    def __call__(self, input_ids, scores, **kwargs) -> bool:
        self._call_count += 1
        cancelled = _cancel_event.is_set()
        if cancelled:
            elapsed_ms = (time.monotonic() - self._first_call_at) * 1000
            logger.info(
                f"_CancelStoppingCriteria: cancel observed on decode-step check "
                f"#{self._call_count} ({elapsed_ms:.1f} ms since this criteria "
                "instance was created)"
            )
        return cancelled


class GenerationCancelled(Exception):
    """Raised by synthesize_wav when _cancel_event fired during the
    generate call — turns a stopping-criteria-truncated partial result into
    an explicit cancelled signal instead of silently returning a short WAV
    (T-04-02)."""


def request_cancel() -> None:
    """Signal the in-flight (or next-to-start) synthesize_wav call to abort
    as soon as the decode loop next checks _cancel_event."""
    logger.info("request_cancel() called — setting _cancel_event")
    _cancel_event.set()


# D-02 hardware finding: passing stopping_criteria into
# generate_custom_voice(**kwargs) does NOT reach the actual decode loop.
# Read directly from the installed qwen-tts==0.1.1 wheel
# (core/models/modeling_qwen3_tts.py): generate_custom_voice's **kwargs
# correctly flows into Qwen3TTSForConditionalGeneration.generate(...), but
# THAT method builds its own `talker_kwargs` dict from a hardcoded literal
# list of keys (do_sample/top_k/top_p/.../repetition_penalty/...) that does
# NOT include **kwargs — so stopping_criteria is silently dropped before it
# ever reaches self.talker.generate(inputs_embeds=..., **talker_kwargs),
# which IS the real transformers.GenerationMixin.generate() call that would
# honor it. Confirmed live on the RX 9070 XT: an unpatched stopping_criteria
# never interrupted generation (cancel-to-stop tracked the full uncancelled
# baseline almost exactly, ~474s vs ~682s baseline for the same text).
#
# Fix: patch the ONE call site that matters — self.talker.generate, a
# stable, standard Transformers API — rather than reimplementing
# Qwen3TTSForConditionalGeneration.generate()'s much larger, qwen_tts
# version-fragile body. If a future qwen-tts release starts forwarding
# stopping_criteria itself, kwargs.setdefault below is a no-op on top of it.
#
# The speech_tokenizer.decode() vocoder stage AFTER the talker (converts
# generated codes to a waveform) is a single torch.inference_mode() forward
# pass, not a decode loop — genuinely not interruptible via stopping
# criteria, but bounded by however many codes the (now-interruptible)
# talker stage produced before stopping, so it stays fast.
#
# Both stages are wrapped with elapsed-time logging (not just the talker
# patch) so a cancel-to-stop measurement can be attributed to "the talker
# loop took a while to notice the cancel" vs. "the vocoder decode of
# whatever partial codes existed took a while" — needed to actually
# diagnose D-02 on real hardware rather than guess (CLAUDE.md: log the flow
# extensively).
_original_talker_generate = model.model.talker.generate
_original_speech_tokenizer_decode = model.model.speech_tokenizer.decode


def _talker_generate_with_cancel(*args, **kwargs):
    kwargs.setdefault("stopping_criteria", StoppingCriteriaList([_CancelStoppingCriteria()]))
    start = time.monotonic()
    result = _original_talker_generate(*args, **kwargs)
    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(f"talker.generate() returned after {elapsed_ms:.1f} ms")
    return result


def _speech_tokenizer_decode_with_timing(*args, **kwargs):
    start = time.monotonic()
    result = _original_speech_tokenizer_decode(*args, **kwargs)
    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(f"speech_tokenizer.decode() (vocoder) returned after {elapsed_ms:.1f} ms")
    return result


model.model.talker.generate = _talker_generate_with_cancel
model.model.speech_tokenizer.decode = _speech_tokenizer_decode_with_timing
logger.info("Patched model.model.talker.generate to honor _cancel_event (D-02 fix)")


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

    Raises GenerationCancelled if request_cancel() fired during the
    generate call (D-01/D-02) — the mid-decode StoppingCriteria check.
    """
    # Clear first, before any generate work, so a stale cancel from a prior
    # call (T-04-01) can never abort this one — request_cancel() only
    # matters from this point forward.
    _cancel_event.clear()
    logger.debug("synthesize_wav: _cancel_event cleared")

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
    #
    # No stopping_criteria kwarg here — per the D-02 finding above, it is
    # silently dropped by generate_custom_voice/generate()'s own kwargs
    # handling before it ever reaches a real decode loop. The only place
    # cancellation actually works is the model.model.talker.generate patch
    # above, which injects its own _CancelStoppingCriteria via
    # kwargs.setdefault regardless of what's passed here.
    wavs, sample_rate = model.generate_custom_voice(
        text=text,
        speaker=chosen_speaker,
        instruct=instruct.strip() if instruct and instruct.strip() else None,
    )

    if _cancel_event.is_set():
        logger.info("synthesize_wav: cancel fired mid-generate — raising GenerationCancelled")
        raise GenerationCancelled("synthesis aborted by request_cancel()")

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
