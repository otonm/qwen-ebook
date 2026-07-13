# Architecture Research

**Domain:** Integration research for v1.1 milestone — generation-control (immediate-cancel) and config-panel additions (model swap, codec, download) to an existing self-hosted TTS pipeline
**Researched:** 2026-07-13
**Confidence:** HIGH (call boundary, cancel semantics, and the library hook capability 1 depends on are all verified directly against this repo's own code and the installed `qwen_tts` wheel — not assumed)

This is not a greenfield domain survey. It supersedes the v1.0 ARCHITECTURE.md (2026-07-09) for this milestone's purposes: it documents the REAL current architecture (verified by reading the code) and the specific integration points the 4 new capabilities need.

## The Real Current Call Boundary (verified, not assumed)

The milestone brief asked "in-process import? subprocess? separate container over HTTP?" — it's the last one, confirmed three ways:

1. **Two separate Podman Quadlet units in one pod** (`deploy/qwen-ebook-tts.container`, `deploy/qwen-ebook-backend.container`): the TTS container gets `AddDevice=/dev/kfd`/`/dev/dri` and `User=0`; the backend container gets neither and is explicitly commented `# No AddDevice here — the backend never imports torch/qwen-tts and stays CPU-only`. Real process/container isolation, not a Python-level boundary.
2. **`backend/app/tts_client.py`**: the `TTS_BACKEND=http` path does a synchronous `httpx.post(f"{TTS_SERVICE_URL}/synthesize", ...)` with a 300s read timeout, called from request handlers via `starlette.concurrency.run_in_threadpool`. The module docstring states the constraint explicitly: "This backend package must never `import torch` / `import qwen_tts` directly ... all GPU work crosses this HTTP boundary instead."
3. **`backend/tts_service/server.py`**: a second, independent FastAPI app (`POST /synthesize`, `GET /healthz`) that owns the model. `backend/tts_service/model.py` loads `Qwen3TTSModel.from_pretrained(...)` ONCE at module-import time (triggered by the outer app's `lifespan`) and holds it resident — "never reload per request" per its own docstring.

So: **HTTP microservice boundary, both processes long-lived, single shared GPU, single resident model.** Not subprocess-per-call, not in-process import, not a task queue (Celery/Redis explicitly out per CLAUDE.md).

### Why this matters for "immediate kill"

`run_in_threadpool` (→ `anyio.to_thread.run_sync`) does **not** deliver `asyncio.CancelledError` to the awaiting coroutine until the underlying blocking call returns — a native OS thread can't be forcibly killed. This is already documented in the codebase's own `cancel_generation` docstring in `main.py`:

> "cancelling the segment currently mid-synth only takes effect once that HTTP call returns; this stops progression to the NEXT segment, it does not abort the in-flight one."

And the frontend already shows this to the user verbatim (`ConfigPanel.tsx`): *"Stops before the next segment — the segment currently generating may still finish."* This is precisely the behavior capability 1 must replace.

**Per-segment generate has no cancel concept at all today** — `POST /segments/{id}/generate` (`main.py`) `await`s `regenerate_segment` synchronously inside the request/response cycle. There is no task handle for any other request to reach in and cancel; only the batch path (`_running_generations: dict[project_id, Task]` in `generation_worker.py`) has a cancellable task registry.

## Component Responsibilities (current)

| Component | Responsibility | Notes |
|-----------|-----------------|-------|
| `backend/app/main.py` | HTTP surface: project/character/segment CRUD, generate/cancel endpoints, SSE streams, static file serving | Owns `regenerate_segment` (single source of truth for cache-key + synth, called by both per-row and batch paths) |
| `backend/app/generation_worker.py` | Batch state machine, SSE progress queue registry, **global single-flight lock** (`_active_generation_label` module global) | Lock is app-wide, not per-project — "the constraint is the one shared GPU, not any one project" |
| `backend/app/tts_client.py` | Sync HTTP client to `tts_service`, `mock`/`http` backend switch | Only place `TTS_SERVICE_URL` is used; only place that would gain a `model_id`/cancel param |
| `backend/tts_service/server.py` | FastAPI process #2: `/synthesize`, `/healthz`, GPU keepalive loop | Owns nothing about generation locking itself — comment confirms "`/synthesize` has no concurrency control of its own" (relies entirely on the backend's single-flight lock never sending it 2 concurrent requests) |
| `backend/tts_service/model.py` | Model load (module-level singleton today), `synthesize_wav` | Loaded once at process start; `MODEL_NAME` is a hardcoded constant today |
| `backend/app/cache_key.py` | Content-hash cache key: `(resolved_speaker, voice_instructions, text, TTS_MODEL_VERSION)` | `TTS_MODEL_VERSION` is currently a **hardcoded string constant** ("only one model is in scope for v1") — this is the exact seam capability 2 needs to turn live |
| `backend/app/audio_join.py` | ffmpeg concat-demuxer join, `-c copy` for wav / `-c:a libmp3lame` for anything else | Binary `if fmt == "wav"` branch — the exact seam capability 3 extends |
| `backend/app/config.py` | Frozen `Settings` dataclass from env vars, `_ALLOWED_OUTPUT_FORMATS = {"wav", "mp3"}` fail-fast at load time | Milestone drops wav, adds flac/opus — this set and its validation both need to change |

## Capability 1 — Immediate Cancel

### The real mechanism, verified against the installed library (not speculative)

`backend/tts_service/model.py` calls `qwen_tts`'s `model.generate_custom_voice(text=..., speaker=..., instruct=...)`. Reading the installed wheel directly (`qwen_tts/inference/qwen3_tts_model.py`):

- `generate_custom_voice(..., **kwargs)` forwards unrecognized kwargs through `self._merge_generate_kwargs(**kwargs)`, whose own `**kwargs` catch-all (`merged = dict(kwargs)`) passes straight into `self.model.generate(input_ids=..., ..., **gen_kwargs)`.
- `self.model` is a `Qwen3TTSForConditionalGeneration`, a HuggingFace Transformers-family model — its `.generate()` supports the standard Transformers `stopping_criteria: StoppingCriteriaList` argument, checked once per decoding step (autoregressive, dozens-to-hundreds of steps/sec).

**This means a custom `StoppingCriteria` is very likely already reachable through the existing public call, with no need to monkeypatch qwen_tts internals** — confirm with a short spike before committing to it as the mechanism, since this reads the library's kwarg-forwarding code path but was not exercised end-to-end against real GPU inference. Treat "the hook exists in the call chain" as HIGH confidence (verified from the wheel), and "it actually aborts a live ROCm decode loop promptly" as MEDIUM until proven live.

### Recommended design (no task queue, reuses existing single-flight discipline)

Because the backend's global `try_claim_generation`/`release_generation` lock already guarantees **at most one synth call in flight anywhere in the app**, `tts_service` never needs a per-request-id cancellation registry — a single process-wide `threading.Event` is sufficient (mirrors the existing `_active_generation_label` module-global pattern, just moved one process over):

```python
# tts_service/model.py
_cancel_event = threading.Event()

class _CancelStoppingCriteria(StoppingCriteria):
    def __call__(self, input_ids, scores, **kwargs) -> bool:
        return _cancel_event.is_set()

def synthesize_wav(text, speaker=None, instruct=None):
    _cancel_event.clear()
    ...
    wavs, sr = model.generate_custom_voice(
        ..., stopping_criteria=StoppingCriteriaList([_CancelStoppingCriteria()])
    )
    if _cancel_event.is_set():
        raise GenerationCancelled()   # new exception type

def request_cancel() -> None:
    _cancel_event.set()
```

```python
# tts_service/server.py
@app.post("/cancel")
async def cancel() -> Response:
    model_module.request_cancel()
    return Response(status_code=202)
```

The key insight that avoids a client-side rewrite: **the fix is almost entirely server-side.** Today's `httpx.post(...)` + `run_in_threadpool` on the backend is fine as-is — it currently blocks for up to 300s only because `tts_service` itself doesn't return until the full segment finishes. Once `tts_service`'s own generate loop is made interruptible, the SAME blocking `httpx.post` naturally unblocks within one decoding step's latency (milliseconds) instead of the full segment. No async `httpx.AsyncClient` migration is needed on the backend side to get "immediate" — building that would solve a problem the server-side fix already removes. `(ponytail: this is the lazy read — verify it holds once the stopping-criteria plumbing is live; if httpx.post still hangs, the anyio-thread-cancellation gap is the fallback thing to fix, not before.)`

### Backend-side plumbing needed

- **Per-segment generate must become a background task** (it isn't one today — it's `await`ed synchronously in the request handler with no task handle). Refactor `POST /segments/{id}/generate` to match the exact pattern `_generate_preview`/character-preview already uses: `try_claim_generation` → spawn via `_spawn_claimed_generation` → return 202 → client polls/streams status. Add a new `dict[segment_id, Task]` registry in `generation_worker.py` (same shape as `_running_generations`, keyed by segment instead of project) so a `POST /segments/{id}/generate/cancel` has something to `.cancel()`.
- **`tts_client.py` gains a `cancel()` function** that POSTs to `{TTS_SERVICE_URL}/cancel` — called by both the batch cancel endpoint and the new per-segment cancel endpoint. Fire-and-forget is fine (best-effort; a 5xx/timeout on the cancel call itself should still let the caller proceed to release the lock).
- **`cancel_generation` (batch) and the new per-segment cancel** both: (1) POST to `tts_service`'s `/cancel`, (2) `task.cancel()` the local asyncio task, (3) reset the affected segment(s) to `"pending"`. Order matters less than "both happen" — the `/cancel` call is what actually shortens the in-flight synth; the asyncio `.cancel()` is what stops progression to the next segment (existing behavior, keep it).

### What NOT to build for this

- **No subprocess-per-request kill.** Forking/spawning a fresh process per synth call to get SIGKILL-ability would mean either re-loading the model per call (the documented anti-pattern already called out in `model.py`) or forking after a CUDA/ROCm context is already initialized in the parent, which is a well-known broken pattern for GPU frameworks (`"Cannot re-initialize CUDA in forked subprocess"`-class failures). Skip it.
- **No task queue / Celery / Redis.** CLAUDE.md already rules this out and nothing here needs it — the single `threading.Event` plus the existing global lock is the entire mechanism.
- **No per-request cancellation token/id.** The app-wide single-flight lock already means "at most one thing is generating," so a single global cancel flag in `tts_service` is correct, not a simplification that will bite later.

## Capability 2 — On-Demand Model Swap (1.7B / 0.6B)

### Where model choice should live: per-project DB column, not a request param or pure global

Two facts pull in the same direction here:

1. **Physical constraint:** one GPU, one resident model at a time ("only one resident in VRAM at a time" per the milestone). This is inherently a `tts_service`-process-global runtime fact, not something that can vary per-request without a reload.
2. **Correctness constraint, already designed for:** `cache_key.py`'s `TTS_MODEL_VERSION` is documented as part of the cache tuple `(character, voice instructions, text, voice/model version)` — currently a hardcoded constant because "only one model is in scope for v1." A project generated on the 1.7B model and later switched to 0.6B must NOT silently serve stale 1.7B-cached audio as if it matches — the cache key needs the ACTUAL model used to vary per project.

Resolve both by splitting the concern:

- **`Project.tts_model: str`** (new SQLModel column, default = today's hardcoded model id) — source of truth for "what this project wants," edited via the Config Panel, and fed into `compute_cache_key(resolved_speaker, voice_instructions, text, model_id)` (drop the hardcoded `TTS_MODEL_VERSION` constant, thread the real value through instead — a straightforward signature change, not a redesign).
- **A single global "currently resident model" fact inside `tts_service`** — physical reality, reconciled opportunistically against whatever `Project.tts_model` says right before synthesis, not duplicated as separate state on the backend side.

This gives correct caching (per-project intent recorded) without pretending two models can be resident simultaneously (they can't, and nothing here tries to fake it).

### Integration points

- **`tts_service/model.py`**: replace the module-level `model = Qwen3TTSModel.from_pretrained(MODEL_NAME, ...)` singleton with a tiny load/unload function:
  ```python
  _loaded_model_id: str | None = None
  _model = None

  def ensure_loaded(model_id: str) -> None:
      global _loaded_model_id, _model
      if _loaded_model_id == model_id:
          return
      if _model is not None:
          del _model
          gc.collect()
          torch.cuda.empty_cache()   # ROCm build aliases cuda->hip; same call as today
      _model = Qwen3TTSModel.from_pretrained(model_id, device_map="cuda:0",
                                              dtype=torch.bfloat16, attn_implementation="sdpa")
      _loaded_model_id = model_id
  ```
  `torch.cuda.empty_cache()` under the ROCm build already in use (`gfx1201`) is the same call as CUDA — no new API surface; this project already calls `device_map="cuda:0"`/`dtype=torch.bfloat16` today on an AMD GPU, so the CUDA-namespace-aliases-to-HIP fact is already relied upon, not a new assumption.
- **`POST /synthesize` gains an optional `model_id` field.** Simplest shape: `tts_service` self-manages — on a request naming a `model_id` that differs from what's resident, it calls `ensure_loaded(model_id)` first, THEN synthesizes, all within the one existing HTTP call. This avoids a second round trip and avoids the backend needing to track `tts_service`'s resident-model state itself (one source of truth, in the process that actually owns the GPU memory).
- **But the milestone explicitly wants an *explicit* "load-on-demand" UX**, not a silent first-request penalty — so also expose a **dedicated `POST /model/{model_id}/load`** endpoint on `tts_service`, and a matching backend endpoint (e.g. `POST /projects/{id}/model`) the Config Panel calls directly when the user picks a model from the dropdown, ahead of hitting Generate. `/synthesize`'s own implicit-load-if-needed stays as a safety net (handles "user forgot to preload"), the explicit endpoint is what gives the UI something to show a spinner against.
- **Route the swap call through the existing lock, don't add a new one.** Treat "load model" as just another claimant of `try_claim_generation("model-load:{model_id}")` in `generation_worker.py` — it already prevents any two generation-triggering actions (preview / segment / batch / now model-load) from racing, with zero new locking primitives. Direct reuse of an existing pattern, not a new mechanism.
- **Latency is real but bounded and already within the existing timeout budget.** `tts_service/model.py`'s own comment says "this can take 1-2 minutes on first run" — but that's the one-time Hugging Face *download*; the volume `qwen-ebook-tts-hf-cache` already persists downloaded weights across restarts, so a swap between two already-downloaded checkpoints is a disk→VRAM load (materially faster — commonly tens of seconds for models this size, not minutes). This fits inside the 300s `httpx` read timeout already used for `/synthesize` — **a plain blocking request/await, no SSE, no background task, is the lazy-correct answer here** unless real-hardware timing during the build phase proves otherwise; don't build SSE progress for this preemptively.
- **`get_supported_speakers()` may differ between checkpoints — do not assume the preset list is identical across 1.7B and 0.6B.** This is a genuine open question flagged for a phase-specific spike (verify once the 0.6B checkpoint is actually downloaded), not something to hardcode an assumption about here. Also note: the wheel's own code shows `if self.model.tts_model_size in "0b6": instruct = None` — **the 0.6B checkpoint silently drops `instruct` steering entirely.** This is a real, verified behavioral difference the Config Panel/UX should surface (switching to 0.6B changes what the voice-instruction field even does), not just a VRAM/speed tradeoff.

### Build-order interaction with Capability 1

Both capabilities modify `tts_service/server.py`'s request-handling shape and both need the same "GPU has exactly one thing happening at a time" discipline. They are not strictly sequential — cancel only touches `/synthesize`; model-swap adds a new `/model/{id}/load` endpoint — but they're cheapest to design in the same pass: introduce one small `_engine_state` module in `tts_service` (currently-loaded model id + the cancellation `threading.Event`) that both endpoints read/write, instead of two independent globals bolted on separately. See Build Order below for why cancel should still land first in sequence despite this shared-file overlap.

## Capability 3 — FLAC/Opus in the ffmpeg Join

Fully independent of capabilities 1 and 2 — touches only `audio_join.py` and `config.py`, no shared code path with the TTS boundary at all.

- `audio_join.py`'s `if fmt == "wav": codec_args = ["-c", "copy"] else: ["-c:a", "libmp3lame"]` becomes a small dict/dispatch: `{"flac": ["-c:a", "flac"], "opus": ["-c:a", "libopus"], "mp3": ["-c:a", "libmp3lame"]}` — a lookup, not a new abstraction (no need for a codec strategy class for 3 fixed options).
- `config.py`'s `_ALLOWED_OUTPUT_FORMATS = {"wav", "mp3"}` → `{"flac", "mp3", "opus"}` (milestone: "WAV dropped"). The existing fail-fast-at-settings-load-time pattern already does the right thing here — just update the set.
- **Verify `libopus`/`flac` are present in the backend container's ffmpeg build** (`backend/Containerfile.backend`) before relying on this — most distro ffmpeg builds include both by default, but this container is minimal/CPU-only by design. One `ffmpeg -codecs | grep -E 'opus|flac'` check inside the built image closes this out; don't assume.
- Response `media_type` in `main.py`'s serving paths needs a matching lookup too (`audio/flac`, and Opus is typically muxed into an Ogg or WebM container by ffmpeg's default muxer when the output extension is `.opus` — confirm the extension-to-mimetype pairing during implementation; it's a one-line lookup, not a design decision).

## Capability 4 — Download Endpoint + Filename

Also independent of capabilities 1 and 2. Loosely coupled to capability 3 (the download response's filename/Content-Type needs to know the final codec, which only becomes variable once 3 lands) but no hard build-order dependency — could be built in either order or in parallel.

- **`Project.output_filename: str | None`** (new SQLModel column) — set via the Config Panel before generation starts, alongside the existing `output_format` field this milestone is already reworking into a per-project setting (today `output_format` is a fixed global `settings.OUTPUT_FORMAT`, serialized read-only in `_serialize_project`; this milestone's Config Panel work already implies promoting BOTH format and filename from global settings to per-project DB columns/PATCH-able fields — do this as one combined schema change, not two).
- **New `GET /projects/{id}/download`** endpoint in `main.py`, sibling to the existing `GET /segments/{id}/audio.wav` / `GET /characters/{id}/preview.wav` pattern already established — reads `Project.output_path`, serves it with `Content-Disposition: attachment; filename="{output_filename}.{output_format}"` and the format-appropriate `media_type` (same lookup table as capability 3's mimetype concern). Reuse `fastapi.responses.FileResponse` (already a FastAPI dependency) rather than reading bytes into memory the way the WAV preview endpoints do today — those are fine for short preview clips but a full joined audiobook file shouldn't be buffered fully into a `Response(content=...)` the way `get_segment_audio` does.
- **Filename validation**: same discipline as everywhere else in this codebase (server-generated ids for actual file paths, user input never used as a raw path component) — the user-supplied filename is ONLY the download's `Content-Disposition` display name, never the actual on-disk path (`out_path` stays a `uuid4().hex`-based server path, exactly as today). Sanitize only enough to keep it a safe header value (strip path separators/control characters) — no need for a full filename-sanitization library for a single-user tool serving its own generated file back to itself.

## Suggested Build Order

1. **Immediate-cancel (Capability 1) first.** It's the one genuine technical unknown here (does `stopping_criteria` actually abort a live ROCm decode loop the way it does on the HF reference CUDA path — verified as reachable in the library's Python call chain, NOT yet verified against real GPU inference). It's also the most architecturally invasive change (per-segment generate has to become a background task with a cancel registry, `tts_service` gains its first piece of shared mutable state). Landing it first de-risks the milestone's hardest question early and gives capability 2 an `_engine_state` scaffold to extend rather than build from scratch.
2. **Model swap (Capability 2) second**, extending the same `tts_service` engine-state module. Mechanically well-understood (load/unload is a standard PyTorch pattern already half-implemented in this codebase's model-loading code) — the open questions here (speaker-list parity across checkpoints, instruct-drop on 0.6B, real swap latency) are spike-and-verify items, not architecture risk.
3 & 4. **FLAC/Opus (3) and filename/download (4)** — fully decoupled from 1 and 2 (no shared code with the TTS HTTP boundary), and mostly decoupled from each other. Sequence them last since they're additive/mechanical and lower-risk; do 3 before 4 only because the download endpoint's Content-Type/extension logic is more naturally written once the codec set it needs to handle is final, not because of any hard technical dependency. Could ship in the same phase as one Config Panel change (both extend `Project` with new per-project settings columns in one migration pass).

**Cross-cutting frontend note:** capability 1's backend change flips per-segment generate from a synchronous `200 {segment}` response to an asynchronous `202` + poll/SSE contract (matching the existing character-preview and batch patterns). Any frontend work on the per-row generate/stop button (`SegmentTable.tsx`/`SegmentPreview.tsx`) should land AFTER that backend contract change, not against today's synchronous shape — building UI against the soon-to-change synchronous contract is wasted work.

## Anti-Patterns to Avoid

### Anti-Pattern: Reaching for a task queue to solve cancellation
**What people do:** see "need to cancel a long-running background job" and reach for Celery/RQ/arq with a broker.
**Why it's wrong:** this app has exactly one GPU, one resident model, and an existing single-flight lock that already serializes all generation app-wide. A task queue adds a broker process, serialization, and a whole new failure mode for a problem that a `threading.Event` plus a `StoppingCriteria` check solves in-process. CLAUDE.md already rules this out explicitly.
**Do this instead:** the `_cancel_event` + `stopping_criteria` design above, gated by the lock that already exists.

### Anti-Pattern: Rewriting the backend's HTTP client to async to "fix" cancellation
**What people do:** see that `run_in_threadpool` can't be cancelled mid-flight and conclude the client needs an async `httpx.AsyncClient` with connection-level cancellation.
**Why it's wrong:** the actual bottleneck is server-side (`tts_service` doesn't return until the whole segment finishes) — fixing that makes the existing blocking client return promptly on its own, no client rewrite needed. An async client migration would be solving the same UX symptom with strictly more moving parts.
**Do this instead:** make `tts_service`'s generate loop interruptible; leave the existing sync `httpx.post` + `run_in_threadpool` client as-is.

### Anti-Pattern: Treating model choice as purely global config
**What people do:** since only one model can be resident at a time, put the choice in `Settings`/env vars like `OUTPUT_FORMAT` is today.
**Why it's wrong:** this breaks the content-hash cache's correctness contract — a project generated under 1.7B and later regenerated under a globally-flipped-to-0.6B setting needs its cache to bust, and that requires the model identity to be recorded per-project, not read from ambient global state at generate time.
**Do this instead:** `Project.tts_model` column feeding `compute_cache_key`, reconciled against `tts_service`'s single physically-resident model at generate time.

## Integration Points Summary

| Boundary | Communication | New in this milestone |
|----------|---------------|------------------------|
| Frontend ↔ backend, per-segment generate | REST, currently sync `200` | Becomes async `202` + poll/SSE (Cap 1) |
| Frontend ↔ backend, batch cancel | REST `POST /projects/{id}/generate/cancel` (exists) | Extended to also call tts_service `/cancel` (Cap 1) |
| Frontend ↔ backend, per-segment cancel | Does not exist today | New `POST /segments/{id}/generate/cancel` (Cap 1) |
| Frontend ↔ backend, model select | Does not exist today (fixed display value) | New `POST /projects/{id}/model` (Cap 2) |
| Backend ↔ tts_service, synth | HTTP `POST /synthesize` (exists) | Gains optional `model_id`; server-side interrupt via stopping_criteria (Cap 1+2) |
| Backend ↔ tts_service, cancel | Does not exist today | New `POST /cancel`, global `threading.Event` (Cap 1) |
| Backend ↔ tts_service, model load | Does not exist today | New `POST /model/{model_id}/load` (Cap 2) |
| Backend ↔ ffmpeg | `subprocess.run`, 2-way branch (exists) | 3-way codec dispatch table (Cap 3) |
| Frontend ↔ backend, download | Does not exist today | New `GET /projects/{id}/download`, `FileResponse` (Cap 4) |

## Sources

- `backend/app/tts_client.py`, `backend/tts_service/server.py`, `backend/tts_service/model.py` — call boundary, verified by direct read.
- `deploy/qwen-ebook-tts.container`, `deploy/qwen-ebook-backend.container` — container topology, verified by direct read.
- `backend/app/main.py` (`cancel_generation`, `regenerate_segment`, `generate_segment`), `backend/app/generation_worker.py` (`try_claim_generation`/`_running_generations`) — current cancel/lock semantics, verified by direct read, including the codebase's own documented ceiling on today's cancel behavior.
- `backend/app/cache_key.py`, `backend/app/audio_join.py`, `backend/app/config.py`, `backend/app/models.py` — current seams for model-version, codec, and per-project schema, verified by direct read.
- Installed `qwen_tts` wheel, `qwen_tts/inference/qwen3_tts_model.py` (`generate_custom_voice`, `_merge_generate_kwargs`) — verified directly from the container image's installed package (not from PyPI docs or memory): confirms `**kwargs` (including a HF-standard `stopping_criteria`) flow through to the underlying `Qwen3TTSForConditionalGeneration.generate()` call, and confirms the 0.6B checkpoint (`tts_model_size in "0b6"`) silently drops `instruct` steering — a real, load-bearing behavioral difference between the two checkpoints this milestone must account for.
- `frontend/src/components/ConfigPanel.tsx`, `frontend/src/hooks/useGenerationLock.ts` — current frontend contract with the generation lock/cancel endpoints, verified by direct read, confirming the documented cancel limitation is already user-visible copy today.

---
*Architecture research for: Qwen Ebook Narrator v1.1 milestone (generation-control + config-panel integration)*
*Researched: 2026-07-13*
