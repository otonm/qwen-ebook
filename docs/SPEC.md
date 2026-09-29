# Qwen Ebook Narrator: System Specification

Reverse-engineered from the code as of this branch. Where this document and the code disagree, the code wins.

## 1. Purpose

A self-hosted, single-user web app that turns long text (`.epub` or UTF-8 `.txt`) into a multi-voice narrated audiobook.

1. An LLM (OpenRouter) detects the cast (narrator plus speaking characters) and splits the text into an ordered script of narration and dialogue segments, each with delivery instructions.
2. The user reviews and edits cast and segments in a table-based UI.
3. A self-hosted Qwen3-TTS model renders each segment on a local GPU.
4. ffmpeg joins the segments into one audio file (`flac`, `mp3` or `opus`).

Non-goals: multi-tenancy, auth (Tailscale is the boundary), voice cloning, task queues, public exposure.

## 2. System architecture

```
                         Tailscale tailnet (only access path, no app-level auth)
                                        │
                                 tailscale serve
                                        │
┌───────────────────────────────────────▼─────────────────────────────────────┐
│  Podman pod "qwen-ebook"   (Quadlet units; only 127.0.0.1:8000 published)    │
│                                                                              │
│  ┌──────────────────────────────────────┐   HTTP :8001    ┌───────────────┐ │
│  │ qwen-ebook-backend  (CPU only)       │  (pod-internal) │ qwen-ebook-tts│ │
│  │ FastAPI, Python 3.12                 │ ───────────────▶│ (GPU, ROCm)   │ │
│  │                                      │  /synthesize    │ FastAPI       │ │
│  │  ┌────────────┐  ┌────────────────┐  │  /cancel        │ Qwen3-TTS     │ │
│  │  │ React SPA  │  │ REST + 2× SSE  │  │  /model/{id}/   │ CustomVoice   │ │
│  │  │ (static,   │  │ main.py        │  │       load      │ 1.7B | 0.6B   │ │
│  │  │ dist/)     │  └───────┬────────┘  │  /healthz       │ (1 resident)  │ │
│  │  └────────────┘          │           │                 │ /dev/kfd      │ │
│  │   analysis_worker  generation_worker │                 │ /dev/dri      │ │
│  │   (asyncio tasks + per-project       │                 └───────────────┘ │
│  │    asyncio.Queue for SSE)            │                                   │
│  │   ffmpeg (subprocess)  SQLite (WAL)  │                                   │
│  │   uploads/ output/ previews/         │                                   │
│  └──────────────────┬───────────────────┘                                   │
└─────────────────────┼────────────────────────────────────────────────────────┘
                      │ HTTPS (httpx)
                      ▼
            OpenRouter chat-completions
            (default x-ai/grok-4.3, json_schema output)
```

Design rules:

- **Isolation boundary:** the backend never imports `torch` or `qwen_tts`. All GPU work crosses the HTTP boundary to the TTS container.
- **One process, no broker:** background work is `asyncio` tasks. There is no Celery, Redis or separate worker.
- **One GPU, one synth at a time:** a global single-flight lock covers segment, preview and batch generation.

## 3. Technology stack

| Area | Choice |
|---|---|
| Backend | FastAPI (native SSE via `fastapi.sse.EventSourceResponse`), SQLModel, SQLite (WAL, `busy_timeout=5000`), `httpx`, `uv`, `ruff` |
| LLM | OpenRouter via raw `httpx`; `OPENROUTER_MODEL` (default `x-ai/grok-4.3`); temperature 0.2; strict JSON-schema output |
| EPUB | `ebooklib` + `beautifulsoup4` + `lxml` |
| TTS | `qwen-tts` on `transformers`, `sdpa` attention, PyTorch ROCm build for `gfx1201` (RX 9070 XT, 16 GB) |
| Audio join | system `ffmpeg`, concat demuxer, explicit argv (no shell) |
| Frontend | React 19, Vite 8, TypeScript 6, Tailwind 4, shadcn-style `ui/` components, `@tanstack/react-table` in `SegmentTable` |
| Deploy | Podman rootful + Quadlet (`deploy/*.container`, `qwen-ebook.pod`) |

