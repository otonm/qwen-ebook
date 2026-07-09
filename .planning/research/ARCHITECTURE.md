# Architecture Research

**Domain:** Self-hosted ebook-to-audiobook narration app (LLM text analysis + multi-voice TTS + audio joining, single-user, GPU-backed)
**Researched:** 2026-07-09
**Confidence:** MEDIUM-HIGH (grounded in real open-source projects of near-identical shape, plus official Podman/ROCm docs; specific numeric tuning values are LOW confidence and should be validated during implementation)

## Standard Architecture

### System Overview

```
┌───────────────────────────────────────────────────────────────────────┐
│  CLIENT (browser)                                                      │
│  ┌────────────────────────┐   ┌───────────────────────────────────┐   │
│  │ Segment Table (70%)     │   │ Config Sidebar (30%)               │   │
│  │ editable rows, status   │   │ file/model/output, live progress   │   │
│  │ badges per row          │   │ (poll or SSE)                      │   │
│  └────────────┬────────────┘   └────────────┬────────────────────┘   │
└───────────────┼───────────────────────────────┼─────────────────────┘
                │  REST (CRUD) + progress stream (SSE/poll)
┌───────────────▼───────────────────────────────▼─────────────────────┐
│  BACKEND / ORCHESTRATOR (single Podman container, CPU-only)          │
│  ┌────────────┐ ┌───────────────┐ ┌───────────┐ ┌─────────────────┐ │
│  │ Upload +    │ │ LLM Analysis  │ │ Job Queue │ │ Audio Joiner    │ │
│  │ EPUB Parser │ │ Client (xAI)  │ │ (1 worker)│ │ (ffmpeg concat) │ │
│  └──────┬──────┘ └──────┬────────┘ └─────┬─────┘ └────────┬────────┘ │
│         │               │                │                │          │
│  ┌──────▼───────────────▼────────────────▼────────────────▼───────┐ │
│  │                  Project / Segment / Character models            │ │
│  └──────────────────────────────┬───────────────────────────────────┘ │
└─────────────────────────────────┼─────────────────────────────────────┘
                                   │  HTTP (podman internal network)
        ┌──────────────────────────┼───────────────┐   outbound HTTPS
        │                          │               ▼
┌───────▼────────────────┐  ┌──────▼──────────────────┐   ┌──────────────┐
│ TTS SERVICE             │  │ PERSISTENCE              │   │ xAI Grok API │
│ (separate Podman        │  │ SQLite (metadata/state)  │   │ (cloud, LLM  │
│  container, GPU         │  │ + filesystem             │   │  analysis)   │
│  passthrough: /dev/kfd, │  │ (source text, per-segment│   └──────────────┘
│  /dev/dri; Qwen TTS on  │  │  audio, final output)    │
│  ROCm, RX 9070 XT)      │  └───────────────────────────┘
│  concurrency=1           │
└──────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|-------------------------|
| Frontend SPA | Editable segment table, cast wizard, config sidebar, live progress display | React/Vue/Svelte SPA or lightweight server-rendered + fetch/HTMX; talks only to backend REST API |
| Backend API/Orchestrator | Project CRUD, file parsing, LLM call orchestration, job queue, state machine, triggers ffmpeg | FastAPI (Python) — matches Qwen TTS ecosystem tooling (Python-native, async, easy HTTP client to TTS service) |
| LLM Analysis Client | Sends source text (chunked if long) to xAI Grok, parses structured JSON (cast + segments), reconciles character identity across chunks | A backend *module*, not a separate service — outbound HTTPS call to cloud API, no local compute |
| TTS Inference Service | Loads Qwen TTS model once, keeps it resident in VRAM, exposes HTTP endpoint for single-segment synthesis | Separate Podman container, ROCm base image, OpenAI-compatible `/v1/audio/speech`-style endpoint (this is the established pattern — see `Qwen3-TTS-Openai-Fastapi-Rocm` and similar) |
| Job Queue | Tracks per-segment generation jobs, ensures sequential GPU access, survives restarts | SQLite-backed queue (segment `status` column doubles as queue state) + single in-process async worker task — no Redis/Celery needed at this scale |
| Audio Joiner | Concatenates per-segment audio into final MP3/WAV in order | `ffmpeg` subprocess using the concat demuxer (file-list based, not filter_complex) |
| Persistence Layer | Durable state for projects, cast, segments, and binary audio artifacts | SQLite for structured/queryable state; filesystem (one directory per project) for text and audio blobs — never store audio blobs in the DB |

## Recommended Project Structure

```
qwen-ebook/
├── backend/
│   ├── app/
│   │   ├── api/                 # FastAPI routers: projects, upload, characters, segments, progress
│   │   ├── models/               # Project, Character, Segment ORM models + Pydantic schemas
│   │   ├── services/
│   │   │   ├── epub_parser.py    # .txt/.epub -> plain text + chapter boundaries
│   │   │   ├── llm_analysis.py   # xAI Grok client: cast detection + segmentation, chunk reconciliation
│   │   │   ├── tts_client.py     # HTTP client to TTS service (retries, timeouts)
│   │   │   ├── job_queue.py      # asyncio worker consuming pending segments sequentially
│   │   │   └── audio_joiner.py   # ffmpeg concat wrapper
│   │   ├── db.py                 # SQLite engine/session
│   │   └── main.py               # app entrypoint, startup hook resumes interrupted jobs
│   └── Containerfile              # no GPU deps — thin, fast rebuilds
├── tts-service/
│   ├── server.py                  # FastAPI wrapping Qwen TTS model, single endpoint, concurrency=1
│   └── Containerfile               # ROCm base image, ~multi-GB, rebuilt rarely
├── frontend/
│   └── src/
│       ├── components/            # SegmentTable, ConfigSidebar, CastWizard
│       └── api/                   # typed REST client + progress polling/SSE hook
├── data/                            # bind-mounted volume, NOT in image
│   └── projects/{project_id}/
│       ├── source.txt
│       ├── segments/{segment_id}.wav
│       └── output.mp3
└── deploy/
    ├── podman-compose.yml (or Quadlet .container units)
    └── db.sqlite (bind-mounted, lives outside containers)
