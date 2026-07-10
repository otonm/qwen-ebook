# Phase 2: LLM Cast Detection & Review Wizard - Research

**Researched:** 2026-07-10
**Domain:** LLM structured-output cast/segment extraction (xAI Grok), EPUB parsing, SSE background-task progress push, React cast-review UI with eager audio preview
**Confidence:** MEDIUM-HIGH (HIGH on xai-sdk API shape and FastAPI SSE — both verified against official/primary sources; MEDIUM on ebooklib spine-resolution and BeautifulSoup footnote-detection specifics — training-knowledge-grounded, partially confirmed by docs; MEDIUM on cross-chunk reconciliation quality, per STATE.md's carried-forward risk note, unchanged by this research pass)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Persistence**
- D-01: Introduce real SQLModel/SQLite persistence in this phase (not in-memory/throwaway state) — one `projects.db` with `Project`, `Character`, `Segment` tables per STACK.md's plan. Phase 3 (PERS-01/02) extends this schema rather than replacing a Phase-2-only stopgap.
- D-02: Schema covers only what Phase 2's wizard needs: `Project` (source text, filename, analysis status), `Character` (name, description, voice preset/instructions, preview audio path), `Segment` (order, character, text, voice instructions). No Phase 3 fields (generation status, content-hash cache key, audio cache path) added speculatively.
- D-03: Cast/segment analysis runs as a background asyncio task, not a blocking request. Upload creates the `Project` row immediately (status: analyzing) and returns; a background task runs the Grok call(s) and pushes progress via SSE (`fastapi.sse.EventSourceResponse`, same mechanism STACK.md already planned for TTS progress).
- D-04: Add an `LLM_BACKEND=mock` env flag mirroring Phase 1's `TTS_BACKEND=mock` pattern — returns canned cast/segment JSON so dev/tests don't hit the real Grok API or incur cost. Gate the real `xai-sdk` import behind this flag, same as `qwen-tts`.

**Chunking & Cross-Chunk Cast Reconciliation**
- D-05: Prefer single-shot analysis: estimate the text's token count and, if it fits within a safety margin, send the whole text to Grok in one call — no chunking, no cross-chunk reconciliation needed for the common case.
- D-06: Safety margin is ~50% of the context window reserved for input text; the remaining ~50% is headroom for the cast+segment JSON output plus the model's own reasoning space. Concretely: text estimated over ~500K tokens triggers the multi-chunk fallback path.
- D-07: Multi-chunk fallback (oversized texts only) reuses Phase 1's paragraph-chunker as the base unit, grouped up to a per-call size under the same budget logic. Each subsequent chunk's Grok call is given: (a) the full running resolved cast list (name + description), and (b) the last 20 segments already resolved ([character]/text pairs) for narrative continuity context.
- D-08: The LLM is prompted to auto-resolve confident character matches across chunks rather than always emitting a new character entry. The wizard's merge tool (WIZ-02) remains the safety net for cases the LLM gets wrong.

**EPUB Parsing (ING-02)**
- D-09: Use `ebooklib` + `beautifulsoup4` (lxml parser, `recover=True`) per STACK.md. Extract text per spine item in reading order.
- D-10: Apply a heuristic skip of obvious non-narrative spine items (cover, TOC, copyright/title page, index) using simple signals: very short extracted text, filename/id hints, and EPUB3 nav landmarks where present. Best-effort filter, not a guarantee.
- D-11: Strip footnote/endnote markers and their linked note text entirely during extraction (detect `epub:type="noteref"`/`"footnote"` and common id/href-to-endnote patterns).
- D-12: Preserve EPUB chapter boundaries (spine item breaks) as first-class structure — extract per-chapter, keep chapter breaks as natural analysis/chunk boundaries.
- D-13: If a specific chapter fails to parse even with `recover=True`, reject the whole upload with a clear error (do not silently skip the broken chapter and proceed with a partial book).

**Wizard Flow & Voice Preview UX**
- D-14: Single-page cast list UI — all detected characters visible at once as cards/rows with inline rename/merge/edit/voice-assign, not a step-by-step next/back wizard.
- D-15: Include a read-only segment preview (speaker + text, no inline edit/dropdowns/bulk actions) alongside the cast wizard in this phase's UI.
- D-16: Pre-fill each character's free-text voice instructions from the LLM's own inferred description as an editable starting default, plus a best-guess preset pick.
- D-17: VoiceDesign (custom voice generation) is explicitly deferred out of this phase. Phase 2 ships CustomVoice preset + free-text instruction-steering only.

### Claude's Discretion
- Exact background-task/SSE wiring shape (task registry, endpoint naming, event payload schema) beyond "background task + SSE progress" being the chosen pattern.
- Precise token-estimation method for the single-shot-vs-chunk decision (e.g. `tiktoken`-style estimate vs. a simpler chars/4 heuristic) — must respect the ~50%-of-context input budget from D-06.
- Exact heuristic thresholds for EPUB non-narrative-section skipping (D-10) and footnote pattern detection (D-11) — pick sensible defaults, document the heuristic's known limits inline.
- Voice-preview generation trigger wiring (WIZ-05: "as soon as a character's voice is assigned") — exact eager-generation mechanism, reusing Phase 1's `tts_client.synthesize()`.
- Internal `Character`/`Segment` SQLModel field naming and exact API request/response shapes.

### Deferred Ideas (OUT OF SCOPE)
- VoiceDesign (custom voice generation for characters with no good preset match) — explicitly deferred past Phase 2 (D-17); revisit only if CustomVoice + instruction-steering proves insufficient.
- Phase 3's full editable segment table (TBL-01..04: inline edit, bulk reassign, per-row on-demand generate/preview) — out of this phase's boundary; Phase 2 only ships a read-only segment preview (D-15).
- Phase 3's generation-status/content-hash caching fields (GEN-02, GEN-05) — not added to the schema speculatively (D-02); Phase 3 owns that design.
</user_constraints>

## Summary

This phase has 17 decisions already locked in CONTEXT.md (D-01..D-17). The open surface for planning is entirely implementation-shape: how `xai-sdk`'s `AsyncClient` actually produces schema-guaranteed cast+segment JSON, how FastAPI's native SSE module actually looks in code, how `ebooklib`+`BeautifulSoup` resolve spine reading order and strip footnotes, and how the single-page wizard wires "assign voice -> auto-generate preview -> instant playback" against Phase 1's existing `tts_client.synthesize()`.

The critical finding: `xai-sdk`'s structured-output pattern is `chat = client.chat.create(model=..., messages=[system(...)])`, then `chat.append(user(...))`, then `response, parsed = await chat.parse(YourPydanticModel)` — confirmed verbatim from the SDK's own `examples/aio/structured_outputs.py`. This is a single shared Pydantic schema (one `CastAnalysisResult` model with `characters: list[CharacterSuggestion]` and `segments: list[SegmentSuggestion]`) reused as the Grok response contract, the SQLModel persistence shape (via `.model_dump()`), and the FastAPI response model — exactly as STACK.md anticipated. `grok-4.3`'s context window is confirmed 1M tokens at $1.25/$2.50 per 1M tokens (input/output) via official `docs.x.ai/developers/models` — the D-06 "~500K tokens triggers chunking" threshold leaves genuine headroom under that ceiling.

FastAPI's native `fastapi.sse.EventSourceResponse` (added ~0.135, this project pins 0.139.0) is a generator-based response: an `async def` path function annotated `-> AsyncIterable[YourPydanticModel]` (or `AsyncIterable[ServerSentEvent]` for full control over `event`/`id`/`retry`), registered via `response_class=EventSourceResponse`. No existing SSE code exists yet in this repo (`backend/app/main.py` currently only has a blocking `/projects` POST and `/healthz`) — this phase is the first real use of that pattern, not a refactor of prior art.

**Primary recommendation:** Reuse Phase 1's established patterns (frozen-dataclass `Settings`, `TTS_BACKEND`-style mock gating, `run_in_threadpool` for blocking calls, UUID-based server filenames) for every new piece — `LLM_BACKEND=mock`, a `analysis_client.py` module mirroring `tts_client.py`'s shape, and an in-process `asyncio.create_task` background worker (no new task-queue dependency, matching STACK.md's explicit "no Celery/Redis" call). The one genuinely new piece of machinery is the SSE progress channel and the first real SQLModel schema — both should be kept as small as D-02 already scopes them.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| EPUB/text upload + parsing | API/Backend | — | `ebooklib`/BeautifulSoup only make sense server-side; browser has no EPUB parser |
| Grok cast/segment analysis | API/Backend | — | `xai-sdk` API key must never reach the browser; single backend process owns the call per STACK.md |
| Cast/segment persistence | Database/Storage | API/Backend | SQLite `projects.db` is the source of truth; FastAPI/SQLModel is the only writer (single process, no concurrent-writer contention to design for) |
| Analysis progress push | API/Backend | Browser/Client | Backend owns the SSE stream (`EventSourceResponse`); browser only consumes via `EventSource`/`fetch` |
| Cast review UI (rename/merge/edit/voice-assign) | Browser/Client | API/Backend | All interactive editing state lives in React; every mutation round-trips to a backend endpoint that writes SQLite (no client-only draft state that could diverge from persistence) |
| Voice preview generation (eager, on assign) | API/Backend | — | Reuses `tts_client.synthesize()` — TTS inference must stay server-side per DEPL-01's GPU/CPU container isolation boundary; browser only gets back an audio URL/path to play |
| Voice preview playback | Browser/Client | — | Native HTML5 `<audio>` element — no library needed (see Don't Hand-Roll) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `xai-sdk` | 1.17.0 (PyPI, released 2026-06-12) | Grok API client, structured-output cast/segment extraction | Official xAI Python SDK; `AsyncClient.chat.create(...).parse(PydanticModel)` gives schema-guaranteed JSON — no manual JSON-repair/retry loop needed |
| `sqlmodel` | 0.0.39 (PyPI, released 2026-06-25) | `Project`/`Character`/`Segment` persistence | One dependency = SQLAlchemy 2.x ORM + Pydantic validation; shares the same Pydantic base as the Grok response schema and FastAPI response models (D-01/D-02) |
| `ebooklib` | 0.20 (PyPI, released 2025-10-26) | EPUB parsing (ING-02) | Standard, only actively-maintained pure-Python EPUB2/3 reader; reads spine/manifest/nav without a system dependency (unlike Calibre's `ebook-convert`) |
| `beautifulsoup4` | 4.15.0 (PyPI, released 2026-06-07) | XHTML -> clean text extraction per chapter | Standard HTML/XML text-extraction library; paired with `lxml` for resilience against malformed EPUB markup |
| `lxml` | 6.1.1 (PyPI, released 2026-05-18) | Parser backend for BeautifulSoup, `recover=True` | Only common Python XML/HTML parser with a documented `recover=True` "best-effort fix broken markup" mode — required by D-13's fail-fast-but-still-try-hard policy |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| React | 19.2.7 (npm) | Wizard UI framework | Already the locked stack choice (STACK.md); first real frontend code in this phase |
| Vite | 8.1.4 (npm) | Frontend build tool/dev server | Companion to React per STACK.md; `npm create vite@latest frontend -- --template react-ts` |
| `@tanstack/react-table` | 8.21.3 (npm) | Read-only segment preview table (D-15) | Headless table engine; only the read-only rendering surface is needed this phase (full editable table is Phase 3/TBL-01..04) |
| `tailwindcss` | 4.3.2 (npm) | Styling | Locked stack choice; v4 uses the new `@tailwindcss/vite` plugin, not the old `tailwind.config.js` PostCSS pipeline |
| shadcn/ui (copy-in components, no version pin — CLI-generated) | — | Card/row layout, buttons, inline-edit inputs | Radix-based, copy-into-repo (not an npm black-box dependency) — install via `npx shadcn@latest init` then `add` individual components as needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| chars/4 token estimate | `tiktoken`-equivalent tokenizer | No official Grok tokenizer exists to call locally; `tiktoken` would estimate OpenAI's tokenization, not Grok's — a wrong-but-precise-looking number is worse than an honest heuristic. chars/4 has ~10-28% error on English prose (see Pitfall below) but D-06's 50%-of-1M-token safety margin absorbs that error with room to spare |
| `fastapi.sse.EventSourceResponse` (native) | `sse-starlette` | Only needed if pinned FastAPI were <0.135; this project pins 0.139.0, so native support applies — no extra dependency |
| Native `<audio>` element for preview playback | `howler.js` / `wavesurfer.js` | A single play/pause of a short pre-generated clip needs no waveform rendering or cross-browser audio-engine abstraction; native `<audio>` + `HTMLAudioElement.play()/.pause()` is sufficient (WIZ-04) |

**Installation:**
```bash
# Backend (extends backend/pyproject.toml dependencies)
uv add xai-sdk sqlmodel ebooklib beautifulsoup4 lxml

# Frontend (first real frontend scaffolding — frontend/ currently only has .gitkeep)
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install @tanstack/react-table
npm install -D tailwindcss @tailwindcss/vite
npx shadcn@latest init
```

**Version verification:** All five backend package versions above were confirmed live against `pypi.org/pypi/<pkg>/json` on 2026-07-10 (not training-data guesses). Frontend versions confirmed live via `npm view <pkg> version` on the same date.

## Package Legitimacy Audit

| Package | Registry | Age (latest release) | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|----------------------|-----------|--------------|---------|-------------|
| `xai-sdk` | PyPI | ~1 month (2026-06-12) | unknown (PyPI has no public download-count API the checker used) | github.com/xai-org/xai-sdk-python | SUS | Flagged — see note below |
| `sqlmodel` | PyPI | ~2 weeks (2026-06-25) | unknown | github.com/fastapi/sqlmodel | SUS | Flagged — see note below |
| `ebooklib` | PyPI | ~9 months (2025-10-26) | unknown | github.com/aerkalov/ebooklib | SUS | Flagged — see note below |
| `beautifulsoup4` | PyPI | ~1 month (2026-06-07) | unknown | crummy.com/software/BeautifulSoup | SUS | Flagged — see note below |
| `lxml` | PyPI | ~2 months (2026-05-18) | unknown | github.com/lxml/lxml | SUS | Flagged — see note below |
| `@tanstack/react-table` | npm | — | 14.9M/wk | github.com/TanStack/table | OK | Approved |
| `tailwindcss` | npm | 11 days (2026-06-29) | 123.8M/wk | github.com/tailwindlabs/tailwindcss | SUS ("too-new") | Approved with note — see below |
| `react` / `react-dom` | npm | — | 146M/wk, 138M/wk | github.com/facebook/react | OK | Approved |
| `vite` | npm | ~1 day (2026-07-09) | 152.6M/wk | github.com/vitejs/vite | SUS ("too-new") | Approved with note — see below |

**Note on the PyPI SUS batch:** The `package-legitimacy check` seam has no PyPI download-count signal available (it returns `weeklyDownloads: null` for every PyPI package regardless of maturity, triggering an automatic "unknown-downloads" SUS reason), and its "too-new" heuristic reads *latest release date*, not *package age* — so an actively-maintained, long-established project that shipped a routine release last month gets flagged identically to a genuinely new package. All five are well-established: `beautifulsoup4`/`lxml` are 15+ year old, ecosystem-standard libraries; `sqlmodel` is maintained by the FastAPI creator (`tiangolo`) under the `fastapi` GitHub org; `ebooklib` has been the de facto pure-Python EPUB library since 2013; `xai-sdk` is xAI's own official SDK published under `xai-org`. Per protocol, these are still tagged `[SUS]` and the planner **must** insert a `checkpoint:human-verify` before each `uv add` — but this is process compliance, not a genuine slopsquat signal. `tailwindcss`/`vite` are the same "too-new" false-positive pattern (both are top-tier, 100M+/week npm packages with a release in the last two weeks) — no checkpoint needed for these, downloads volume alone rules out slopsquatting.

**Packages removed due to `[SLOP]` verdict:** none.
**Packages flagged as suspicious `[SUS]`:** `xai-sdk`, `sqlmodel`, `ebooklib`, `beautifulsoup4`, `lxml` (PyPI download-count tooling gap, not a real risk signal — see note above). The planner should still add one `checkpoint:human-verify` task before the `uv add` step as a formality, given the protocol's hard requirement, but should not block on it beyond a quick "yes, this is the real `sqlmodel`/`xai-sdk`" confirmation.

## Architecture Patterns

### System Architecture Diagram

```
Browser (React wizard)
   |
   | 1. POST /projects (multipart: .txt or .epub file)
   v
FastAPI backend (Project created, status=analyzing, HTTP 201 returned immediately)
   |
   | 2. asyncio.create_task() spawns background analysis worker
   |    (request handler returns; does NOT block on Grok)
   v
Background task:
   EPUB path: ebooklib -> spine walk -> BeautifulSoup+lxml per chapter
              -> strip footnotes/skip non-narrative items -> plain text
   TXT path:  reuse existing decode (Phase 1)
   |
   | 3. estimate_tokens(text) -- chars/4 heuristic
   v
   text_tokens <= ~500K? --[yes]--> single Grok call (full text)
        |
        [no]
        v
   chunk_paragraphs() (Phase 1 chunker, grouped to per-call budget)
   -> sequential Grok calls, each given: running cast list + last 20
      resolved segments (D-07), reconciling matches into existing
      characters (D-08)
   |
   | 4. each Grok call: xai-sdk AsyncClient.chat.create(...).parse(CastAnalysisResult)
   v
   SQLModel writes: Character rows (upsert/merge into running cast),
                     Segment rows (ordered, character_id FK, voice_instructions)
   |
   | 5. progress events pushed via SSE as each chunk/step completes
   v
Browser (EventSource on /projects/{id}/analysis-stream)
   -> cast list + segment preview render as data arrives
   |
   | 6. user renames/merges/edits characters, assigns voice (preset or
   |    free-text instructions) via PATCH /characters/{id}
   v
FastAPI: on voice assignment, eagerly calls tts_client.synthesize()
   (run_in_threadpool, reusing Phase 1's client) -> writes preview WAV
   -> Character.preview_audio_path updated
   |
   | 7. browser polls/receives updated character, <audio src=...> now
   |    resolves; play/pause is instant (WIZ-05)
   v
Browser: play/pause preview via native <audio> element
```

### Recommended Project Structure
```
backend/app/
├── main.py              # existing — add /projects (new shape), /projects/{id},
│                         #   /projects/{id}/analysis-stream (SSE), /characters/{id}
├── config.py             # existing — extend Settings with LLM_BACKEND, XAI_API_KEY,
│                         #   GROK_MODEL, DATABASE_URL, ANALYSIS_TOKEN_LIMIT
├── db.py                 # NEW — SQLModel engine/session setup (check_same_thread=False)
├── models.py              # NEW — Project/Character/Segment SQLModel table classes
├── schemas.py             # NEW — CastAnalysisResult/CharacterSuggestion/SegmentSuggestion
│                         #   Pydantic schema, shared by Grok .parse() call + API responses
├── analysis_client.py     # NEW — mirrors tts_client.py's mock/real-backend-switch shape;
│                         #   wraps xai-sdk AsyncClient calls
├── analysis_worker.py     # NEW — background asyncio task: chunk-or-not decision,
│                         #   sequential Grok calls, SQLModel writes, SSE event emission
├── epub_parser.py         # NEW — ebooklib + BeautifulSoup spine walk, footnote strip,
│                         #   non-narrative-section skip heuristic
├── token_estimate.py       # NEW — chars/4 heuristic, single function
├── chunking.py            # existing — reused as-is for the oversized-text fallback
├── tts_client.py           # existing — reused as-is for voice preview generation
└── audio_join.py           # existing — untouched this phase

frontend/src/
├── main.tsx / App.tsx
├── components/
│   ├── CastWizard.tsx      # single-page cast list (D-14) — cards/rows,
│   │                       #   inline rename/merge/edit/voice-assign
│   ├── CharacterCard.tsx    # one character: name, description, voice picker,
│   │                       #   play/pause preview button
│   └── SegmentPreview.tsx   # read-only segment list (D-15) — TanStack Table,
│                           #   no inline edit/dropdowns
├── hooks/
│   └── useAnalysisStream.ts # EventSource wrapper -> React state
└── api/
    └── client.ts            # fetch wrappers for /projects, /characters endpoints
```

### Pattern 1: xai-sdk structured output (verified against official example)
**What:** Use `chat.parse(PydanticModel)` to get a schema-guaranteed parsed object back from Grok in one call, no manual JSON parsing/retry loop.
**When to use:** Every cast/segment analysis call (single-shot or per-chunk).
**Example:**
```python
# Source: github.com/xai-org/xai-sdk-python examples/aio/structured_outputs.py
# (verified via WebFetch of the raw file, 2026-07-10)
from xai_sdk import AsyncClient
from xai_sdk.chat import system, user

client = AsyncClient(api_key=settings.XAI_API_KEY)

chat = client.chat.create(
    model=settings.GROK_MODEL,  # "grok-4.3" — 1M context, $1.25/$2.50 per 1M tok
    messages=[system(CAST_ANALYSIS_SYSTEM_PROMPT)],
)
chat.append(user(full_text_or_chunk))

# .parse() blocks streaming (a documented xai-sdk limitation) but that's
# fine here — this app needs the complete cast+segment JSON, not a
# progressive stream of it.
response, result = await chat.parse(CastAnalysisResult)
# result: CastAnalysisResult (your Pydantic model) — schema-guaranteed
```

### Pattern 2: FastAPI native SSE for analysis progress (verified against official docs)
**What:** `fastapi.sse.EventSourceResponse` streams progress events from the background analysis task to the browser.
**When to use:** `/projects/{id}/analysis-stream` endpoint.
**Example:**
```python
# Source: fastapi.tiangolo.com/tutorial/server-sent-events/ (verified 2026-07-10)
from collections.abc import AsyncIterable
from fastapi.sse import EventSourceResponse, ServerSentEvent

@app.get("/projects/{project_id}/analysis-stream", response_class=EventSourceResponse)
async def analysis_stream(project_id: str) -> AsyncIterable[ServerSentEvent]:
    async for event in analysis_progress_events(project_id):
        # event: {"stage": "chunk_2_of_5", "characters_found": 4, ...}
        yield ServerSentEvent(data=event, event="progress")
    yield ServerSentEvent(data={"status": "complete"}, event="done")
```
```javascript
// Client side — native EventSource, no library needed
const es = new EventSource(`/projects/${projectId}/analysis-stream`);
es.addEventListener("progress", (e) => setProgress(JSON.parse(e.data)));
es.addEventListener("done", () => es.close());
```
FastAPI's native implementation already handles keep-alive pings (~15s), `Cache-Control: no-cache`, and `X-Accel-Buffering: no` — no manual header wiring needed.

### Pattern 3: ebooklib spine-order traversal with item resolution
**What:** Walk the EPUB spine (its actual linear reading order) rather than iterating `get_items_of_type(ITEM_DOCUMENT)` directly — the latter is manifest order, which is not guaranteed to match reading order.
**When to use:** ING-02 EPUB text extraction, always — reading order matters for D-12's chapter-boundary-preserving extraction.
**Example:**
```python
# Source: github.com/aerkalov/ebooklib README (spine/get_items_of_type
# confirmed via WebFetch); spine tuple shape and get_item_with_id()
# resolution is well-established ebooklib usage — flagged [ASSUMED] below
# since the fetched docs excerpt didn't show this exact resolution line.
from ebooklib import epub
import ebooklib

book = epub.read_epub(path, options={"ignore_ncx": True})

# book.spine is a list of (idref, linear) tuples in reading order;
# linear == "no" marks an item excluded from the default reading order
# (common for some cover/ancillary pages) — respect it per D-10.
chapters = []
for idref, linear in book.spine:
    if linear == "no":
        continue
    item = book.get_item_with_id(idref)
    if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
        continue
    chapters.append(item)
```

### Anti-Patterns to Avoid
- **Iterating `get_items_of_type(ITEM_DOCUMENT)` directly for extraction order:** returns manifest order, not reading order — can silently scramble chapters for EPUBs where manifest and spine order differ.
- **Trusting a single global `text.split()` on the whole EPUB text for chunking:** ignores D-12's requirement to keep chapter breaks as first-class chunk boundaries in the fallback path — chunk *within* each chapter's text, don't concatenate-then-reblind-chunk across chapter boundaries.
- **Calling `chat.parse()` then manually re-validating with `model_validate_json` "just in case":** `.parse()` already returns a validated Pydantic instance; the manual-`response_format`+`model_validate_json` path (Pattern 2 in xai-sdk's own examples) exists only for when you also need `.sample()`'s finer streaming control — don't use both patterns in the same call.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Grok JSON schema enforcement / retry-on-malformed-JSON | A manual "ask Grok for JSON, `json.loads()`, retry on `JSONDecodeError`" loop | `xai-sdk`'s `chat.parse(PydanticModel)` | Schema compliance is enforced by the API itself (best-effort for some JSON Schema keywords, but core `str`/`int`/`list`/nested-model shapes are guaranteed) — hand-rolled retry loops are strictly worse and still need a schema definition anyway |
| Audio preview playback UI | A custom `<canvas>` waveform player or a wrapper library | Native `<audio>` element + `HTMLAudioElement.play()/.pause()` | WIZ-04/WIZ-05 only need play/pause of a short pre-generated clip — no waveform, no scrubbing UI requested |
| SSE reconnection/keep-alive/buffering headers | Manual `Cache-Control`/`X-Accel-Buffering` header wiring, manual 15s ping loop | `fastapi.sse.EventSourceResponse` (native, ≥0.135) | Already implements exactly this; hand-rolling duplicates a solved, shipped feature |
| Malformed-XHTML recovery | A custom regex-based HTML cleanup pass before parsing | `lxml`'s `recover=True` mode (via BeautifulSoup's `features="lxml-xml"` or `features="lxml"`) | `recover=True` is exactly the documented mechanism for "best-effort fix broken markup" — a bespoke regex pass would re-solve a problem `lxml` already solves robustly |
| Token counting for the chunk-threshold decision | Vendoring or approximating `tiktoken`'s BPE tables for a tokenizer Grok doesn't even use | chars/4 heuristic, with the ~50%-of-context D-06 safety margin absorbing its ~10-28% error | No official Grok tokenizer is public; a precise-looking-but-wrong estimate (using OpenAI's tokenizer to guess Grok's token count) is worse than an honest, wide-margin heuristic |

**Key insight:** Every "hard problem" in this phase already has a load-bearing library or native platform feature that solves it (Grok's own structured-output guarantee, FastAPI's own SSE implementation, lxml's own recovery mode, the browser's own `<audio>` element) — the actual new code this phase writes is the *glue*: prompt engineering, the SQLModel schema, and the wizard's React state management, not re-implementing any of the above.

## Common Pitfalls

### Pitfall 1: `.parse()` streaming limitation surprising a later refactor
**What goes wrong:** A future attempt to stream Grok's structured output token-by-token (e.g. to show cast members appearing live rather than all-at-once) breaks, because `.parse()` doesn't support streaming.
**Why it happens:** xai-sdk's docs explicitly state `.parse()` disables streaming; only `response_format=Model` + `.stream()` supports incremental output, and that path requires manual `model_validate_json` at the end rather than getting a parsed object per chunk.
**How to avoid:** This phase's SSE progress (D-03) is chunk-level ("chunk 2 of 5 done"), not token-level — `.parse()` is the right call for that granularity. Don't reach for `.stream()` unless a future requirement genuinely needs sub-chunk progress.
**Warning signs:** A task description asking for "live token streaming of detected characters" — flag as a scope question, not a `.parse()`-compatible ask.

### Pitfall 2: Spine order != manifest order != file order
**What goes wrong:** Chapters extracted out of order, or a cover/copyright page's boilerplate text gets fed to Grok as if it were chapter 1, confusing character detection.
**Why it happens:** `ebooklib.get_items_of_type(ITEM_DOCUMENT)` returns manifest declaration order, which real-world EPUB toolchains (especially older Calibre-converted files) don't always keep in sync with `book.spine`'s actual linear reading order.
**How to avoid:** Always walk `book.spine` (respecting `linear == "no"` exclusions) and resolve each `idref` via `get_item_with_id()`, per Pattern 3 above — never iterate the manifest directly for extraction order.
**Warning signs:** Extracted chapter count doesn't match the EPUB's actual chapter count in a reading app, or "chapter 1" text looks like front-matter/legal boilerplate.

### Pitfall 3: chars/4 heuristic under-estimating on dialogue-heavy or non-English text
**What goes wrong:** A text estimated safely under the ~500K-token single-shot threshold actually exceeds Grok's real token count once submitted, risking a truncated or rejected call.
**Why it happens:** chars/4 is an English-prose average; heavy dialogue (short lines, lots of punctuation/quote marks) and non-English text tokenize less efficiently than plain narrative prose, and the heuristic's own measured error band is ~10-28% versus a real tokenizer.
**How to avoid:** D-06's ~50%-of-context safety margin (500K of a 1M window) is already sized to absorb this — don't shrink that margin without re-deriving the chunking threshold's error budget. If a book turns out truly borderline, the multi-chunk fallback path (D-07) exists precisely for this.
**Warning signs:** A Grok API error mentioning context length on a text that "should" have fit per the chars/4 estimate — the estimate underestimated, not a Grok API bug.

### Pitfall 4: SQLite `check_same_thread` + background asyncio task writing from a different thread than the request handler
**What goes wrong:** `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread` (or silent corruption) when the background analysis task and the FastAPI request handlers touch the same SQLite connection from different threads/tasks.
**Why it happens:** SQLModel's default `create_engine("sqlite:///...")` sets `check_same_thread=True` unless explicitly overridden; combined with `run_in_threadpool` (Phase 1's established pattern for blocking calls) or a bare `asyncio.create_task`, connections can end up crossing thread boundaries.
**How to avoid:** Pass `connect_args={"check_same_thread": False}` to `create_engine`, and open a fresh `Session` per operation (per-request/per-task, not a shared long-lived session) — this is SQLModel's own documented FastAPI pattern, not a workaround.
**Warning signs:** Intermittent `ProgrammingError` only under concurrent load, or silent writes that don't appear in later reads.

### Pitfall 5: Eager voice-preview generation racing a rapid re-assignment
**What goes wrong:** User picks preset A, TTS starts generating a preview; user immediately changes their mind to preset B before A's preview finishes — two `tts_client.synthesize()` calls race, and the wrong (stale) preview WAV can end up referenced by `Character.preview_audio_path`.
**Why it happens:** WIZ-05 requires eager (on-assign, not on-click) generation; a naive "fire-and-forget on every PATCH" implementation has no ordering guarantee between two overlapping generation calls for the same character.
**How to avoid:** When starting a new preview generation for a character, either (a) cancel/ignore the result of any still-in-flight generation for that same character ID, or (b) make the write "last request wins" by stamping each generation with the voice-assignment version/timestamp it was generated for, and only writing `preview_audio_path` if that stamp still matches the character's *current* voice assignment when the generation completes.
**Warning signs:** Playing a character's preview and hearing the previous preset/instructions instead of the currently-assigned one.

## Code Examples

### Shared Pydantic schema (Grok response contract + persistence + API)
```python
# schemas.py — one shape reused across the LLM output, DB, and API
# per STACK.md's explicit recommendation
from pydantic import BaseModel, Field

class CharacterSuggestion(BaseModel):
    name: str
    description: str = Field(description="Inferred age/gender/personality traits")
    is_narrator: bool = False

class SegmentSuggestion(BaseModel):
    order: int
    character_name: str  # resolved to Character.id after persistence
    text: str
    voice_instructions: str = Field(description="e.g. 'narrates in a soothing voice'")

class CastAnalysisResult(BaseModel):
    characters: list[CharacterSuggestion]
    segments: list[SegmentSuggestion]
```

### chars/4 token estimate (single function, no dependency)
```python
# token_estimate.py
def estimate_tokens(text: str) -> int:
    """Rough English-prose token estimate (~10-28% error band per chars/4
    heuristic research). D-06's ~50%-of-context safety margin absorbs this
    error — do not treat the return value as exact."""
    return len(text) // 4
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `sse-starlette` third-party package for FastAPI SSE | Native `fastapi.sse.EventSourceResponse` | FastAPI ~0.135 (this project pins 0.139.0) | No extra dependency needed; STACK.md already anticipated this — confirmed still current |
| Grok `grok-3`/`grok-4` context windows (historically smaller) | `grok-4.3` at 1M tokens, $1.25/$2.50 per 1M in/out | Current as of docs.x.ai check on 2026-07-10 | D-06's 500K-token chunking threshold is genuinely a ~50% margin under the real ceiling, not a stale/overcautious number |

**Deprecated/outdated:** None identified specific to this phase's stack beyond the SSE point above.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `ebooklib` spine tuples are `(idref, linear)` and resolve via `book.get_item_with_id(idref)` | Architecture Patterns / Pattern 3 | If the tuple shape or method name differs slightly in 0.20, the EPUB parser module needs a one-line fix during implementation — low risk, easily caught by a smoke test against a real EPUB (D-13's fail-fast policy will surface a wrong assumption immediately rather than silently) |
| A2 | `epub:type="noteref"`/`"footnote"` and common id/href-to-endnote patterns are the dominant real-world footnote-marking conventions (D-11) | Common Pitfalls (implicit), STACK.md carryover | If a specific EPUB uses a nonstandard footnote convention (e.g. plain `<sup>` tags with no `epub:type`), footnotes may leak into narration text uncleaned — D-10/D-11 are explicitly scoped as "best-effort, not a guarantee" already, so this is an accepted, documented limitation rather than a silent gap |
| A3 | SQLModel's FastAPI-integration guidance (`check_same_thread=False`, per-request `Session`) applies unchanged to this app's background-asyncio-task-plus-request-handler shape | Common Pitfalls / Pitfall 4 | If the background task's session lifecycle needs different handling than the tutorial's per-request pattern, could surface as an intermittent threading error during implementation — should be caught by a basic integration test exercising concurrent analysis + a read request |

**If this table is empty:** N/A — see entries above; all three are implementation-detail-level assumptions with cheap, fast-failing detection paths (D-13's fail-fast policy, a smoke test, or an integration test), not decisions that need user confirmation before planning proceeds.

## Open Questions

1. **Exact Grok system prompt wording for cast/segment extraction**
   - What we know: The schema (`CastAnalysisResult`) and the reconciliation context shape (D-07/D-08: running cast list + last 20 segments) are locked.
   - What's unclear: The precise prompt wording that reliably produces good character-trait inference (age/gender/personality) and confident cross-chunk name matching (D-08) is a prompt-engineering question best resolved iteratively during implementation/testing against real book text, not something a research pass can pin down in advance.
   - Recommendation: Planner should scope a task for "draft + iterate the system prompt against a real short story/chapter" with a manual eyeball-check acceptance criterion, rather than treating prompt wording as a fixed spec.

2. **Preset voice list / mapping from character description to a specific CustomVoice preset**
   - What we know: D-16 says pre-fill free-text voice instructions from the LLM's inferred description, plus "a best-guess preset pick."
   - What's unclear: The actual 9 CustomVoice preset names/characteristics (`model.get_supported_speakers()`) weren't re-verified in this research pass — Phase 1 already picked one default preset for its spike, but the full list needs enumerating against the actual `qwen-tts` model for the wizard's preset dropdown.
   - Recommendation: Planner should include a task to enumerate `get_supported_speakers()` output (or check Phase 1's TTS container logs/code for whatever was already discovered) before building the preset-picker UI — this is a quick lookup against code Phase 1 already touched, not new research.

## Project Constraints (from CLAUDE.md)

- Lint gate: after any major Python change, `cd backend && uv run ruff check .` (strict: `E, F, I, UP, B`) — apply `--fix`, then fix remaining warnings manually before committing. Applies to every new backend module this phase adds (`db.py`, `models.py`, `schemas.py`, `analysis_client.py`, `analysis_worker.py`, `epub_parser.py`, `token_estimate.py`).
- Podman (not Docker) for deployment — no new container work this phase touches deployment shape, but any new backend dependency (`xai-sdk`, `sqlmodel`, `ebooklib`, `beautifulsoup4`, `lxml`) must be added to `backend/Containerfile.backend`'s `uv sync` layer, not installed ad hoc.
- `TTS_BACKEND=mock` pattern precedent — `LLM_BACKEND=mock` (D-04) must gate the real `xai-sdk` import behind the flag identically, so dev/CI never requires a live `XAI_API_KEY`.
- No Celery/Redis/task queue — background analysis must be an in-process `asyncio` task, not a new service.
- `pydub` forbidden for audio — not relevant to this phase's new code (no new audio-join work), but voice-preview generation must go through the existing `tts_client.synthesize()` → ffmpeg-free WAV write path, consistent with Phase 1.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ING-02 | Upload EPUB, extract reading-order text, strip markup/footnotes | Pattern 3 (spine traversal), Pitfall 2 (spine vs manifest order), Don't-Hand-Roll (lxml `recover=True`) |
| CAST-01 | Grok detects cast (narrator + characters) with inferred traits | Pattern 1 (xai-sdk `.parse()`), shared `CastAnalysisResult` schema in Code Examples |
| CAST-02 | Running cast list re-supplied to each chunk to minimize duplicates | Architecture Diagram step 4 (per D-07/D-08, already locked — research confirms the xai-sdk call shape carries this context) |
| CAST-03 | Text split into ordered, voice-tagged narration/dialogue segments | `SegmentSuggestion` schema in Code Examples, same `.parse()` call as CAST-01 |
| WIZ-01 | User reviews LLM-suggested cast before segments are generated | Architecture Diagram steps 5-6; D-14 single-page UI (locked) |
| WIZ-02 | Rename/merge/edit character description | Recommended Project Structure (`CharacterCard.tsx`), no new library needed (Don't Hand-Roll has no entry here — this is plain React state + a PATCH endpoint) |
| WIZ-03 | Assign preset or free-text voice per character | Open Question 2 (preset enumeration), D-16 (locked, pre-fill from description) |
| WIZ-04 | Play/pause preview per character | Don't Hand-Roll (native `<audio>` element) |
| WIZ-05 | Preview pre-generated eagerly on voice assignment | Architecture Diagram step 6, Pitfall 5 (race-condition handling) |

</phase_requirements>

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `node`/`npm` | Frontend scaffolding (Vite/React) | Yes (this research host) | node v20.19.2, npm 9.2.0 | — |
| `ffmpeg` | Audio join (existing, unchanged this phase) | Not on this research shell's PATH | — | Already provisioned inside `backend/Containerfile.backend` via `apt-get install ffmpeg` (verified by reading the Containerfile) — no action needed; this host is a sandboxed research environment, not the dev/deploy target |
| `uv` | Backend dependency management | Not on this research shell's PATH | — | Already provisioned in Phase 1's dev host and in `Containerfile.backend` (`pip install uv`) — same sandbox caveat as ffmpeg |
| `XAI_API_KEY` / Grok API reachability | Real (non-mock) Grok analysis calls | Not set in this environment | — | `LLM_BACKEND=mock` (D-04) is the required dev/test fallback — real key only needed for production deployment and any manual real-API smoke test |

**Missing dependencies with no fallback:** None — every gap above is either a sandboxed-research-host artifact (ffmpeg/uv already solved by the existing Containerfile) or has an explicit, already-locked mock fallback (`LLM_BACKEND=mock`).

**Missing dependencies with fallback:** `ffmpeg`, `uv` (container-provisioned), `XAI_API_KEY` (mock backend).

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Tailscale is the access boundary (DEPL-02, out of this phase) — no auth layer added |
| V3 Session Management | No | No session/cookie auth introduced this phase |
| V4 Access Control | No | Single-user tool; no per-user resource scoping needed |
| V5 Input Validation | Yes | EPUB upload: reuse Phase 1's `_read_upload_bounded` size-cap pattern for the new upload path; Pydantic (via SQLModel/FastAPI) validates all new request/response bodies; Grok's `.parse()` output is itself schema-validated on the way in |
| V6 Cryptography | No | No new secrets beyond `XAI_API_KEY`, which is an env var like `TTS_SERVICE_URL` — no crypto operations this phase introduces |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| Zip-bomb / decompression-bomb EPUB (EPUB is a ZIP container) | Denial of Service | Apply the same `MAX_UPLOAD_BYTES` bound (Phase 1's `_read_upload_bounded`) to the raw EPUB upload before `ebooklib.read_epub()` ever decompresses it; `ebooklib` itself doesn't cap decompressed size, so the bound must be enforced on the compressed upload as the first line of defense |
| Malicious/malformed XHTML triggering XXE (XML External Entity) injection during parse | Information Disclosure | `lxml`'s default parser has XXE protections since 4.x+ (network/entity resolution disabled by default) — do not construct a custom `lxml.etree.XMLParser` with `resolve_entities=True` or `no_network=False` when wiring `recover=True` |
| Path traversal via EPUB-internal filenames (spine item names, `href` values) used to construct filesystem paths | Tampering | Never use any string sourced from inside the EPUB (item names, hrefs) to build a filesystem path — continue Phase 1's established pattern of UUID-based server-generated paths for anything written to disk (preview WAVs, project directories) |
| Prompt injection via untrusted book text influencing the Grok system prompt / instructions | Tampering (of LLM output) | Keep the system prompt and user-supplied book text in separate message roles (`system(...)` vs `user(...)`, per Pattern 1) — never string-concatenate book text into the system prompt; this is already how the shared schema/`.parse()` pattern is structured, not an extra step |

## Sources

### Primary (HIGH confidence)
- `docs.x.ai/developers/models` (WebFetch, 2026-07-10) — confirmed grok-4.3 = 1M context, $1.25/$2.50 per 1M tokens
- `github.com/xai-org/xai-sdk-python` raw `examples/aio/structured_outputs.py` (WebFetch, 2026-07-10) — exact `.parse()`/`response_format` code shape
- `docs.x.ai/developers/model-capabilities/text/structured-outputs` (WebSearch, 2026-07-10) — `.parse()` streaming limitation, JSON Schema keyword support caveats
- `fastapi.tiangolo.com/tutorial/server-sent-events/` (WebFetch, 2026-07-10) — native `EventSourceResponse` code pattern, built-in keep-alive/header behavior
- `pypi.org/pypi/<pkg>/json` for `xai-sdk`, `sqlmodel`, `ebooklib`, `beautifulsoup4`, `lxml` (direct API query, 2026-07-10) — live version/release-date verification
- `npm view <pkg> version` for `react`, `react-dom`, `vite`, `@tanstack/react-table`, `tailwindcss` (direct registry query, 2026-07-10) — live version verification

### Secondary (MEDIUM confidence)
- `github.com/aerkalov/ebooklib` README (WebFetch, 2026-07-10) — `book.spine`, `get_items_of_type(ITEM_DOCUMENT)` confirmed; exact spine-tuple resolution code not shown in fetched excerpt (see A1 in Assumptions Log)
- WebSearch on chars/4 token-estimation heuristic (2026-07-10) — cross-referenced across multiple sources, consistent ~10-28% error figures
- WebSearch on BeautifulSoup/lxml `recover=True` + EPUB `epub:type` footnote conventions (2026-07-10) — general pattern confirmed, EPUB-specific `epub:type` handling not found in a single authoritative source (see A2)

### Tertiary (LOW confidence)
- None used as load-bearing claims — all `[ASSUMED]`-tagged items are logged in the Assumptions Log above with an explicit low-risk rationale.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all package versions verified live against PyPI/npm registries, not training-data guesses
- xai-sdk API shape / Grok model specs: HIGH — verified against official SDK source and official docs.x.ai
- FastAPI SSE pattern: HIGH — verified against official FastAPI docs
- EPUB parsing specifics (spine resolution, footnote detection): MEDIUM — training-knowledge-grounded, partially confirmed, two items logged as assumptions with fast-failing detection paths
- Cross-chunk cast reconciliation quality: MEDIUM (unchanged from STATE.md's carried-forward risk note — this research pass did not find a sourced novel-length benchmark for LLM cross-chunk character reconciliation; D-07/D-08 remain a synthesized best-practice, not a proven-correct approach)

**Research date:** 2026-07-10
**Valid until:** ~2026-08-09 (30 days) for the EPUB/FastAPI/xai-sdk API-shape findings (stable APIs); ~2026-07-17 (7 days) for the exact package version pins given `xai-sdk`/`sqlmodel` are fast-moving, recently-released packages — re-verify versions immediately before `uv add` if planning is delayed past a week