## 4. Repository layout

```
qwen-ebook/
├── backend/
│   ├── app/                     CPU-side FastAPI service
│   │   ├── main.py              all routes, regenerate_segment(), lifespan
│   │   ├── analysis_worker.py   run_analysis(), chunking, retry/coverage gate, persistence
│   │   ├── analysis_client.py   OpenRouter call, system prompt, continuity block
│   │   ├── generation_worker.py global lock, batch loop, join, SSE queues
│   │   ├── tts_client.py        synthesize / cancel / load_model / tts_health
│   │   ├── audio_join.py        ffmpeg concat + CODEC_TABLE
│   │   ├── epub_parser.py       EPUB -> plain text
│   │   ├── chunking.py          paragraph/sentence chunker
│   │   ├── cache_key.py         SHA-256 content-hash cache key
│   │   ├── voices.py            6 fixed presets, instruction merge
│   │   ├── models.py            Project / Character / Segment tables
│   │   ├── schemas.py           CastAnalysisResult (LLM + DB + API contract)
│   │   ├── config.py            env-driven Settings
│   │   └── db.py                engine, WAL pragmas, additive column migrator
│   ├── tts_service/             GPU-side FastAPI service
│   │   ├── server.py            /synthesize /cancel /model/{id}/load /healthz, keepalive
│   │   └── model.py             model swap, cancel via StoppingCriteria, WAV encode
│   ├── Containerfile.backend    multi-stage: builds frontend, serves dist as static
│   └── Containerfile.tts
├── frontend/src/
│   ├── App.tsx                  screen router
│   ├── api/client.ts            typed fetch wrappers
│   ├── hooks/                   SSE + generation hooks
│   └── components/              screens, table, config panel, cast wizard
├── deploy/                      Quadlet units, run-local.sh, bootstrap-vm.sh
└── docs/                        API, CONFIGURATION, DEVELOPMENT, TESTING, this spec
```

## 5. Data model

```
┌──────────────────────────┐ 1      * ┌───────────────────────────┐
│ Project                  │──────────▶│ Character                 │
│ id (PK, str)             │           │ id (PK)                   │
│ filename                 │           │ project_id (FK)           │
│ source_text              │           │ name                      │
│ status: analyzing|ready| │           │ description               │
│         error            │           │ is_narrator               │
│ error_detail             │           │ voice_preset (1 of 6)     │
│ created_at               │           │ voice_instructions        │
│ output_path              │           │ preview_audio_path        │
│ tts_model: 1.7b | 0.6b   │           │ voice_version (int)       │
│ output_format: flac|mp3| │           └─────────────┬─────────────┘
│                opus      │                         │ 1
│ output_filename          │                         │
└────────────┬─────────────┘                         │ *
             │ 1                       ┌─────────────▼─────────────┐
             │                         │ Segment                   │
             └────────────────────────▶│ id (PK)                   │
                          *            │ project_id (FK)           │
                                       │ order                     │
                                       │ character_id (FK)         │
                                       │ text                      │
                                       │ voice_instructions        │
                                       │ generation_status:        │
                                       │   pending|generating|     │
                                       │   complete|error          │
                                       │ generation_error          │
                                       │ audio_path                │
                                       │ cache_key                 │
                                       │ generation_version (int)  │
                                       └───────────────────────────┘
```

- Audio is referenced by path and never stored as blobs.
- `voice_version` and `generation_version` implement last-request-wins: async writers (previews, regeneration) only write results back if the version they started with is still current.
- `db.py` migrates additively: `create_all()` plus idempotent `ALTER TABLE ADD COLUMN`. There is no Alembic.
- The frontend also knows a `queued` status; the backend model does not persist it.

### Shared LLM contract (`schemas.py`)

```
CastAnalysisResult
├── characters: [CharacterSuggestion]   name, voice_preset (Literal of 6 ids),
│                                       description (voice traits only), is_narrator
└── segments:   [SegmentSuggestion]     order, character_name, text,
                                        voice_instructions (delivery only)
```