```

### Structure Rationale

- **`backend/` vs `tts-service/` as separate top-level directories, separate Containerfiles:** they have entirely different dependency footprints (thin Python web app vs. multi-GB ROCm/PyTorch image) and different rebuild cadences. Coupling them in one image means every backend code change triggers a full GPU-stack rebuild.
- **`data/` outside both container images, bind-mounted:** projects must survive container rebuants/redeploys; putting audio/text in the image or in an anonymous volume risks data loss on `podman-compose down` or image rebuild.
- **`services/` module boundary inside backend:** each service (parser, LLM client, TTS client, queue, joiner) is independently testable/mockable — critical because local dev has no GPU (per project constraints) and no desire to hit the real xAI API on every test run.

## Architectural Patterns

### Pattern 1: TTS as a separate, GPU-scoped microservice behind a plain HTTP API

**What:** The Qwen TTS model runs in its own container, loads once at startup, and exposes a minimal synchronous HTTP endpoint (e.g., `POST /synthesize {text, voice_instructions} -> audio bytes`). The web backend never touches the GPU directly.

**When to use:** Any time a resource-intensive, stateful model (loaded weights resident in VRAM) needs to serve a lightweight, frequently-restarted web layer. This is the dominant pattern across every real project surveyed (Qwen3-TTS-Openai-Fastapi-Rocm, TTS-Story's engine registry, tts-audiobook-tool's "standalone server component").

**Trade-offs:** +Independent restart/scale, +GPU device flags scoped to one container (least privilege, cleaner Podman GPU passthrough), +backend stays GPU-free so local dev works without ROCm. −One more container to deploy/network; −adds one HTTP hop per segment (negligible vs. inference time, which is seconds).

**Example:**
```python
# backend/app/services/tts_client.py
import httpx

