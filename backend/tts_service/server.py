"""Internal FastAPI server for the GPU-scoped Qwen3-TTS inference container.

Implements the internal contract locked in 01-SKELETON.md (extended with
`instruct` — see model.py's synthesize_wav; extended again in Phase 5 with
on-demand model swap, CFG-04):
  POST /synthesize             {"text": str, "speaker": str | null, "instruct": str | null}
                                -> 200 audio/wav
  POST /model/{model_id}/load  -> 200 once the requested checkpoint is resident
  GET  /healthz                -> 200 only once a model is loaded and resident

Also runs a periodic GPU keepalive matmul (ROCm-specific gotcha — AMD's
power management downclocks an idle GPU, spiking latency on the first
request after a gap; independently corroborated by the community
groxaxo/Qwen3-TTS-Openai-Fastapi FastAPI wrapper around this same
qwen-tts package, not part of the official qwen-tts API surface).
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("tts_service.server")
logging.basicConfig(level=logging.INFO)

GPU_KEEPALIVE_INTERVAL = float(os.environ.get("GPU_KEEPALIVE_INTERVAL", "15"))

# D-01 (Claude's Discretion / RESEARCH.md): default checkpoint loaded at
# process startup — preserves today's baseline behavior. Swapping to the
# other checkpoint afterward is what POST /model/{model_id}/load is for.
DEFAULT_MODEL_ID = "1.7b"

# Readiness flag — tts_service.model is imported lazily below so the actual
# model load (now inside ensure_loaded, not at import time — Phase 5) happens
# at server startup via lifespan, not merely at module-import time of this
# file during test collection.
_model_module = None
_ready = False


async def _keepalive_loop() -> None:
    if GPU_KEEPALIVE_INTERVAL <= 0:
        logger.info("GPU keepalive disabled (GPU_KEEPALIVE_INTERVAL <= 0)")
        return
    logger.info("GPU keepalive loop started (interval=%ss)", GPU_KEEPALIVE_INTERVAL)
    try:
        while True:
            await asyncio.sleep(GPU_KEEPALIVE_INTERVAL)
            if _model_module is not None:
                try:
                    _model_module.keepalive_matmul()
                except Exception:
                    # Broad catch is deliberate: this is a periodic background
                    # keepalive loop with no caller to propagate to — a failed
                    # matmul must never crash the server.
                    logger.exception("GPU keepalive matmul failed")
    except asyncio.CancelledError:
        logger.info("GPU keepalive loop cancelled")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model_module, _ready
    # Phase 5: tts_service.model no longer loads a checkpoint at import time
    # (see model.py) — this ensure_loaded call is the ONE place the default
    # model is loaded, at process startup. run_in_threadpool because it's a
    # synchronous, multi-second GPU load — same discipline as /synthesize.
    from tts_service import model as model_module

    _model_module = model_module
    logger.info(f"Loading default model {DEFAULT_MODEL_ID!r}...")
    await run_in_threadpool(model_module.ensure_loaded, DEFAULT_MODEL_ID)
    _ready = True
    logger.info(f"Model loaded; default speaker = {model_module.DEFAULT_SPEAKER}")

    keepalive_task = asyncio.create_task(_keepalive_loop())
    try:
        yield
    finally:
        keepalive_task.cancel()
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)


class SynthesizeRequest(BaseModel):
    text: str
    speaker: str | None = None
    instruct: str | None = None


@app.get("/healthz")
async def healthz() -> Response:
    if not _ready:
        return Response(status_code=503, content="model not loaded")
    return Response(status_code=200, content="ok")


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest) -> Response:
    if not _ready or _model_module is None:
        return Response(status_code=503, content="model not loaded")

    if not req.text or not req.text.strip():
        return Response(status_code=422, content="text must not be empty")

    # Imported here (not at module top level) to preserve the same lazy-load
    # discipline as _model_module itself — tts_service.model is already
    # loaded by this point (lifespan set _model_module above), so this just
    # binds the name from the cached module, no second model load.
    from tts_service.model import GenerationCancelled

    try:
        # CR-02: synthesize_wav() is a synchronous, GPU-bound call that can
        # take a long time per chunk. Running it directly on the event loop
        # would block /healthz and every other request for the duration —
        # offload it to the threadpool instead.
        wav_bytes = await run_in_threadpool(
            _model_module.synthesize_wav, req.text, req.speaker, req.instruct
        )
    except ValueError as exc:
        # Unsupported speaker / empty text / oversized text -> 400, not 500
        # (T-02-01: qwen-tts's own get_supported_speakers()-backed
        # validation raises ValueError; we surface it as a client error).
        return Response(status_code=400, content=str(exc))
    except GenerationCancelled:
        # T-04-06: a deliberate POST /cancel-triggered stop must be
        # distinguishable from a crash. 499 (Client Closed Request, the
        # nginx/many-gateways convention for "request aborted by caller")
        # is not in FastAPI's own vocabulary but is a well-understood
        # non-500 signal; the backend maps it to a clean "cancelled" state
        # rather than treating it as a synthesis failure.
        logger.info("synthesis cancelled via /cancel — returning 499")
        return Response(status_code=499, content="synthesis cancelled")
    except Exception:
        # Broad catch is deliberate: any other model/runtime failure should
        # surface as a clean 500 with a logged traceback, not an unhandled
        # stack-trace leak to the client.
        logger.exception("synthesis failed")
        return Response(status_code=500, content="synthesis failed")

    return Response(content=wav_bytes, media_type="audio/wav")


@app.post("/model/{model_id}/load")
async def load_model_route(model_id: str) -> Response:
    """Swaps the resident checkpoint to `model_id` (CFG-04). Allowlist-
    validated against MODEL_CHOICES here too (V5 defense-in-depth — the
    main backend also validates before calling this route, T-05-01) so an
    arbitrary model_id can never reach from_pretrained. _ready flips False
    for the swap's duration (racing /synthesize gets a clean 503, T-05-02)
    and is set True in BOTH the success and failure branches — on failure
    the OLD model is still resident (ensure_loaded only deletes it after
    the new load succeeds, D-02), so the service is still usable."""
    global _ready
    if _model_module is None:
        return Response(status_code=503, content="model not loaded")
    if model_id not in _model_module.MODEL_CHOICES:
        return Response(status_code=422, content=f"unknown model_id {model_id!r}")

    _ready = False
    try:
        await run_in_threadpool(_model_module.ensure_loaded, model_id)
    except Exception:
        # Broad catch is deliberate: any from_pretrained/CUDA failure should
        # surface as a clean 500 with a logged traceback, matching the
        # /synthesize convention above.
        logger.exception("model swap failed")
        _ready = True  # old model is still resident (del happens AFTER new load succeeds)
        return Response(status_code=500, content="model swap failed")
    _ready = True
    return Response(status_code=200, content="ok")


@app.post("/cancel")
async def cancel() -> Response:
    """Best-effort, fire-and-forget: sets the cancel flag that the
    in-flight /synthesize call's StoppingCriteria checks on its next
    decode step (see tts_service/model.py). Does not wait for that call
    to actually finish unwinding — the caller's own /synthesize request
    unblocks itself once the decode loop observes the flag."""
    if _model_module is None:
        return Response(status_code=503, content="model not loaded")
    _model_module.request_cancel()
    return Response(status_code=202)