The same schema is the OpenRouter `json_schema`, the persistence input (`model_dump()`), and the shape of `GET /projects/{id}`.

## 6. Voice presets (`voices.py`)

Six fixed personas; each maps to a Qwen CustomVoice speaker. This mapping is best-effort timbre matching, not vendor metadata.

| Preset id | Qwen speaker |
|---|---|
| `narrator_sultry_woman` (default and narrator fallback) | `serena` |
| `middle_sultry_woman` | `vivian` |
| `playful_student` | `sohee` |
| `bright_young_guy` | `ryan` |
| `reassuring_young_man` | `aiden` |
| `gruff_older_man` | `uncle_fu` |

The `instruct` string sent to TTS is `merge_instructions(character.voice_instructions, segment.voice_instructions)`, joined with `". "` and skipping empty parts. Unknown or empty presets resolve to the default speaker. `best_guess_preset()` does a keyword match against a description as a fallback.

## 7. Core pipelines

### 7.1 Upload and analysis

```
 Browser                Backend                                   OpenRouter
   │  POST /projects (file)  │                                        │
   ├────────────────────────▶│ bounded read (413 if > MAX_UPLOAD_BYTES)
   │                         │ .epub -> epub_parser.extract_text()
   │                         │ .txt  -> UTF-8 decode
   │                         │ INSERT Project(status=analyzing)
   │  201 {id}               │ spawn asyncio task run_analysis()
   │◀────────────────────────┤
   │  GET /analysis-stream   │
   ├────────────────────────▶│  (SSE: progress|done|error)
   │                         │ estimate_tokens = len/4
   │                         │ ── ≤ ANALYSIS_TOKEN_LIMIT (6000 tok ≈ 24k chars)
   │                         │      one analyze() call ─────────────────▶│
   │                         │ ── >  limit: chunk_paragraphs(800) grouped
   │                         │      to budget; per group analyze() with
   │                         │      running_cast + last 20 segments ────▶│
   │                         │ retry ≤3× on ValidationError / HTTPError /
   │                         │ coverage < 85% of source chars
   │                         │ _persist_result -> Character + Segment rows
   │                         │ Project.status = ready
   │  event: done            │
   │◀────────────────────────┤   on failure: status=error, error_detail
```

Prompt-level rules (`CAST_ANALYSIS_SYSTEM_PROMPT`):

- Every word of the input must survive verbatim into segments. Dialogue tags and action beats stay as their own narrator segments.
- One speaker per segment.
- `voice_instructions` are delivery only, and empty for most narration.
- Book text goes in the user message and never in the system message (prompt-injection mitigation).
- Continuity context is reference only, followed by the marker `=== TEXT TO CONVERT ===`. Existing character names are reused.

EPUB parsing (`epub_parser.py`):

- Spine reading order.
- Footnote and endnote stripping.
- Non-narrative sections skipped by heuristics, minimum 200 narrative chars.
- Zip-bomb guard (decompression ratio ≤ 100).
- Chapter boundaries preserved as blank lines.

### 7.2 Review and editing

- Cast edits: `PATCH /characters/{id}`, merge (`POST .../merge` returns an undo snapshot), and stateless `POST /characters/undo-merge`.
- Segment edits: `PATCH /segments/{id}` (character, text, instructions) and `POST /segments/bulk-reassign`.
- Any voice-affecting edit bumps a version counter and resets the affected segment or preview to `pending`. It does not auto-generate.
- Every edit persists immediately; there is no separate save step.

### 7.3 Single-segment generation and caching

```
regenerate_segment(segment_id, version)
  speaker  = preset_speaker(character.voice_preset)   (or best_guess_preset fallback)
  instruct = merge_instructions(character.voice_instructions, segment.voice_instructions)
  key      = SHA256(speaker ␟ instruct ␟ text ␟ Project.tts_model)   (recomputed live)
  ├─ key == stored cache_key and audio file exists -> cache hit, no TTS call
  └─ miss -> tts_client.synthesize() -> write WAV -> status=complete
             (write back only if generation_version still matches)
```