class TTSClient:
    def __init__(self, base_url: str, timeout: float = 120.0):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def synthesize(self, text: str, voice_instructions: str) -> bytes:
        resp = await self._client.post(
            "/synthesize",
            json={"text": text, "voice_instructions": voice_instructions},
        )
        resp.raise_for_status()
        return resp.content  # raw wav/mp3 bytes
```

### Pattern 2: Segment status as the job queue (state machine, no separate queue table)

**What:** Each `Segment` row carries a `status` enum (`pending -> queued -> generating -> complete | error`, plus `stale` for post-edit). The single background worker polls/selects segments with `status = 'queued'` in order, marks them `generating`, calls the TTS client, writes the audio path, and marks `complete`. On backend startup, any segment left `generating` (from a crash mid-job) is reset to `queued` and resumed.

**When to use:** Single-user, single-GPU, modest job volume (tens to low-thousands of segments per project). Avoids standing up Redis/Celery/ARQ purely to serialize access to one GPU.

**Trade-offs:** +Zero extra infrastructure, +state is always consistent with what the UI needs to render (poll `GET /segments` and you have both "queue" and "progress" in one query), +durable across restarts since it's just SQLite rows. −Doesn't generalize to multi-worker/distributed processing if the project ever needs more than one GPU (acceptable given the fixed single-GPU deployment target).

**Example:**
```python
# backend/app/services/job_queue.py
async def worker_loop(db, tts_client):
    while True:
        segment = db.get_next_queued_segment()  # ORDER BY order_index, status='queued' LIMIT 1
        if segment is None:
            await asyncio.sleep(1)
            continue
        db.update_status(segment.id, "generating")
        try:
            audio = await tts_client.synthesize(segment.text, segment.voice_instructions)
            path = save_segment_audio(segment.project_id, segment.id, audio)
            db.mark_complete(segment.id, audio_path=path)
            await rejoin_project(segment.project_id)  # cheap ffmpeg concat, not full regen
        except Exception as e:
            db.mark_error(segment.id, str(e))
```

### Pattern 3: LLM analysis as a chunk-and-reconcile pipeline, not a single call

**What:** For long texts (full novels can exceed even large LLM context windows), split the source into chapter- or size-bounded chunks, send each to the Grok API for cast detection + segmentation independently, then reconcile character identity across chunks (e.g., "Sarah" detected in chunk 1 and chunk 5 must resolve to the same `Character` row) before writing final `Segment` rows.

**When to use:** Whenever input length is not bounded and could exceed model context in production use (this project explicitly targets full ebooks, not just short articles).

**Trade-offs:** +Handles arbitrarily long books, +keeps each LLM call fast and cheap. −Adds real complexity (name/identity matching across chunks is a genuine open problem, not just plumbing) — flag this for deeper research or a simpler v1 heuristic (e.g., match by exact name string, let user merge duplicates manually in the cast wizard).

## Data Flow

### Request Flow (end-to-end pipeline)

```
[Upload .txt/.epub]
    ↓
[Backend: parse → plain text + chapters] → Project(status=uploaded)
    ↓
[Backend: chunk text → xAI Grok API] → cast + segments (JSON)
    ↓
[Backend: reconcile characters, write rows] → Project(status=analyzed)
    ↓                                          Character[], Segment[](status=pending)
[User: cast wizard + table edits]  ←───────────────┐
    ↓ (PATCH /characters, /segments)                │ live edits, no regen triggered
[User: clicks Generate]                             │ unless segment already had audio
    ↓                                                │ (→ marks status=stale)
[Backend: mark segments queued] → Job Queue
    ↓ (single worker, sequential)
