"""Qwen3-TTS CustomVoice model wrapper — swappable on demand between two
checkpoints (CFG-04, D-01).

Loading happens ONLY inside `ensure_loaded(model_id)` — importing this
module no longer loads any model. `server.py`'s lifespan calls
`ensure_loaded("1.7b")` once at process startup (preserving today's default
behavior); `POST /model/{model_id}/load` calls it again on demand. Only one
checkpoint is ever resident in VRAM at a time — `ensure_loaded` deletes the
old one before loading the new one (RESEARCH.md Pattern 1 / STACK.md's
7-step swap sequence).
"""

import gc
import io
import logging
import threading
import time

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel
from transformers import StoppingCriteria, StoppingCriteriaList

logger = logging.getLogger("tts_service.model")

# D-01: the two hardcoded checkpoints this app supports. No generic model
# registry — RESEARCH.md Anti-Pattern: only 2 ids, this dict is the whole
# abstraction needed.
MODEL_CHOICES: dict[str, str] = {
    "1.7b": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "0.6b": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
}

MAX_TEXT_LENGTH = 4000  # defensive cap; backend pre-chunks to ~800 chars (T-02-02)

# Module globals populated only by ensure_loaded() below — no model is
# resident until the first ensure_loaded() call (server.py's lifespan makes
# that call at startup with the default "1.7b").
model = None
DEFAULT_SPEAKER: str | None = None
_loaded_model_id: str | None = None
_swap_lock = threading.Lock()

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


def _pick_default_speaker(supported: list[str]) -> str:
    """D-04 (Claude's discretion): pick a sensible narrator-style preset.
    Falls back to the first entry if no obviously-better narrator-labelled
    preset exists — qwen-tts's own speaker list is the source of truth
    here, not a hand-rolled allowlist (RESEARCH.md Don't Hand-Roll)."""
    narrator_candidates = [s for s in supported if "narrat" in s.lower()]
    return narrator_candidates[0] if narrator_candidates else supported[0]


def _apply_stopping_criteria_patch(model_instance: Qwen3TTSModel) -> None:
    """Re-applies Phase 4's talker/speech_tokenizer monkeypatch to a freshly
    loaded model instance. The patch does NOT survive a fresh
    from_pretrained (each swap gets a brand new talker/speech_tokenizer
    object) — ensure_loaded calls this after every load, not just once.

    D-02 hardware finding: passing stopping_criteria into
    generate_custom_voice(**kwargs) does NOT reach the actual decode loop.
    Read directly from the installed qwen-tts==0.1.1 wheel
    (core/models/modeling_qwen3_tts.py): generate_custom_voice's **kwargs
    correctly flows into Qwen3TTSForConditionalGeneration.generate(...), but
    THAT method builds its own `talker_kwargs` dict from a hardcoded literal
    list of keys (do_sample/top_k/top_p/.../repetition_penalty/...) that does
    NOT include **kwargs — so stopping_criteria is silently dropped before it
    ever reaches self.talker.generate(inputs_embeds=..., **talker_kwargs),
    which IS the real transformers.GenerationMixin.generate() call that would
    honor it. Confirmed live on the RX 9070 XT: an unpatched stopping_criteria
    never interrupted generation (cancel-to-stop tracked the full uncancelled
    baseline almost exactly, ~474s vs ~682s baseline for the same text).

    Fix: patch the ONE call site that matters — self.talker.generate, a
    stable, standard Transformers API — rather than reimplementing
    Qwen3TTSForConditionalGeneration.generate()'s much larger, qwen_tts
    version-fragile body. If a future qwen-tts release starts forwarding
    stopping_criteria itself, kwargs.setdefault below is a no-op on top of it.

    The speech_tokenizer.decode() vocoder stage AFTER the talker (converts
    generated codes to a waveform) is a single torch.inference_mode() forward
    pass, not a decode loop — genuinely not interruptible via stopping
    criteria, but bounded by however many codes the (now-interruptible)
    talker stage produced before stopping, so it stays fast.

    Both stages are wrapped with elapsed-time logging (not just the talker
    patch) so a cancel-to-stop measurement can be attributed to "the talker
    loop took a while to notice the cancel" vs. "the vocoder decode of
    whatever partial codes existed took a while" — needed to actually
    diagnose D-02 on real hardware rather than guess (CLAUDE.md: log the flow
    extensively).
    """
    original_talker_generate = model_instance.model.talker.generate
    original_speech_tokenizer_decode = model_instance.model.speech_tokenizer.decode

    def _talker_generate_with_cancel(*args, **kwargs):
        kwargs.setdefault("stopping_criteria", StoppingCriteriaList([_CancelStoppingCriteria()]))
        start = time.monotonic()
        result = original_talker_generate(*args, **kwargs)
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(f"talker.generate() returned after {elapsed_ms:.1f} ms")
        return result

    def _speech_tokenizer_decode_with_timing(*args, **kwargs):
        start = time.monotonic()
        result = original_speech_tokenizer_decode(*args, **kwargs)
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(f"speech_tokenizer.decode() (vocoder) returned after {elapsed_ms:.1f} ms")
        return result

    model_instance.model.talker.generate = _talker_generate_with_cancel
    model_instance.model.speech_tokenizer.decode = _speech_tokenizer_decode_with_timing
    logger.info("Patched model.model.talker.generate to honor _cancel_event (D-02 fix)")


