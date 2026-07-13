"""Internal FastAPI server for the GPU-scoped Qwen3-TTS inference container.

Implements the internal contract locked in 01-SKELETON.md (extended with
`instruct` — see model.py's synthesize_wav):
  POST /synthesize  {"text": str, "speaker": str | null, "instruct": str | null} -> 200 audio/wav
  GET  /healthz      -> 200 only once the model is loaded and resident

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

# Readiness flag — imported lazily below so `import tts_service.model` (which
# triggers the actual ~1.7B-parameter model load) happens at server startup,
# not merely at module-import time of this file during test collection.
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
    # Import triggers model.py's module-level Qwen3TTSModel.from_pretrained()
    # call — the ONE place the 1.7B model is loaded, at process startup.
    from tts_service import model as model_module

    _model_module = model_module
    _ready = True
    logger.info("Model loaded; default speaker = %s", model_module.DEFAULT_SPEAKER)

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
    except Exception:
        # Broad catch is deliberate: any other model/runtime failure should
        # surface as a clean 500 with a logged traceback, not an unhandled
        # stack-trace leak to the client.
        logger.exception("synthesis failed")
        return Response(status_code=500, content="synthesis failed")

    return Response(content=wav_bytes, media_type="audio/wav")