[Worker: POST TTS service /synthesize] → audio bytes
    ↓
[Backend: write segment audio file] → Segment(status=complete, audio_path)
    ↓ (after each segment, and always at explicit "join")
[Backend: ffmpeg concat all complete segments in order] → Project.output_path
    ↓
[UI: poll/SSE progress reflects each row's status + overall %]
```

### Regenerate-single-segment flow

```
[User edits row text/voice_instructions after audio exists]
    ↓
PATCH /segments/{id} → Segment(status=stale)
    ↓ (explicit "regenerate" action, or auto-enqueue on edit — product decision)
Segment(status=queued) → Job Queue picks it up (same worker, same path as initial gen)
    ↓
[Worker regenerates ONLY this segment]
    ↓
[Backend: cheap ffmpeg re-concat of the full ordered list] → Project.output_path updated
```

This is the same code path as initial generation — "regenerate one segment" is not a special case, it's just enqueuing a single segment ID instead of all of them. This is the key design insight: **don't build a separate "regenerate" pipeline; build one queue-a-segment primitive and call it from both "generate all" and "regenerate this row."**

### Data Model

```
Project
  id, name, created_at, updated_at
  source_filename, source_text_path
  status: uploaded | analyzing | analyzed | generating | complete | error
  llm_model, output_format (mp3|wav), output_path

Character
  id, project_id (FK)
  name, description (age/personality/gender, LLM-inferred)
  voice_type: preset | instructions
  preset_voice_id (nullable), voice_instructions (nullable)
  display_order

Segment
  id, project_id (FK), order_index
  character_id (FK, nullable until assigned)
  text, voice_instructions (per-segment override of character default)
  status: pending | queued | generating | complete | error | stale
  audio_path (nullable), duration_ms (nullable), error_message (nullable)
  updated_at
```

No separate `Job` table is needed — `Segment.status` + `order_index` IS the queue. If job history/audit becomes a real requirement later, add a lightweight append-only `JobLog` table, but don't build it preemptively.

### Key Data Flows

1. **Analysis flow (LLM-bound, cloud):** Source text → chunked outbound HTTPS calls to xAI → structured JSON → Character/Segment rows. One-time per project (re-run only if user explicitly requests re-analysis).
2. **Generation flow (GPU-bound, local, sequential):** Segment(queued) → TTS service HTTP call → audio file → Segment(complete) → cheap rejoin. Repeats per segment, strictly one at a time given single GPU.
3. **Progress flow (read-only):** Frontend polls `GET /projects/{id}/segments` (or subscribes to SSE) → renders per-row status badges + aggregate progress bar from count(complete)/count(total).

## Scaling Considerations

This is a single-user, single-GPU, personal tool — "scale" here means **text length / segment count per project**, not concurrent users.

| Scale | Architecture Adjustments |
|-------|---------------------------|
| Short text (article, few chapters, <100 segments) | Everything as described works with no changes; single LLM call may suffice without chunking |
| Full novel (1,000s of segments) | LLM analysis MUST chunk + reconcile (Pattern 3); ffmpeg join MUST use concat demuxer with a file list, not `filter_complex` (which does not scale past dozens of inputs); SQLite handles thousands of rows trivially, no changes needed there |
| Very long generation runs (hours of sequential TTS) | Job queue must survive backend restarts (resume `generating`→`queued` on startup) and the UI must tolerate long-lived progress polling/SSE connections; consider a lightweight ETA estimate (rolling average of prior segment durations) for the sidebar |

### Scaling Priorities

1. **First bottleneck:** LLM context window on full-book analysis — solved by chunking + reconciliation (Pattern 3), which should be assumed necessary from day one given this project's explicit ebook use case, not treated as a later optimization.
2. **Second bottleneck:** GPU inference throughput for very long books (sequential, one segment at a time, could take a long time for a full novel) — not really "solvable" further given the single-GPU constraint; the honest scaling answer is to set correct user expectations (background/batch processing, not real-time) rather than add parallelism that a single GPU can't actually exploit (see below).

## Anti-Patterns

### Anti-Pattern 1: Running the TTS model in-process inside the web backend

**What people do:** Load the Qwen TTS model directly in the FastAPI process that also serves the web UI, to "keep it simple" and avoid a second container.

**Why it's wrong:** Couples GPU device passthrough to the entire web stack (violates least-privilege in Podman), makes every backend restart (including trivial code changes during development) reload a multi-GB model into VRAM, blocks the event loop / competes for resources with request handling, and makes local development impossible without ROCm+GPU present (violates this project's own constraint that GPU-dependent behavior must be mockable in dev).

**Do this instead:** Separate container, HTTP boundary (Pattern 1). Mock the `TTSClient` in dev/tests.

### Anti-Pattern 2: Full pipeline regeneration on every edit

**What people do:** Any edit to a row's text or voice instructions triggers regenerating the entire audiobook from scratch.

**Why it's wrong:** Wastes GPU time (minutes to hours for a full book) for a one-line tweak, directly contradicts the explicit requirement that edits regenerate only the affected segment, and makes iteration on voice instructions painfully slow.

**Do this instead:** Segment-level status machine (Pattern 2) — mark only the edited segment `stale`/`queued`, regenerate it alone, then do a cheap ffmpeg re-concat (not re-encode) of the full ordered list.

### Anti-Pattern 3: Parallelizing TTS requests against a single GPU without a concurrency cap

**What people do:** Fire off multiple segment-generation HTTP requests concurrently to "speed things up," assuming the TTS service will handle them in parallel.

**Why it's wrong:** A single 16GB-VRAM GPU running one resident model instance does not meaningfully parallelize compute-bound inference — concurrent requests either serialize at the driver level anyway (no throughput gain) or risk VRAM contention/OOM if the inference library naively tries to hold multiple concurrent generation states. This matches what real self-hosted TTS servers do: bound concurrency to 1 (the `TTS_MAX_CONCURRENT`-style pattern seen in production Qwen3-TTS ROCm servers). [MEDIUM confidence — general GPU-serialization principle is well-established; the exact behavior of the specific Qwen TTS model under concurrent load was not independently benchmarked and should be spot-checked during implementation.]

**Do this instead:** Single worker, sequential queue (Pattern 2). If throughput ever truly matters, the correct lever is a faster/smaller model or a second GPU — not client-side concurrency against one device.

### Anti-Pattern 4: Storing generated audio as BLOBs in SQLite

**What people do:** Store per-segment WAV/MP3 data directly in the database for "consistency."

**Why it's wrong:** Bloats the DB file, makes backups/inspection painful, complicates streaming audio to the browser (files are natively servable via static file routes; BLOBs require an extra read-and-stream layer), and provides no real benefit at single-user scale.

**Do this instead:** Filesystem storage (`data/projects/{id}/segments/{segment_id}.wav`), DB stores only the path.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|----------------------|-------|
| xAI Grok API | Outbound HTTPS from backend, structured/JSON-mode completion request per text chunk | Requires retry/backoff for rate limits; chunk long books (Pattern 3); no local infra needed |
| Qwen TTS service | Internal HTTP call from backend to TTS container over the Podman network (e.g., `http://tts-service:8000/synthesize`) | Single endpoint, one request per segment, bounded concurrency; treat as a local "cloud-like" API even though it's on the same host |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|----------------|-------|
| Frontend ↔ Backend | REST (CRUD) + SSE or polling for progress | Progress can start as simple polling (`GET /segments` every 1-2s) for MVP; upgrade to SSE only if polling proves too chatty/laggy — don't over-engineer this early |
| Backend ↔ TTS service | Synchronous HTTP request per segment, backend-managed sequencing | Backend owns the queue and sequencing; TTS service itself should also cap its own internal concurrency to 1 as a second line of defense against accidental parallel calls |
| Backend ↔ Persistence | Direct SQLite access (ORM) + direct filesystem read/write within the process | No abstraction layer needed at this scale; keep it simple |
| Backend ↔ ffmpeg | Subprocess invocation, not a network service | Concat demuxer for joining (fast, no re-encode of already-correct-format segments); explicit encode step only needed if TTS output format differs from desired output format |

## Podman / GPU Passthrough Specifics

- Confirmed pattern (official Podman/AMD docs): `podman run --device /dev/kfd --device /dev/dri ...` grants ROCm compute access; rootless Podman additionally requires the invoking user to be in the `video`/`render` groups and `--group-add keep-groups` to propagate them into the container. [HIGH confidence, Red Hat + AMD official docs]
- Alternative: Container Device Interface (CDI) via `--device amd.com/gpu=<entry>`, AMD's newer/preferred mechanism for structured device injection. [MEDIUM confidence — confirmed to exist, not verified as the more mature path for this specific hardware yet]
- These device flags should be applied **only to the `tts-service` container**, never to the backend container — this is the concrete Podman-level enforcement of the "TTS as separate GPU-scoped service" pattern (Pattern 1).
- RX 9070 XT (RDNA4, LLVM target `gfx1201`) has official ROCm 7.x support as of current AMD documentation — this is a relatively recent addition, so pin a ROCm version known to support `gfx1201` explicitly in the TTS service's base image rather than floating on `latest`. [HIGH confidence per AMD's own system requirements page, but flag for a version-pinning check during setup since RDNA4 support is newer than most existing ROCm container tutorials/examples online, which mostly target older CDNA/RDNA2-3 cards]
- Local dev machine (non-GPU per project context) cannot run the TTS container's real inference path — the `TTSClient` HTTP boundary is also what makes a mock/stub TTS service (returning silent placeholder audio) trivial to swap in for local development, satisfying the project's "GPU-dependent behavior should degrade gracefully or be mockable" constraint.