def ensure_loaded(model_id: str) -> None:
    """No-op if `model_id` is already the resident model; otherwise swaps
    to it: delete the old model (if any), reclaim VRAM, load the requested
    checkpoint, re-apply the cancel monkeypatch, and re-derive
    DEFAULT_SPEAKER from the new checkpoint's own speaker roster.

    Raises ValueError on an unknown model_id (never reaches from_pretrained
    with an unvalidated id — T-05-01).
    """
    global model, DEFAULT_SPEAKER, _loaded_model_id

    if model_id not in MODEL_CHOICES:
        raise ValueError(f"unknown model_id {model_id!r}")
    if _loaded_model_id == model_id:
        return  # already resident — no-op, matches D-01's "swap only on real change"

    with _swap_lock:
        if _loaded_model_id == model_id:  # re-check under lock
            return

        if model is not None:
            free_before, total = torch.cuda.mem_get_info()
            logger.info(
                f"ensure_loaded: unloading {_loaded_model_id!r} (free VRAM before "
                f"unload: {free_before / 1024**2:.1f} MB / {total / 1024**2:.1f} MB)"
            )
            del model
            gc.collect()
            torch.cuda.empty_cache()  # ROCm build aliases cuda->hip
            free_after, _ = torch.cuda.mem_get_info()
            logger.info(f"ensure_loaded: free VRAM after unload: {free_after / 1024**2:.1f} MB")

        logger.info(f"ensure_loaded: loading {model_id!r} ({MODEL_CHOICES[model_id]})...")
        # ROCm-safe attention. NOT the qwen-tts README's own default of
        # "flash_attention_2" (CUDA-only, unsafe/unavailable on ROCm) — sdpa
        # is mandatory per CLAUDE.md / RESEARCH.md Pattern 1.
        new_model = Qwen3TTSModel.from_pretrained(
            MODEL_CHOICES[model_id],
            device_map="cuda:0",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )
        _apply_stopping_criteria_patch(new_model)

        supported = new_model.get_supported_speakers()
        logger.info(f"ensure_loaded: supported speakers for {model_id!r}: {supported}")

        model = new_model
        DEFAULT_SPEAKER = _pick_default_speaker(supported)
        _loaded_model_id = model_id
        logger.info(
            f"ensure_loaded: swap complete — {model_id!r} resident, "
            f"default speaker = {DEFAULT_SPEAKER}"
        )


def get_supported_speakers() -> list[str]:
    return model.get_supported_speakers()


def synthesize_wav(text: str, speaker: str | None = None, instruct: str | None = None) -> bytes:
    """Synthesize `text` with the given (or default) speaker, optionally
    steered by free-text `instruct` (tone/delivery), return WAV bytes.

    Raises ValueError on empty text or text exceeding MAX_TEXT_LENGTH.

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

    # D-07: a swap can leave a caller naming a speaker the NEW resident
    # model doesn't support (e.g. a smaller checkpoint with a reduced
    # roster). Defensive fallback rather than a hard error — RESEARCH.md
    # Pitfall 3 confirms the 1.7B/0.6B rosters are identical today, so this
    # never actually fires in practice, but it's cheap correctness insurance
    # against a future checkpoint with a smaller speaker set.
    supported_speakers = model.get_supported_speakers()
    if chosen_speaker not in supported_speakers:
        logger.info(
            f"synthesize_wav: speaker {chosen_speaker!r} not in resident model's "
            f"supported speakers {supported_speakers} — falling back to "
            f"DEFAULT_SPEAKER {DEFAULT_SPEAKER!r} (D-07)"
        )
        chosen_speaker = DEFAULT_SPEAKER

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
    # applied by _apply_stopping_criteria_patch, which injects its own
    # _CancelStoppingCriteria via kwargs.setdefault regardless of what's
    # passed here.
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
