"""Internal TTS client.

POSTs to the isolated GPU-scoped TTS container's /synthesize endpoint per
the locked internal contract (01-SKELETON.md). This backend package must
never `import torch` / `import qwen_tts` directly (DEPL-01 GPU/CPU
isolation boundary) — all GPU work crosses this HTTP boundary instead.
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger("app.tts_client")


def synthesize(text: str, speaker: str, instruct: str | None = None) -> bytes:
    """Return WAV bytes for `text` spoken by `speaker`, optionally steered
    by free-text `instruct` (tone/delivery — e.g. "sad and aggressive").
    The CustomVoice model supports a chosen speaker AND instruct steering
    together, not either/or (qwen-tts's generate_custom_voice(text,
    speaker, instruct=...) — see tts_service/model.py)."""
    response = httpx.post(
        f"{settings.TTS_SERVICE_URL}/synthesize",
        json={"text": text, "speaker": speaker, "instruct": instruct},
        timeout=httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0),
    )
    response.raise_for_status()
    return response.content


def cancel() -> None:
    """Best-effort request to interrupt the in-flight synth call.

    Fire-and-forget: a 5xx/timeout on the cancel POST itself must never
    raise into the caller, because the caller still needs to release the
    generation lock even if this call fails (T-04-05)."""
    try:
        httpx.post(
            f"{settings.TTS_SERVICE_URL}/cancel",
            timeout=httpx.Timeout(connect=2.0, read=2.0, write=2.0, pool=2.0),
        ).raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"cancel() POST to tts_service failed (best-effort): {exc}")


def load_model(model_id: str) -> None:
    """Request tts_service swap its resident model to `model_id` (Phase 5,
    CFG-04, D-01's explicit-load trigger).

    Unlike cancel(), this is NOT best-effort: a swap failure (OOM, download
    error, checkpoint missing) must propagate so main.py's handler can
    apply D-02 (revert the dropdown to whichever model is still actually
    resident, leave the project row untouched). Uses the same long-read
    timeout as synthesize() since a real swap takes tens of seconds."""
    logger.info(f"requesting tts_service load model_id={model_id!r}")
    response = httpx.post(
        f"{settings.TTS_SERVICE_URL}/model/{model_id}/load",
        timeout=httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0),
    )
    response.raise_for_status()


def tts_health() -> bool:
    """Return True when the TTS backend is ready to synthesize."""
    try:
        response = httpx.get(f"{settings.TTS_SERVICE_URL}/healthz", timeout=5.0)
        return response.status_code == 200
    except httpx.HTTPError:
        return False
