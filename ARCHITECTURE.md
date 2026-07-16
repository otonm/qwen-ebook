<!-- generated-by: gsd-doc-writer -->
# Architecture

This is the developer-facing deep dive: how Qwen Ebook Narrator is built, why
each piece was chosen, and how data moves through it. If you just want to
know what the app does, see the top-level README; this document assumes
you're about to read or change the code.

## System overview

Qwen Ebook Narrator is a single-user, self-hosted web app: one FastAPI
process owns upload handling, LLM-driven text analysis, EPUB parsing, TTS
request orchestration, ffmpeg audio joining, and SQLite persistence. A
separate GPU-scoped process hosts the actual Qwen3-TTS model and is only
ever reached over an internal HTTP call from the backend — the backend
itself never imports `torch` or `qwen-tts`. A React SPA, built and served as
static assets from the backend container, is the sole UI. There is no
message queue, no separate worker process, and no auth layer: the app is
reached exclusively over Tailscale by one trusted user, and concurrency is
handled with plain `asyncio` tasks and per-project queues inside the single
backend process. Both the LLM and TTS integrations are HTTP-only — there is
no mock/offline mode built into the app; development and testing happen
against the real OpenRouter API and the real TTS container.

## Component diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ Podman pod "qwen-ebook" (loopback-only :8000 published to host)      │
│                                                                       │
│  ┌───────────────────────────────┐      ┌─────────────────────────┐ │
│  │ qwen-ebook-backend (CPU-only)  │      │ qwen-ebook-tts (GPU)    │ │
│  │ backend/app/*.py, FastAPI      │─http─▶│ backend/tts_service/   │ │
│  │  - upload / EPUB parse         │ :8001 │ Qwen3-TTS-12Hz-1.7B-   │ │
│  │  - chunking                    │       │ CustomVoice on ROCm    │ │
│  │  - OpenRouter cast/segment     │       │ /dev/kfd, /dev/dri     │ │
│  │    analysis                    │       │ only mounted here      │ │
│  │  - SQLModel / SQLite           │       └─────────────────────────┘ │
│  │  - ffmpeg join                 │                                  │
│  │  - serves frontend/dist as     │                                  │
│  │    static files                │                                  │
│  └───────────────┬─────────────────┘                                 │
│                  :8000 (loopback)                                    │
└──────────────────┼────────────────────────────────────────────────────┘
                    │
              tailscale serve
                    │
            ┌───────▼────────┐        ┌──────────────────┐
            │ Browser (React │        │ OpenRouter (LLM   │
            │ SPA, Tailscale │        │ gateway, external)│
            │ client)        │◀──────▶│ x-ai/grok-4.3     │
            └────────────────┘        └──────────────────┘
```

- `qwen-ebook-backend` and `qwen-ebook-tts` are two separate Podman containers
  in one pod (`deploy/qwen-ebook.pod`); they talk over the pod-internal
  network, port 8001 is never published to the host.
- The backend is the only container reachable from the host/tailnet
  (`deploy/qwen-ebook-backend.container`, `deploy/qwen-ebook.pod`:
  `PublishPort=127.0.0.1:8000:8000`).
- `tailscale serve` on the host is the only path in from the tailnet — there
  is no separate auth layer in the app itself (see Design Decisions below).

## Data flow

1. **Upload** — `POST /projects` (`backend/app/main.py`) reads the upload in
   bounded chunks (rejecting anything over `MAX_UPLOAD_BYTES`), extracts text
   via `epub_parser.extract_text()` for `.epub` files (spine reading order,
   footnote stripping, zip-bomb guard) or decodes UTF-8 directly for plain
   text, creates a `Project` row with `status="analyzing"`, and spawns a
   background `asyncio.Task` running `analysis_worker.run_analysis()`.
2. **Chunk (if oversized)** — `analysis_worker.estimate_tokens()` (a
   chars/4 heuristic, no tokenizer dependency) sizes the source text; text
   at or under `ANALYSIS_TOKEN_LIMIT` is analyzed in a single LLM call via
   `run_analysis()`, oversized text falls back to
   `_run_chunked_analysis()`, which splits it with
   `chunking.chunk_paragraphs()` (paragraph-boundary greedy merge, sentence
   split as the oversized-paragraph fallback) and groups the pieces into
   per-call batches via `_group_chunks()`.
3. **LLM cast/segment analysis** — `analysis_client.analyze()` posts to
   OpenRouter's chat-completions endpoint (`x-ai/grok-4.3` by default,
   `OPENROUTER_MODEL` env-configurable) with `response_format:
   json_schema` set to `CastAnalysisResult`'s own Pydantic schema, so the
   parsed response can never structurally drift from what gets persisted.
   Multi-chunk runs carry forward a `running_cast` + last-20
   `recent_segments` continuity window so repeat characters across chunks
   are reconciled by exact name match rather than re-invented per chunk.
   Results are persisted as `Character` and `Segment` rows
   (`analysis_worker._persist_result()`).
4. **SSE progress** — the frontend subscribes to
   `GET /projects/{id}/analysis-stream`; `analysis_worker` pushes
   `("progress"|"done"|"error", payload)` tuples onto a per-project
   `asyncio.Queue`, drained by `main.analysis_stream()` and forwarded as
   Server-Sent Events (`fastapi.sse.EventSourceResponse`).
5. **Review** — the user edits cast (name, description, voice
   preset/instructions, merge/undo-merge) and segments (reassign character,
   edit text/instructions, bulk-reassign) via `PATCH`/`POST` endpoints in
   `main.py`. Any edit that changes voice-affecting fields bumps a
   `voice_version`/`generation_version` counter and clears the segment's
   cached `audio_path` — it does **not** auto-fire regeneration (see Design
   Decisions).
6. **Per-segment TTS generation** — `POST /segments/{id}/generate` (single
   row) or `POST /projects/{id}/generate` (whole project, via
   `generation_worker.run_batch_generation()`) call
   `main.regenerate_segment()`, which recomputes a content-hash cache key
   (`cache_key.compute_cache_key()` over resolved speaker + voice
   instructions + text + the *live* per-project `model_id`
   — `Project.tts_model`, `"1.7b"` or `"0.6b"` — rather than a hardcoded
   constant, so a per-project model swap naturally invalidates every
   previously-cached segment) and only calls `tts_client.synthesize()` on a
   cache miss. `synthesize()` posts to the TTS container's
   `POST /synthesize` over HTTP (`TTS_SERVICE_URL`). A project's model can
   be swapped on demand — the backend calls `tts_client.load_model()`,
   which posts to the TTS container's `POST /model/{model_id}/load` to swap
   the resident checkpoint between the two supported models. All
   generation (segment, character preview, or batch) shares one global
   single-flight lock (`generation_worker.try_claim_generation()`, keyed by
   a `"segment:{id}"`/`"preview:{id}"`/`"batch:{id}"` label) since only one
   synthesis call may use the single GPU at a time; an in-flight call can be
   interrupted via `POST /projects/{id}/generate/cancel`, which calls
   `tts_client.cancel()` (posts to the TTS container's `POST /cancel`) and
   awaits the running task rather than cancelling it outright, so the loop
   only advances once the interrupted call has actually finished. Batch
   generation streams `{segment_id, n, total, status}` progress over
   `GET /projects/{id}/generation-stream`, is resumable across a crash
   (stale `"generating"` rows are reset to `"pending"` on restart), and one
   segment's synthesis failure never aborts the rest of the run.
7. **Join** — once every segment has a valid `audio_path`,
   `generation_worker._join_project()` calls `audio_join.join_wavs()`, which
   shells out to system `ffmpeg` via the concat demuxer with an explicit
   argument list (never a shell string) and always re-encodes (no
   stream-copy path) into one of three supported output formats looked up
   from `audio_join.CODEC_TABLE` — `flac`, `mp3` (`libmp3lame`), or `opus`
   (`libopus`, muxed into an Ogg container) — per `Project.output_format`;
   an unlisted format raises rather than silently falling back to `mp3`.
   The joined file is written to `Project.output_path`.
8. **Download** — the joined file is served back to the browser; per-segment
   preview audio (`GET /segments/{id}/audio.wav`) and character voice
   previews (`GET /characters/{id}/preview.wav`) are available throughout
   review for spot-checking before a full batch run.

## Key abstractions

| Abstraction | File | Purpose |
|---|---|---|
| `Project` / `Character` / `Segment` (SQLModel tables) | `backend/app/models.py` | The entire persisted app state: source text, detected cast, ordered narration/dialogue segments, generation status, and cache keys. |
| `CastAnalysisResult` / `CharacterSuggestion` / `SegmentSuggestion` (Pydantic) | `backend/app/schemas.py` | One schema shared verbatim across the LLM's structured-output contract, DB persistence, and the API response shape — no separate hand-maintained schema to drift. |
| `Settings` (frozen dataclass) | `backend/app/config.py` | Typed, environment-driven configuration (upload/output paths, LLM/TTS service URLs and defaults, analysis token limit), loaded once as a module-level singleton. |
| Per-project `asyncio.Queue` progress registries | `backend/app/analysis_worker.py`, `backend/app/generation_worker.py` | In-process pub/sub for SSE progress, one registry for analysis and a separate one for generation — no external broker. |
| `compute_cache_key()` | `backend/app/cache_key.py` | SHA-256 over `(resolved_speaker, voice_instructions, text, model_id)`, where `model_id` is always the *live* `Project.tts_model` recomputed fresh before every generate call — the sole cache-invalidation mechanism for generated audio, and what makes a per-project model swap force-invalidate every previously-cached segment for free. |
| `synthesize()` / `load_model()` / `cancel()` / `tts_health()` | `backend/app/tts_client.py` | The backend's only touchpoint with TTS — a thin `httpx` HTTP client with no mock/offline mode; every call is a real POST to the TTS container (`TTS_SERVICE_URL`). |
| `extract_text()` | `backend/app/epub_parser.py` | EPUB → plain narrative text: spine reading order, footnote stripping, zip-bomb guard, chapter-boundary preservation. |
| `chunk_paragraphs()` | `backend/app/chunking.py` | Stdlib-regex paragraph/sentence chunker used only when text exceeds the single-call token budget. |
| `estimate_tokens()` | `backend/app/analysis_worker.py` | chars/4 token-count heuristic (no tokenizer dependency) deciding whether `run_analysis()` sends the whole text in one LLM call or falls back to chunked analysis. |
| `try_claim_generation()` / `get_generation_task_by_label()` | `backend/app/generation_worker.py` | A single global generation lock (one GPU, one synthesis call at a time) keyed by `"segment:{id}"`/`"preview:{id}"`/`"batch:{id}"` labels, so any in-flight generation of any kind can be looked up and cancelled. |
| TTS inference server | `backend/tts_service/server.py`, `backend/tts_service/model.py` | The isolated GPU process: loads a resident Qwen3-TTS checkpoint (`"1.7b"` by default) at startup, exposes `POST /synthesize`, `POST /model/{model_id}/load` (on-demand checkpoint swap between the two supported models), `POST /cancel` (interrupts in-flight synthesis), and `GET /healthz`; runs a periodic keepalive matmul to avoid ROCm idle-downclock latency spikes. |

## Directory structure rationale

```
backend/
  app/            FastAPI backend — the CPU-only process (models, endpoints,
                   workers, clients). Never imports torch/qwen-tts (DEPL-01
                   isolation boundary).
  tts_service/     GPU-scoped inference server — the only place torch/
                   qwen-tts are imported. Built into a separate container
                   image (Containerfile.tts) with /dev/kfd, /dev/dri passthrough.
  Containerfile.backend / Containerfile.tts   Two separate container images
                   per the CPU/GPU isolation boundary above.
frontend/
  src/
    components/    React screens (UploadScreen, CastWizard, ProjectScreen,
                    SegmentTable, ConfigPanel, ProjectListScreen) plus a
                    shadcn/ui component set under components/ui/.
    hooks/         useAnalysisStream / useGenerationStream — thin SSE
                    consumers backing the two progress streams above.
    api/client.ts   All backend HTTP calls in one place.
deploy/
  *.pod, *.container   Podman Quadlet (systemd) unit files — the permanent
                   production deployment shape.
  run-local.sh     Manual two-container dev bring-up (no systemd).
  bootstrap-vm.sh  One-time VM provisioning (Podman, Tailscale, git).
```

The `backend/app` vs `backend/tts_service` split exists solely to enforce
the GPU/CPU isolation boundary at the container level, not just in code —
the backend image is built without `torch`/`qwen-tts` at all, so there is no
way for a bug to accidentally pull GPU inference into the process that's
reachable from the host network.

## Tech stack and rationale

| Area | Choice | Why |
|---|---|---|
| Backend framework | FastAPI `0.139.0` (`backend/pyproject.toml`) | One process owns upload, LLM calls, EPUB parsing, the TTS request queue, ffmpeg join, and SQLite — native async, native SSE support (`fastapi.sse.EventSourceResponse`) is used directly rather than adding a WebSocket layer for one-way progress push. |
| Persistence | SQLModel over a single SQLite file (`backend/app/db.py`, `backend/app/models.py`) | Single-user app, no need for a network database. `Project`/`Character`/`Segment` tables; audio is referenced by filesystem path, never blobbed into the DB. |
| LLM | OpenRouter via plain `httpx` calls, no provider SDK (`backend/app/analysis_client.py`) | OpenRouter is a routing layer over many models, so `OPENROUTER_MODEL` (default `x-ai/grok-4.3`) is swappable without a code change. Structured JSON-schema output (`CastAnalysisResult.model_json_schema()`) keeps the LLM response contractually tied to the persistence/API schema. |
| TTS model | Qwen3-TTS-12Hz-1.7B-CustomVoice (`backend/tts_service/`), pinned `qwen-tts==0.1.1` | Preset + free-text steering, no voice cloning — the voice-cloning "Base" variant's speaker-encoder path was found unreliable on ROCm. |
| GPU runtime | ROCm 7.2 PyTorch build (`docker.io/rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.9.1`, `backend/Containerfile.tts`) | Matched to the production AMD RX 9070 XT (`gfx1201`) — officially ROCm-7.2+-supported, unlike the `gfx1103` integrated GPU used in early development, which reproducibly crashed on real inference. |
| EPUB parsing | `ebooklib` + `beautifulsoup4` (`features="lxml-xml"`) + `lxml` | Reading-order (`book.spine`) traversal instead of manifest order, which can silently scramble chapters; `lxml`'s default entity/network-resolution-disabled parser avoids reopening XXE. |
| Audio join | System `ffmpeg` via `subprocess.run` with an explicit arg list (`backend/app/audio_join.py`) | Concat demuxer, not the concat filter or `pydub` (unmaintained) — no shell string interpolation, even though inputs are server-generated filenames. |
| Frontend | React 19 + Vite 8 + TypeScript, Tailwind CSS 4, shadcn/ui components (`frontend/package.json`) | SPA built to static assets and shipped inside the backend's container image (`Containerfile.backend`'s multi-stage build) rather than a separate frontend host — one deployable process, matching the single-VM/no-load-balancer deployment target. |
| Container runtime | Podman + Quadlet (systemd units) | User's existing infra; GPU passthrough via `/dev/kfd`/`/dev/dri` device mounts scoped to only the TTS container. |
| Concurrency | Plain `asyncio.create_task()` + per-project `asyncio.Queue` registries, no task queue | Single GPU, single user — no Celery/Redis. Background tasks are held in a module-level `set` to avoid asyncio's fire-and-forget garbage-collection footgun. |
| Tooling | `uv` (deps/venv), `ruff` (lint: `E, F, I, UP, B`) | See `backend/pyproject.toml`. |

## Design decisions and outcomes

- **Self-hosted Qwen TTS on ROCm, not a cloud TTS API.** Avoids per-request
  cost and keeps generation on the local Tailscale network. Real inference
  was proven correct against the production RX 9070 XT VM (mono 24kHz WAV,
  96.5% non-zero samples for a 3-sentence sample) — see
  `.planning/PROJECT.md` Key Decisions and `deploy/README.md`'s "D-09 GPU
  re-verification checklist". A known transitive dependency (`sox`, both the
  PyPI wrapper and the system binary, required by `qwen-tts`'s tokenizer)
  had to be added back to `Containerfile.tts`/`requirements.txt` after being
  removed under the mistaken assumption it was unused.

- **Podman, not Docker.** A fixed infra constraint, not a technical
  trade-off (see `CLAUDE.md` Constraints). Delivered as a two-container pod
  (`deploy/qwen-ebook.pod`) with GPU device passthrough isolated to the TTS
  container only — verified directly by checking for `/dev/kfd`/`/dev/dri`
  inside each container rather than trusting `podman inspect`, which was
  found not to reflect `--device`-passed devices in its JSON output on this
  Podman version.

- **Rootful Podman, not rootless.** `--group-add keep-groups` (the original
  plan for non-root GPU access) was verified not to grant real `/dev/kfd`
  access on the production host's Podman/crun combination — render/video
  host GIDs are lost in the rootless user-namespace mapping regardless of
  group membership. The TTS container therefore runs as `User=0`/`Group=0`
  (`deploy/qwen-ebook-tts.container`); the backend container stays non-root
  since it needs no device access.

- **Invalidate cached audio on edit; do not auto-regenerate.** An edit
  (text, voice instructions, character reassignment) bumps
  `generation_version`, clears `audio_path`, and marks the segment
  `"pending"` — but generation only fires when the user explicitly triggers
  it (per-row `POST /segments/{id}/generate` or the batch
  `POST /projects/{id}/generate`). This was **reversed mid-development**
  from an original "auto-regenerate on edit" design after the user found
  auto-fire-on-blur surprising in practice during UAT
  (`.planning/PROJECT.md` Key Decisions, GEN-03/D-06).

- **Content-hash caching for generated audio.** `compute_cache_key()`
  hashes `(resolved_speaker, voice_instructions, text, model_id)`, where
  `model_id` is the project's *live* `tts_model` field (`"1.7b"`/`"0.6b"`),
  not a hardcoded version constant. It is always recomputed live from
  current DB state before a generate call rather than trusted as stored
  ground truth, so an out-of-band character preset change, a text edit, or
  a per-project TTS model swap (`POST /model/{model_id}/load` against the
  TTS container) are all naturally cache-busting with no separate
  invalidation code path. Batch regeneration and single-row regeneration
  share the exact same `regenerate_segment()` function, so their cache-hit
  behavior can never drift apart.

- **On-demand model swap and mid-synthesis cancel, not a static single
  model.** The TTS container exposes `POST /model/{model_id}/load` to swap
  its resident checkpoint between the two supported models without a
  container restart, and `POST /cancel` to interrupt an in-flight
  `/synthesize` call. Cancel handlers never call `task.cancel()` on the
  backend's own generation task — cancelling a task awaiting
  `run_in_threadpool` was found not to wait for the underlying worker
  thread to actually stop, which would release the global generation lock
  while the GPU call was still running. Instead they call
  `tts_client.cancel()` (the real server-side interrupt) and then plainly
  `await` the task, which only returns once synthesis has genuinely
  finished.

- **Tailscale-only exposure, no separate auth layer.** The backend
  container publishes only to `127.0.0.1:8000` on the host
  (`PublishPort=127.0.0.1:8000:8000` in `deploy/qwen-ebook.pod`); `tailscale
  serve` is the sole path in from the tailnet. This is a deliberate
  trust-boundary decision for a single-user tool, not an oversight — see
  `CLAUDE.md` Constraints ("Network") and "What NOT to use" ("Multi-tenant
  auth").

## Testing

There is no automated test suite (no `backend/tests/` directory exists) —
testing runs against the real deployment: bring the two-container pod up
with `bash deploy/run-local.sh` and exercise the app end-to-end (upload →
analysis → generation → join). There is no mock/offline mode for either
external dependency — the app always talks to the real TTS container and
the real OpenRouter API.