## Suggested Build Order

1. **Data model + persistence** (Project/Character/Segment schema, SQLite, project CRUD API) — foundation everything else depends on.
2. **File upload + parsing** (.txt and .epub → plain text/chapters) — no GPU or LLM dependency, fully testable standalone.
3. **Frontend table + sidebar shell against mocked/fixture segment data** — can start immediately once the API contract (Segment/Character JSON shape) is defined in step 1; does NOT need real LLM or TTS to exist. This decouples UI iteration from the riskiest backend pieces.
4. **TTS service standalone spike** (separate track, can start in parallel with 1-3) — stand up the ROCm container, confirm Qwen TTS loads and serves a synthesis request on the actual RX 9070 XT hardware via Podman GPU passthrough. This is the highest-risk, most environment-specific component (newest-generation GPU + ROCm + Podman + rootless device passthrough all stacked); de-risk it early even though nothing else strictly blocks on it yet.
5. **LLM analysis integration** (xAI Grok call, JSON parsing, chunk+reconcile for long texts) — depends on 1-2; testable independently of TTS entirely, produces real Segment/Character data the frontend can render.
6. **Wire frontend to real backend** (cast wizard + editable table against real analysis output) — depends on 3 + 5.
7. **Job queue + backend-to-TTS integration** (single async worker, sequential HTTP calls to TTS service, status transitions) — depends on 5 (segments exist to generate) and 4 (TTS service exists to call).
8. **Audio joining** (ffmpeg concat) — depends on 7 producing segment files; can be developed/tested earlier against dummy silent audio files if useful to decouple from real TTS timing.
9. **Regenerate-single-segment + auto-rejoin** — mostly wiring on top of 7+8 (same queue-a-segment primitive, see Data Flow section); low incremental risk once 7+8 exist.
10. **Live progress UI** (polling first, SSE later if needed) — depends on 7 (there must be real status transitions to observe); start simple.
11. **Podman deployment** (compose/Quadlet files, GPU device scoping, Tailscale serving) — can be scaffolded early as a skeleton (empty services wired together) and filled in incrementally as each service solidifies; final integration/validation pass once 1-10 work locally.