The cache key covers only voice-affecting inputs, so nothing else needs an invalidation path. Editing text, instructions or preset, or swapping the model, changes the key.

### 7.4 Batch generation and join

```
POST /projects/{id}/generate  (202)          409 if the global lock is held
  └─ task: run_batch_generation
       reset stale "generating" rows -> "pending"   (crash resume)
       for each segment in order:
           stop requested? -> return           (checked at loop top)
           mark generating, push SSE {segment_id, n, total, status}
           regenerate_segment()                (cache hit skips synthesis)
           one failure -> status=error, loop continues
       _join_project(): ffmpeg concat of all complete segments
           -> re-encode per CODEC_TABLE[output_format]
           -> Project.output_path (uuid4 filename on disk)
       push SSE done | error
GET /projects/{id}/download   -> served under output_filename (sanitized), 409 if no output
```

`CODEC_TABLE`:

| Format | Codec | Content type |
|---|---|---|
| flac | `flac`, level 8 | `audio/flac` |
| mp3 | `libmp3lame` | `audio/mpeg` |
| opus | `libopus`, 48k, VBR, voip, Ogg container | `audio/ogg` |

An unknown format raises; there is no fallback.

### 7.5 Cancellation

```
Stop clicked ─▶ POST .../generate/cancel
                 ├─ generation_worker.request_stop(label)
                 ├─ tts_client.cancel() ─▶ TTS /cancel ─▶ _cancel_event.set()
                 │       decode loop's StoppingCriteria sees it next step
                 │       ─▶ GenerationCancelled ─▶ HTTP 499
                 └─ await the running task (never task.cancel())
                    ─▶ segment row reset, terminal SSE pushed, lock released
```

The lock is released only by the task's done-callback, never by a cancel handler. `delete_project` is the one place that uses a raw `task.cancel()`.

### 7.6 Global single-flight lock

`try_claim_generation(label)` claims a module-level slot atomically. There is no `await` between the check and the set, so it is safe under asyncio. Labels are `segment:{id}`, `preview:{id}` and `batch:{id}`. A busy lock yields HTTP 409 for user actions and a silent skip for best-effort background regeneration. `GET /generation-status` exposes `{"active": bool}` so the UI can disable controls app-wide.

### 7.7 TTS model swap

`POST /projects/{id}/model {model_id}` is allowlist-validated (`1.7b` or `0.6b`). It calls the TTS service's `/model/{id}/load`. Only one checkpoint is resident in VRAM: the old one is deleted after the new one loads. On failure the old model stays resident, the project row is untouched, and the UI reverts. On success `Project.tts_model` changes, so all cache keys change, and cached audio and previews are invalidated.

## 8. API surface

Backend (public to the tailnet):

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | 200 if the TTS backend is reachable, else 503 |
| POST | `/projects` | Upload and start analysis (201) |
| GET | `/projects` | List summaries, newest first |
| GET | `/projects/{id}` | Full project with characters and segments |
| PATCH | `/projects/{id}` | Set `output_format`, `output_filename` |
| DELETE | `/projects/{id}` | Delete project and audio (204) |
| GET | `/projects/{id}/download` | Joined audio file |
| GET | `/projects/{id}/analysis-stream` | SSE: `progress` / `done` / `error` |
| GET | `/projects/{id}/generation-stream` | SSE: `progress` / `done` / `error` |
| POST | `/projects/{id}/generate` | Start or resume batch (202) |
| POST | `/projects/{id}/generate/cancel` | Cancel batch |
| POST | `/projects/{id}/model` | Swap TTS model |
| GET | `/voices` | Preset list (id and label) |
| GET | `/generation-status` | Global lock state |
| PATCH | `/characters/{id}` | Edit name, description, preset, instructions |
| POST | `/characters/{id}/preview` | Generate voice preview |
| POST | `/characters/{id}/preview/cancel` | Cancel preview |
| GET | `/characters/{id}/preview.wav` | Preview audio |
| POST | `/characters/{id}/merge` | Merge into another character |
| POST | `/characters/undo-merge` | Undo a merge from its snapshot |
| PATCH | `/segments/{id}` | Edit character, text, instructions |
| POST | `/segments/{id}/generate` | Render one segment (202) |
| POST | `/segments/{id}/generate/cancel` | Cancel it |
| GET | `/segments/{id}/audio.wav` | Segment audio |
| POST | `/segments/bulk-reassign` | Reassign many segments |

SSE payloads:

- Analysis progress: `{stage: "estimating" | "analyzing" | "chunk", n?, total?}`
- Generation progress: `{segment_id, n, total, status}`
- Terminal events: `done {status: "ready"}` or `error {detail}`

TTS service (pod-internal, port 8001, never published):

| Method | Path | Behavior |
|---|---|---|
| POST | `/synthesize` | `{text, speaker?, instruct?}` returns `audio/wav`. 400 bad speaker or oversize text, 422 empty, 499 cancelled, 503 not ready |
| POST | `/model/{id}/load` | Swap checkpoint. 422 unknown id, 500 failed |
| POST | `/cancel` | Sets the cancel event (202) |
| GET | `/healthz` | 200 only when a model is resident |

The TTS service runs a periodic keepalive matmul (`GPU_KEEPALIVE_INTERVAL`, default 15 s) to avoid ROCm idle-downclock latency spikes. `MAX_TEXT_LENGTH` is 4000 chars; the backend pre-chunks well below that.

## 9. Frontend

Screen state machine (`App.tsx`). The active project id is persisted in `localStorage` (`qwen-ebook:projectId`); the landing view is in-memory only.

```
        ┌──────────────┐  New Project   ┌───────────────┐
        │ ProjectList  │───────────────▶│ UploadScreen  │
        │ (landing)    │◀───────────────│               │
        └──────┬───────┘                └───────┬───────┘
               │ open project                   │ POST /projects
               ▼                                ▼
        ┌───────────────────────────────────────────────┐
        │ useAnalysisStream(projectId)                  │
        ├── status=analyzing ─▶ AnalyzingScreen (progress bar + skeletons)
        ├── status=error     ─▶ ErrorScreen (upload another)
        └── status=ready ─▶ header [← Projects] [Review cast →]
                         ├─ ProjectScreen   (default)
                         └─ CastWizard      (toggle)
        └───────────────────────────────────────────────┘
```

`ProjectScreen` layout (about 70/30 split on `xl`, stacked below):

```
┌───────────────────────────────────────────────────────────────────────────┐
│ ← Projects                                          Review cast →         │
│ my-book.epub                                                              │
├──────────────────────────────────────────────┬────────────────────────────┤
│ SegmentTable (~70%)                          │ ConfigPanel (~30%)         │
│ ┌────┬──────────┬───────────────┬────┬────┐  │ Config                     │
│ │ #  │ Narrator │ Text          │Instr│ ▶ │  │  Input File: my-book.epub  │
│ ├────┼──────────┼───────────────┼────┼────┤  │  TTS model:  [1.7B ▾]      │
│ │ 1  │[Narr. ▾] │ editable text │ …  │ ▶  │  │  Format:     [mp3 ▾]       │
│ │ 2  │[Anna ▾]  │ editable text │ …  │ ▶  │  │  Filename:   [ ______ ]    │
│ │ 3  │[Narr. ▾] │ …             │    │ ⟳  │  │ Characters                 │
│ └────┴──────────┴───────────────┴────┴────┘  │  ▸ CharacterCard × N       │
│ [bulk: select rows] [Reassign to… ▾] [Apply] │    (preset, instructions,  │
│ per-row status badge: pending / generating / │     preview play/pause)    │
│ complete / error                             │ Generation                 │
│                                              │  [Generate All / Stop]     │
│                                              │  ▓▓▓▓▓░░░░░ n / total      │
│                                              │  [Download]                │
└──────────────────────────────────────────────┴────────────────────────────┘
```

Behavior:

- Row buttons use `GenerateStopPlayButton` via `useGenerateStopPlay`: the first click generates, then it becomes play/pause, and it can stop an in-flight render.
- `useGenerationStream` overlays live SSE statuses on the table only while a run is `running`. Afterwards the refetched project is the source of truth.
- `useGenerationLock` polls `/generation-status`, and all generate controls disable while any generation is active.
- `CastWizard` is the cast-review flow: name, description and preset per character, merge, and undo merge.
- `refetch()` failures keep the last loaded data and show an error banner.

## 10. Configuration (env vars, `config.py`)

| Variable | Default | Meaning |
|---|---|---|
| `TTS_SERVICE_URL` | `http://localhost:8001` | GPU container endpoint |
| `OPENROUTER_API_KEY` | empty | Required for analysis |
| `OPENROUTER_MODEL` | `x-ai/grok-4.3` | Any OpenRouter model |
| `ANALYSIS_TOKEN_LIMIT` | 6000 | Per-call analysis budget (about 24k chars) |
| `CHUNK_TARGET_LEN` | 800 | Chunker target chars |
| `MAX_UPLOAD_BYTES` | 10 MiB | Upload cap |
| `UPLOAD_DIR` / `OUTPUT_DIR` / `PREVIEW_DIR` / `STATIC_DIR` | under `backend/` | Storage paths |
| `DATABASE_URL` | `sqlite:///backend/projects.db` | SQLite file |
| `LOG_LEVEL` | `INFO` | Root logging level |
| `GPU_KEEPALIVE_INTERVAL` (TTS) | 15 | Seconds between keepalive matmuls (≤0 disables) |

`TTS_DEFAULT_SPEAKER` is also read by config, but the app resolves speakers from presets.

## 11. Deployment

- Rootful Podman with Quadlets: `qwen-ebook.pod`, `qwen-ebook-backend.container`, `qwen-ebook-tts.container`.
- The TTS container gets `/dev/kfd` and `/dev/dri` and runs as root inside the container. A named volume caches the Hugging Face model download.
- The pod publishes only `127.0.0.1:8000`. Port 8001 stays pod-internal.
- `tailscale serve` exposes the backend to the tailnet.
- The pod uses `--exit-policy=continue` so a single member restart doesn't tear the pod down. The TTS container uses `Restart=on-failure`.
- `deploy/run-local.sh` is the non-Quadlet equivalent. `deploy/bootstrap-vm.sh` prepares the VM.

## 12. Error handling and invariants

1. Analysis failure: `Project.status="error"` plus `error_detail`, pushed over SSE as `error`.
2. Content-loss gate: results covering under 85% of source chars are retried up to three times, then fail loudly.
3. One segment failure never aborts a batch. The row becomes `error` with `generation_error`.
4. A crashed batch is resumable. Stale `generating` rows reset to `pending`, and cache hits skip finished work.
5. Model swap failure reverts to the resident model. The UI re-reads server state.
6. Output filenames on disk are server-generated uuid4 names. The user-facing download name is sanitized.
7. `httpx`/`httpcore` logging is pinned to WARNING so DEBUG mode can't leak the OpenRouter bearer token.

## 13. Project conventions (from `CLAUDE.md`)

- Run `cd backend && uv run ruff check .` after major Python changes (rules `E, F, I, UP, B`), with no outstanding warnings.
- No `# noqa` in non-test code unless framework-required, and always with a why-comment.
- Use `logging`, never `print()`, and log extensively.
- Use f-strings everywhere, including inside logging calls.
- Podman only (no Docker), no task queue, no vLLM, no `flash-attn`, no voice cloning path.

## 14. Known limitations

- No mock or offline mode. Development and tests run against real OpenRouter and the real TTS container.
- The speaker-to-persona mapping is heuristic and needs re-tuning by ear.
- Migrations are additive only. Column renames or drops would need Alembic.
- The generation lock is global and in-process, so it is not safe across multiple backend replicas. That is by design for a single-user tool.
- Segments are rendered strictly sequentially, with no GPU batching.