**Key build-order insight:** the frontend table/sidebar and the TTS-on-ROCm spike are the two things that can and should start in parallel with the "main line" (data model → parsing → LLM → queue → join), because they have no dependency on each other and one of them (the GPU spike) carries the most environment/hardware risk in the whole project.

## Sources

- [How to configure AMD GPU for using in Podman containers on RHEL9 — Red Hat Customer Portal](https://access.redhat.com/solutions/7073764) — HIGH confidence, official
- [How to Use GPU Passthrough with Podman](https://oneuptime.com/blog/post/2026-03-18-use-gpu-passthrough-podman/view) — MEDIUM confidence
- [How to Use ROCm in Podman Containers](https://oneuptime.com/blog/post/2026-03-18-use-rocm-podman-containers/view) — MEDIUM confidence
- [AMD Container Runtime Toolkit — Running Workloads](https://instinct.docs.amd.com/projects/container-toolkit/en/latest/container-runtime/running-workloads.html) — HIGH confidence, official AMD docs
- [GitHub — antonsokolskyy/Qwen3-TTS-Openai-Fastapi-Rocm](https://github.com/antonsokolskyy/Qwen3-TTS-Openai-Fastapi-Rocm) — MEDIUM-HIGH confidence, direct real-world reference implementation for this exact stack (Qwen3-TTS + FastAPI + ROCm)
- [GitHub — groxaxo/Qwen3-TTS-Openai-Fastapi](https://github.com/groxaxo/Qwen3-TTS-Openai-Fastapi) — MEDIUM confidence, corroborates OpenAI-compatible server pattern and `TTS_MAX_CONCURRENT` concurrency bounding
- [GitHub — Xerophayze/TTS-Story](https://github.com/Xerophayze/TTS-Story) — MEDIUM-HIGH confidence, near-identical project shape (multi-voice TTS studio, chunk review/regeneration, job queue, local GPU + Qwen3-TTS backend) — strongest real-world corroboration of the overall architecture
- [GitHub — psdwizzard/chatterbox-Audiobook](https://github.com/psdwizzard/chatterbox-Audiobook) — MEDIUM confidence, corroborates queue + individual-chunk-regeneration pattern
- [GitHub — zeropointnine/tts-audiobook-tool](https://github.com/zeropointnine/tts-audiobook-tool) — MEDIUM confidence, corroborates standalone TTS server component pattern
- [GitHub — aedocw/epub2tts](https://github.com/aedocw/epub2tts) — LOW-MEDIUM confidence, corroborates EPUB parsing as a distinct pipeline stage
- [ROCm system requirements (Linux) — AMD ROCm Documentation](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/reference/system-requirements.html) — HIGH confidence, official; confirms RX 9070 XT / gfx1201 official support
- [ROCm compatibility matrix — AMD](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html) — HIGH confidence, official
- [Managing Background Tasks in FastAPI: BackgroundTasks vs ARQ + Redis](https://davidmuraya.com/blog/fastapi-background-tasks-arq-vs-built-in/) — MEDIUM confidence, informed the decision to avoid Redis/Celery given single-user/single-GPU scale
- [What is everyone using for scheduled background jobs and queued tasks? (not celery) — fastapi/full-stack-fastapi-template Discussion #2059](https://github.com/fastapi/full-stack-fastapi-template/discussions/2059) — LOW-MEDIUM confidence, community discussion corroborating SQLite-backed lightweight queue viability for single-node deployments

---
*Architecture research for: self-hosted ebook-to-audiobook narration app (LLM analysis + local multi-voice TTS + audio joining)*
*Researched: 2026-07-09*
