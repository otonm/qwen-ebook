# Phase 3: Editable Table, Full Generation Pipeline, Persistence & Deployment - Research

**Researched:** 2026-07-11
**Domain:** Editable data-grid UI, resumable/crash-safe job orchestration without a task queue, content-addressable caching, and Podman Quadlet (systemd) production deployment
**Confidence:** MEDIUM-HIGH (the individual techniques are well-documented; the specific combination — content-hash cache + resumable batch + concurrent per-row regen, all against real GPU inference — is genuinely untested per CONTEXT.md D-02)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01/D-02/D-03 (real-hardware validation):** The production RX 9070 XT VM (Tailscale hostname `tts`) already exists and Phase 1's GPU re-verification checklist is closed out on it. No pod currently runs on the VM between sessions. Phase 3's plan must start by running `bash deploy/run-local.sh` to re-confirm the pod comes up, then build/test the generation pipeline against **real synthesis where practical during execution** — not defer all real-hardware contact to a final sign-off. `TTS_BACKEND=mock`/`LLM_BACKEND=mock` remain the default for fast local iteration (UI work, table logic, caching-key correctness); the shift is validating early and incrementally, not dropping mocks.
- **D-04 (Project List / Reopen, PERS-02):** Add a `GET /projects` list endpoint + a new frontend project-list screen (filename, date, status) to pick a project to reopen — not just the single-slot localStorage "resume last project" mechanism. No schema change needed (multiple `Project` rows already exist in SQLite). Navigation placement is Claude's discretion.
- **D-05 (Bulk Row Selection, TBL-03):** Checkbox column + header "select all" + an action bar appearing above the table when 1+ rows are selected (e.g. "Reassign narrator to: [dropdown]"). Not shift/ctrl-click range select.
- **D-06 (Regeneration Trigger, GEN-03):** Auto-regenerate on blur — editing a row's Narrator/Voice Instructions/Text and clicking away triggers that row's regeneration automatically in the background, consistent with Phase 2's autosave-on-blur pattern (no separate Save/confirm step). Applies per-row; distinct from the batch "generate all" action.

### Claude's Discretion

- Project list screen's navigation placement/entry point.
- Batch-vs-per-row-edit interleaving behavior during concurrent generation (flagged for real-hardware testing per D-02/D-06).
- Exact content-hash implementation (algorithm, what "voice/model version" concretely means given only one TTS model exists today) — must satisfy GEN-02's stated key: (character, voice instructions, text, voice/model version).
- Exact SSE/polling mechanism for CFG-03's live per-segment/overall progress — likely reuses Phase 2's `EventSourceResponse` pattern, exact event schema open.
- Internal schema additions for generation status (pending/queued/generating/complete/error per GEN-05) and cache key storage — Phase 2's D-02 explicitly deferred this to Phase 3.
- CFG-01's "model" field: real dropdown vs. fixed display value (only one TTS model in scope for v1).

### Deferred Ideas (OUT OF SCOPE)

- VoiceDesign custom voice generation — deferred past Phase 2 (D-17), stays out of scope.
- Full git-like edit history / diff — explicitly out of scope per REQUIREMENTS.md; not raised as a live idea.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TBL-01 | Editable table (~70% width): Narrator dropdown, Voice Instructions free text, Text free text | TanStack Table v8 editable-cell pattern (Architecture Patterns → Pattern 1); reuse `SegmentPreview.tsx`/`ui/table.tsx` |
| TBL-02 | Edit Narrator/Voice Instructions/Text on any row | Same pattern; auto-regen-on-blur wiring (Pattern 3) reuses `CharacterCard.tsx`'s blur-commit convention |
| TBL-03 | Bulk select + reassign Narrator/voice | TanStack Table row-selection guide (Pattern 2) — checkbox column + `getSelectedRowModel()` |
| TBL-04 | Per-row generate + play/pause on demand | Existing `tts_client.synthesize`/`_generate_preview` race-guard pattern extended per-segment |
| GEN-02 | Content-hash cache keyed on (character, voice instructions, text, voice/model version) | Content-hash design (Pattern 4) — SHA-256 hexdigest, recomputed live, no truncation |
| GEN-03 | Edit → regenerate only that segment → rejoin | `audio_join.join_wavs` reused unchanged; regenerate-then-rejoin sequencing (Pattern 4/5) |
| GEN-05 | Persisted per-segment status enabling resumable batch | Resumable batch state machine (Pattern 5) — SQLite status column + asyncio loop, no Celery |
| PERS-01 | Auto-save projects as user works | Already true by construction (every PATCH/edit commits immediately) — no new mechanism needed |
| PERS-02 | Reopen a saved project | `GET /projects` list endpoint (Pattern 6) + project-list screen |
| CFG-01 | Right-side config panel: input file/model/output format/output file | UI-only; no new backend research needed beyond existing `/projects/{id}` payload |
| CFG-02 | Right-side panel: character list + preview controls | Reuses Phase 2's `CharacterCard`/preview endpoints unchanged |
| CFG-03 | Live per-segment/overall progress | SSE extension of `EventSourceResponse` pattern (Pattern 5) with a new event schema |
| DEPL-02 | Tailscale-only exposure, no public exposure, no auth | Podman Quadlet unit design (Pattern 7) + `tailscale serve` binding recommendation |
</phase_requirements>

## Summary

Phase 3 has three genuinely new pieces of engineering (Quadlet deployment, content-hash caching, resumable batch generation) layered onto UI work that is a direct, low-risk extension of Phase 2's established conventions (blur-commit editing, TanStack Table, SSE progress, `asyncio.create_task` background workers with version-stamped race guards). None of the three new pieces require a new external dependency — they compose existing stack primitives (`hashlib` stdlib, SQLite status columns, Podman's built-in Quadlet generator, `@tanstack/react-table` already installed) rather than reaching for new libraries. This keeps the "Don't Hand-Roll" story simple: the risk in this phase is design discipline (getting the cache key composition right, resetting stale "generating" rows on resume, not double-writing the same segment from both an in-flight per-row regen and a running batch pass), not unfamiliar tooling.

The single biggest scope-correctness risk is CONTEXT.md D-02: caching, resumable batch, and concurrent regenerate-while-batch-running have never been exercised against real GPU inference, only `TTS_BACKEND=mock`. The plan should sequence work so the real pod (`bash deploy/run-local.sh`) is brought up early and the generation pipeline is validated against it incrementally — not just at a final sign-off gate the way Phase 1/2 did.

**Primary recommendation:** Extend `Segment` with `generation_status`, `generation_error`, `audio_path`, `cache_key`, and `generation_version` fields; drive the batch/regen state machine as a single in-process `asyncio` loop (matching `analysis_worker.py`'s existing shape, no Celery/Redis); compute the content hash as a full `hashlib.sha256(...).hexdigest()` over (resolved speaker preset, segment voice instructions, segment text, a hardcoded TTS model-version constant), recomputed live on every generate-check rather than trusted as a stored fact; and deploy via Podman Quadlet `.pod`/`.container` unit files (rootful, `User=0`/`Group=0`, `AddDevice=`) with the backend bound so only `tailscale serve` exposes it on the tailnet.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Editable segment table (TBL-01/02) | Browser / Client | API / Backend | Cell edit state lives in React (TanStack Table); PATCH on blur persists to backend, same split as `CharacterCard.tsx` |
| Bulk row selection + reassign (TBL-03) | Browser / Client | API / Backend | Selection state is client-only (`rowSelection`); the bulk PATCH is a single new backend endpoint |
| Per-row generate/preview (TBL-04) | API / Backend | Database / Storage | Backend orchestrates `tts_client.synthesize`; audio bytes land on disk, referenced by path (existing convention, never blobbed) |
| Content-hash cache (GEN-02) | API / Backend | Database / Storage | Hash computed and compared in Python; the `cache_key`/`audio_path` pair is the only persisted cache metadata |
| Regenerate-then-rejoin (GEN-03) | API / Backend | Database / Storage | `audio_join.join_wavs` (ffmpeg subprocess) is backend-owned; output file path stored per project |
| Resumable batch state machine (GEN-05) | API / Backend | Database / Storage | Single in-process `asyncio` loop (no separate worker tier, per CLAUDE.md's no-Celery constraint); status persisted per segment so a process restart can resume |
| Project save/reopen (PERS-01/02) | Database / Storage | API / Backend | SQLite already durable-by-default per write; `GET /projects` is a thin read layer over it |
| Live progress (CFG-03) | API / Backend | Browser / Client | `EventSourceResponse` push; client only renders — same split as Phase 2's analysis stream |
| Tailscale-only exposure (DEPL-02) | Infra / Network | API / Backend | Access control lives at the network layer (`tailscale serve`/tailnet ACLs), not in application code — matches "no added auth layer" constraint |
| Podman Quadlet deployment (DEPL-02) | Infra / Network | — | systemd-managed container lifecycle; outside all five standard tiers, kept as its own row since it owns none of the application's request/response path |

## Standard Stack

### Core

No new external dependencies are required for this phase. Every new mechanism composes libraries already in the stack:

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `hashlib` (stdlib) | Python 3.12 stdlib | Content-hash cache key (GEN-02) | `[CITED: web search synthesis — SHA-256 hexdigest is the standard TTS-cache key construction, avoids Python's unstable built-in `hash()`]` |
| `@tanstack/react-table` | `8.21.3` (already installed, `frontend/package.json`) | Editable cells + row selection + bulk toolbar (TBL-01..04) | `[VERIFIED: package.json]` Already the read-only table engine in `SegmentPreview.tsx`; v8's own guide covers editable cells and checkbox row selection natively — no second table library needed |
| Podman (Quadlet generator) | `5.4.2`+ (matches `podman --version` on this host; VM confirmed Podman-capable per D-01) | Production deployment as systemd units (DEPL-02) | `[CITED: docs.podman.io]` Built into Podman itself since v4.4+; CLAUDE.md already mandates Podman + Quadlets over Docker/Kubernetes |
| `fastapi.sse.EventSourceResponse` | Already pinned (`fastapi==0.139.0`) | Live per-segment/overall progress (CFG-03) | `[VERIFIED: codebase]` Identical mechanism already used by `analysis_stream` in `main.py` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tailscale serve` (Tailscale CLI, host-level, not a package) | Whatever Tailscale version is on the VM (already installed per `bootstrap-vm.sh`) | Tailnet-only exposure with no public port (DEPL-02) | `[CITED: tailscale.com/docs/features/tailscale-serve]` Bind the backend to `localhost` inside the pod's network namespace and let `tailscale serve` proxy it to the tailnet with automatic HTTPS, rather than publishing `0.0.0.0:8000` and trusting the VM has no public IP |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| In-process `asyncio` batch loop + SQLite status column | Celery/RQ + Redis | Explicitly forbidden by CLAUDE.md ("one GPU, one user" — an in-process asyncio worker + a `status` column in SQLite is the mandated shape) |
| `hashlib.sha256(...).hexdigest()` full digest | Truncated hash (e.g. first 16 hex chars) for shorter filenames | `[CITED: web search]` Truncating to 64 bits drops the birthday-bound collision threshold to ~2^32 — not worth the readability gain for a personal-scale cache |
| Podman Quadlet `.pod`/`.container` units | `podman-compose` / raw `podman run` in a cron/`@reboot` script | Quadlet gets native systemd restart-on-failure, ordering (`After=`/`Requires=`), and `journalctl` logging for free; `podman-compose` still needs an external wrapper to run as a persistent service |
| `tailscale serve` proxy | Bind directly to `0.0.0.0:8000` and rely on "the VM has no public IP" | `[CITED: tailscale.com]` Direct-bind is one host-network misconfiguration away from public exposure; `serve` keeps the app on `localhost` and makes the tailnet the only path in, matching DEPL-02's explicit "no public exposure" requirement more defensively |

**Installation:** None — no `npm install`/`pip install` needed for this phase's new mechanisms. Podman Quadlet is a `podman` subsystem already present at `5.4.2`.

**Version verification:** `@tanstack/react-table` version confirmed directly from `frontend/package.json` (`^8.21.3`) — already installed, not a new install. `podman --version` on this dev sandbox reports `5.4.2`; the target production VM's Podman version should be reconfirmed at execution time (`podman --version` over Tailscale SSH) since Quadlet's exact key set has evolved across Podman 4.4–5.x releases.

## Package Legitimacy Audit

**Not applicable — this phase installs no new external packages.** All new mechanisms (content-hash caching, resumable batch state machine, Quadlet deployment, Tailscale serve) are built from the stdlib, already-installed dependencies (`@tanstack/react-table`, `fastapi`), or host-level tooling (`podman`, `tailscale`) already mandated by CLAUDE.md and already present on the target VM per D-01/D-02.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────── Browser (tailnet client) ───────────────────────────────┐
│  Project List Screen ──(GET /projects)──> pick project ──> Segment Table + Config Panel │
│       │                                         │                    │                  │
│       │                                         ▼                    ▼                  │
│       │                          Editable Table (TanStack Table)   Config Panel          │
│       │                          - Narrator dropdown (blur→PATCH)  - input/model/output  │
│       │                          - Voice Instructions (blur→PATCH) - character list        │
│       │                          - Text (blur→PATCH)               - live progress (SSE)  │
│       │                          - checkbox col + bulk toolbar                            │
│       │                          - per-row Generate/Play button                           │
└───────┼─────────────────────────────────┬──────────────────────────────┬─────────────────┘
        │ GET/POST/PATCH                  │ POST /segments/{id}/generate │ GET /projects/{id}/
        │                                 │ POST /segments/bulk-reassign │   generation-stream (SSE)
        ▼                                 ▼                              │
┌───────────────────────────── FastAPI backend (CPU container) ──────────┼─────────────────┐
│  GET /projects            in-process asyncio batch loop                │                 │
│  GET /projects/{id}       ─────────────────────────────                │                 │
│  PATCH /segments/{id} ──> recompute cache_key ──> cache hit? ───No───> synthesize() ──┐   │
│                                  │                                        (threadpool) │   │
│                                 Yes                                          │         │   │
│                                  │                                          ▼         │   │
│                                  ▼                                    write .wav,     │   │
│                            reuse cached audio_path                    update Segment  │   │
│                                  │                                     row (status=    │   │
│                                  └──────────────┬──────────────────────  complete)     │   │
│                                                 ▼                              │       │   │
│                                    audio_join.join_wavs() (ffmpeg) ◄────────────┘       │   │
│                                                 │                                        │  │
│                                                 ▼                                        │  │
│                                     joined output file (path stored on Project) ─────────┼──┘
│  SSE progress queue (per-project, per-segment + overall) <───────────────────────────────┘
└───────────────────────────────────────┬─────────────────────────────────────────────────┘
                                         │ httpx POST /synthesize (internal, GPU-scoped)
                                         ▼
                          ┌───────────────────────────────────┐
                          │  TTS container (GPU-scoped, ROCm)  │
                          │  Qwen3-TTS-12Hz-1.7B-CustomVoice    │
                          └───────────────────────────────────┘

Both containers run inside one Podman pod (Quadlet .pod unit); only the backend's
port is reachable, and only via `tailscale serve` — no public port published.
```

### Recommended Project Structure

```
backend/app/
├── models.py            # Segment gains: generation_status, generation_error,
│                         #   audio_path, cache_key, generation_version
├── cache_key.py          # NEW — compute_cache_key(preset, voice_instructions, text)
├── generation_worker.py  # NEW — mirrors analysis_worker.py's shape: per-project
│                         #   progress queue, resumable batch loop, per-row regen
├── main.py               # + GET /projects, POST /segments/{id}/generate,
│                         #   POST /segments/bulk-reassign, POST /projects/{id}/
│                         #   generate (batch), GET /projects/{id}/generation-stream
frontend/src/
├── components/
│   ├── ProjectListScreen.tsx   # NEW — PERS-02
│   ├── SegmentTable.tsx        # NEW — extends SegmentPreview.tsx into editable+bulk
│   └── ConfigPanel.tsx         # NEW — CFG-01/02/03 right-side panel
├── hooks/
│   └── useGenerationStream.ts  # NEW — mirrors useAnalysisStream.ts
deploy/
├── qwen-ebook.pod         # NEW — Quadlet pod unit
├── qwen-ebook-tts.container    # NEW — Quadlet container unit (GPU-scoped)
├── qwen-ebook-backend.container # NEW — Quadlet container unit (no GPU devices)
```

### Pattern 1: Editable cell via local state + blur commit (TBL-01/02)

**What:** Each cell renders an `<input>`/`<Select>` backed by local component state; the value commits to the backend only `onBlur`, not on every keystroke.
**When to use:** Every editable cell in the segment table (Narrator dropdown, Voice Instructions, Text).
**Example:**
```tsx
// Source: tanstack.com/table/v8/docs/framework/react/examples/editable-data
// (fetched 2026-07-11) — [CITED: tanstack.com]
// Adapted to this codebase's existing blur-commit convention (CharacterCard.tsx)
function TextCell({ getValue, row, column, table }) {
  const initialValue = getValue<string>()
  const [value, setValue] = useState(initialValue)

  function onBlur() {
    if (value !== initialValue) {
      table.options.meta?.updateData(row.index, column.id, value)
    }
  }

  useEffect(() => setValue(initialValue), [initialValue])

  return (
    <Textarea value={value} onChange={(e) => setValue(e.target.value)} onBlur={onBlur} />
  )
}
```
This is the same shape as `CharacterCard.tsx`'s `handleVoiceInstructionsBlur` — the codebase already has this exact convention twice over (name field, voice instructions field); the table just needs a per-column `cell` renderer instead of a standalone component.

### Pattern 2: Checkbox row selection + bulk toolbar (TBL-03)

**What:** A leading `select` column with a header "select all" checkbox and a per-row checkbox; a toolbar renders above the table only when `table.getSelectedRowModel().rows.length > 0`.
**When to use:** TBL-03's bulk narrator/voice reassignment.
**Example:**
```tsx
// Source: tanstack.com/table/v8/docs/guide/row-selection (fetched 2026-07-11)
// [CITED: tanstack.com]
const columns = [
  columnHelper.display({
    id: "select",
    header: ({ table }) => (
      <Checkbox
        checked={table.getIsAllRowsSelected()}
        onCheckedChange={table.getToggleAllRowsSelectedHandler()}
      />
    ),
    cell: ({ row }) => (
      <Checkbox
        checked={row.getIsSelected()}
        onCheckedChange={row.getToggleSelectedHandler()}
      />
    ),
  }),
  // ...Narrator/Voice Instructions/Text columns
]

const table = useReactTable({
  data: segments,
  columns,
  getCoreRowModel: getCoreRowModel(),
  getRowId: (segment) => segment.id, // stable id, not array index — CITED
  state: { rowSelection },
  onRowSelectionChange: setRowSelection,
})

const selectedIds = Object.keys(table.getState().rowSelection)
```
`getRowId: (segment) => segment.id` is important — without it, TanStack Table indexes selection by array position, which desyncs after any row-order change (a real risk here since a bulk reassign could reorder narrator groupings in future work).

### Pattern 3: Auto-regenerate-on-blur (GEN-03/D-06)

**What:** The same blur handler that PATCHes a segment's Narrator/Voice Instructions/Text also kicks off that segment's regeneration as a fire-and-forget background task — mirroring `patch_character`'s existing `voice_version` bump + `asyncio.create_task(_generate_preview(...))` call.
**When to use:** Every commit-on-blur in the segment table.
**Example:**
```python
# Extends main.py's existing patch_character shape (T-02 pattern) to segments.
@app.patch("/segments/{segment_id}")
async def patch_segment(segment_id: str, patch: SegmentPatch) -> dict:
    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        # ... apply patch.character_id / patch.voice_instructions / patch.text ...
        segment.generation_version += 1
        version = segment.generation_version
        session.add(segment)
        session.commit()

    task = asyncio.create_task(regenerate_segment(segment_id, version))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return result
```
`regenerate_segment` recomputes the cache key from the *current* row, checks the cache, synthesizes if needed, and — same last-request-wins guard as `_generate_preview` — only writes back if `segment.generation_version` still equals `version` when it finishes.

### Pattern 4: Content-hash cache key (GEN-02)

**What:** A single deterministic hash over every field that affects the resulting audio, recomputed live on each generate-check rather than trusted as a cached fact.
**When to use:** Before every synthesize call (per-row on-demand, per-row auto-regen, and each segment inside a batch run).
**Example:**
```python
# NEW: backend/app/cache_key.py
# [ASSUMED — Claude's Discretion per CONTEXT.md; synthesizes CITED web-search
# guidance (SHA-256 hexdigest, full digest, not Python's built-in hash())
# with this codebase's existing preset-resolution logic]
import hashlib

# Bump this string manually if the TTS model or backend implementation changes
# in a way that could change output audio for the same inputs (D-17: only one
# model — Qwen3-TTS-12Hz-1.7B-CustomVoice — is in scope for v1, so this is a
# constant today, not a live "model version" lookup).
TTS_MODEL_VERSION = "qwen3-tts-12hz-1.7b-customvoice-v1"


def compute_cache_key(resolved_speaker: str, voice_instructions: str, text: str) -> str:
    """`resolved_speaker` must be the same value passed to tts_client.synthesize()
    (character.voice_preset, or best_guess_preset() fallback — see
    _generate_preview's existing resolution logic) so a character's preset
    change is naturally reflected without extra bookkeeping."""
    payload = "\x1f".join([resolved_speaker, voice_instructions, text, TTS_MODEL_VERSION])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```
Recomputing the hash live (rather than only updating it in a PATCH handler) means an out-of-band character preset change picked up later, a text edit, or any future model-version bump are all naturally cache-busting with no extra invalidation code path — the cache is "is this exact hash's audio already on disk," full stop. Use `\x1f` (ASCII unit separator) rather than `|` or `,` as the field delimiter — cheap, standard trick to avoid a crafted voice-instructions string containing the delimiter character silently colliding two different (character, text) pairs onto the same hash.

### Pattern 5: Resumable batch generation state machine (GEN-05)

**What:** A single in-process `asyncio` loop that walks segments in order, checks each one's cache key, synthesizes on a miss, and persists status after every segment — not just at the end — so a crash mid-batch leaves an accurate per-segment record.
**When to use:** The "generate all" batch action (CFG-03's overall progress).
**Example:**
```python
# NEW: backend/app/generation_worker.py — mirrors analysis_worker.py's shape
async def run_batch_generation(project_id: str) -> None:
    queue = _get_progress_queue(project_id)

    # Crash-safety: a "generating" row from a previous, now-dead process is
    # not actually in flight — asyncio tasks do not survive a restart. Reset
    # stale "generating" rows to "pending" at the start of every fresh batch
    # invocation, or a resumed batch will treat them as someone else's job
    # forever and never touch them again.
    with Session(engine) as session:
        stale = session.exec(
            select(Segment)
            .where(Segment.project_id == project_id)
            .where(Segment.generation_status == "generating")
        ).all()
        for segment in stale:
            segment.generation_status = "pending"
            session.add(segment)
        session.commit()

    with Session(engine) as session:
        segments = sorted(
            session.exec(select(Segment).where(Segment.project_id == project_id)).all(),
            key=lambda s: s.order,
        )

    total = len(segments)
    for index, segment in enumerate(segments, start=1):
        # Recompute — do not trust a stored cache_key as ground truth about
        # what's on disk today; a concurrent per-row edit could have moved on.
        with Session(engine) as session:
            fresh = session.get(Segment, segment.id)
            if fresh.generation_status == "complete" and _cache_still_valid(fresh):
                await queue.put(("progress", {"segment_id": fresh.id, "n": index, "total": total, "status": "complete"}))
                continue
            fresh.generation_status = "generating"
            session.add(fresh)
            session.commit()

        await queue.put(("progress", {"segment_id": segment.id, "n": index, "total": total, "status": "generating"}))
        try:
            await _generate_one_segment(segment.id)
        except Exception as exc:
            logger.exception(f"segment {segment.id} generation failed")
            with Session(engine) as session:
                fresh = session.get(Segment, segment.id)
                fresh.generation_status = "error"
                fresh.generation_error = str(exc)
                session.add(fresh)
                session.commit()
            await queue.put(("progress", {"segment_id": segment.id, "n": index, "total": total, "status": "error"}))
            continue  # GEN-05: one failed segment must not abort the whole batch

    await queue.put(("done", {"status": "ready"}))
```
This is the same "persist status, don't just hold it in memory" discipline `run_analysis` already applies to `Project.status`, extended to per-segment granularity. `audio_join.join_wavs` is called once after the loop (or on-demand), over whatever the currently-complete segments' `audio_path`s are — see Open Questions for what to do about segments left in `error`.

### Pattern 6: Project list (PERS-02)

**What:** A new read-only list endpoint over the existing `Project` table, no schema change.
**Example:**
```python
@app.get("/projects")
async def list_projects() -> list[dict]:
    with Session(engine) as session:
        projects = session.exec(select(Project).order_by(Project.id)).all()  # add created_at if sortable-by-date is wanted
        return [
            {"id": p.id, "filename": p.filename, "status": p.status}
            for p in projects
        ]
```
Note: `Project` currently has no timestamp column — D-04 asks for "date" in the list. Add a `created_at: datetime` field (default `datetime.utcnow`) to `Project` if a real date column is wanted rather than inferring order from row insertion.

### Pattern 7: Podman Quadlet deployment (DEPL-02)

**What:** Translate `run-local.sh`'s imperative `podman pod create` + two `podman run --pod` invocations into declarative `.pod`/`.container` unit files under `/etc/containers/systemd/`, managed by root's systemd (rootful, matching the D-09-verified GPU access path).
**Example:**
```ini
# deploy/qwen-ebook.pod — [CITED: docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html]
[Unit]
Description=Qwen Ebook Narrator pod

[Pod]
PodName=qwen-ebook
# TTS port 8001 stays pod-internal only — do not PublishPort it (T-03-01).
# Backend is deliberately NOT published to 0.0.0.0 here either — bind it to
# 127.0.0.1 and let `tailscale serve` do the tailnet-facing proxy (DEPL-02).
PublishPort=127.0.0.1:8000:8000

[Install]
WantedBy=multi-user.target
```
```ini
# deploy/qwen-ebook-tts.container
[Unit]
Description=Qwen Ebook TTS (GPU-scoped)
After=qwen-ebook-pod.service
Requires=qwen-ebook-pod.service

[Container]
ContainerName=qwen-ebook-tts
Image=localhost/qwen-ebook-tts:dev
Pod=qwen-ebook.pod
User=0
Group=0
AddDevice=/dev/kfd
AddDevice=/dev/dri
Volume=qwen-ebook-tts-hf-cache:/home/ubuntu/.cache/huggingface

[Install]
WantedBy=multi-user.target
```
```ini
# deploy/qwen-ebook-backend.container
[Unit]
Description=Qwen Ebook backend (CPU-only)
After=qwen-ebook-pod.service qwen-ebook-tts.service
Requires=qwen-ebook-pod.service

[Container]
ContainerName=qwen-ebook-backend
Image=localhost/qwen-ebook-backend:dev
Pod=qwen-ebook.pod
Environment=TTS_BACKEND=http
Environment=TTS_SERVICE_URL=http://localhost:8001

[Install]
WantedBy=multi-user.target
```
Bring-up: `sudo systemctl daemon-reload && sudo systemctl start qwen-ebook-backend.service` (starting the backend unit pulls in the pod and the TTS unit via `Requires=`). Then, once: `sudo tailscale serve --bg 8000` (persists across reboots as a Tailscale Serve config, independent of the Quadlet units).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multi-field content hash | Custom string-concat + Python `hash()` | `hashlib.sha256(...).hexdigest()` (stdlib) | `[CITED]` Built-in `hash()` is salted per-process (`PYTHONHASHSEED`) — not stable across the backend restarting, which would silently invalidate the entire cache on every deploy |
| Resumable job queue | Celery/RQ + Redis, or a hand-rolled thread pool with a custom lock | A persisted SQLite status column + one in-process `asyncio` loop | CLAUDE.md explicitly forbids Celery/Redis for this project's scale; `analysis_worker.py` already proves the shape works |
| Editable spreadsheet grid | A second table/grid library, or raw `<table>` + manual cell-focus tracking | `@tanstack/react-table`'s built-in editable-cell (`meta.updateData`) + row-selection (`rowSelection` state) APIs | Already installed and already used for the read-only preview; v8 ships both patterns as first-class, documented guides |
| Persistent GPU-container service | A shell script wrapped in `@reboot` cron, or a hand-rolled supervisor loop | Podman Quadlet `.pod`/`.container` units | Native systemd semantics (restart-on-failure, ordering via `After=`/`Requires=`, `journalctl` logs) for free; CLAUDE.md already mandates Podman + Quadlets |
| Tailnet-only network exposure | Custom iptables rules, or binding `0.0.0.0` and trusting VM has no public IP | `tailscale serve` (proxy from `localhost` to the tailnet) | `[CITED: tailscale.com]` One command, automatic HTTPS, stable hostname, and the app process never has to listen on anything but loopback |

**Key insight:** Every "don't hand-roll" item in this phase already has a first-class primitive one layer down in the stack the project already committed to (stdlib, an installed npm package, or Podman/Tailscale's own tooling) — the discipline required is choosing the existing primitive correctly, not building something new.

## Common Pitfalls

### Pitfall 1: "generating" status surviving a crash as a false in-flight marker
**What goes wrong:** A batch run crashes (process restart, VM reboot) while segment N is mid-synthesis. Its row is left with `generation_status="generating"`. On resume, a loop that only picks up `"pending"` rows will never touch it again.
**Why it happens:** `asyncio` tasks do not survive a process restart; nothing marks the interrupted row back to `"pending"`.
**How to avoid:** At the start of every batch invocation (and/or in `lifespan()` at app startup), reset any row still `"generating"` for that project back to `"pending"` before starting the loop (Pattern 5 above).
**Warning signs:** A resumed batch reports "done" while one segment's audio is still the old cached file (or missing).

### Pitfall 2: Per-row auto-regen racing a running batch pass
**What goes wrong:** Editing a row mid-batch (D-06's explicitly-flagged discretion area) triggers its own regeneration at the same time the batch loop reaches that same row — two synth calls for one segment, last-write-wins on disk with no guarantee which "wins" is the correct (newest-edit) one.
**Why it happens:** Both paths write `Segment.audio_path`/`cache_key` independently with no coordination.
**How to avoid:** Reuse the existing `voice_version` last-request-wins pattern (`_generate_preview`, Pitfall 5 from Phase 2) as `generation_version`: bump it on every PATCH; any in-flight synth (batch or per-row) that finishes after a newer version has landed discards its own write instead of persisting it.
**Warning signs:** A segment's audible content doesn't match its currently-displayed table row after an edit made during a batch run — flagged in CONTEXT.md as needing real-hardware testing, not just a mock-backend unit test.

### Pitfall 3: Trusting a stored `cache_key` instead of recomputing it
**What goes wrong:** If the cache key is only recomputed inside the PATCH handler (not at generate-time), a case where the underlying character's voice preset changes independently (e.g. via the CFG-02 character panel) leaves stale audio silently un-invalidated.
**How to avoid:** Recompute `compute_cache_key(...)` from live DB state immediately before every generate-check (Pattern 4) — never branch on "did anything call PATCH since last time."

### Pitfall 4: Quadlet unit dropping a device flag that the ad hoc `run-local.sh` command has
**What goes wrong:** `run-local.sh` passes `--user 0:0 --device /dev/kfd --device /dev/dri`; a hand-translated Quadlet unit omits one of these (commonly `--device /dev/dri`, since `/dev/kfd` alone often "looks like" it's enough during a quick manual test) and GPU access silently fails only in the systemd-managed deployment.
**Why it happens:** Already documented project-wide in `.planning/research/PITFALLS.md` Pitfall 1 — Quadlet/systemd-unit deployments frequently drop a flag present in the ad hoc test command.
**How to avoid:** Both `AddDevice=/dev/kfd` and `AddDevice=/dev/dri` plus `User=0`/`Group=0` must all be present in the `.container` unit (Pattern 7); verify post-deploy with `sudo systemctl status qwen-ebook-tts.service` + `podman exec qwen-ebook-tts ls /dev/kfd /dev/dri` exactly as `deploy/README.md` already does for the ad hoc pod.

### Pitfall 5: SQLite write contention between the batch loop, per-row regen, and SSE progress reads
**What goes wrong:** A long batch run holding write transactions open while per-row PATCHes and SSE polling reads happen concurrently can trip SQLite's default rollback-journal locking (`database is locked` / `SQLITE_BUSY`).
**Why it happens:** `[CITED: web search synthesis]` Default SQLite journal mode blocks readers during a writer's transaction; the existing per-operation-`Session` discipline (`db.py`) already avoids long-held transactions, but Phase 3 adds materially more concurrent write traffic than Phase 1/2 had.
**How to avoid:** Set `PRAGMA journal_mode=WAL` (readers don't block on a writer) and a `busy_timeout` of a few seconds at engine creation in `db.py`; keep every transaction as short as Pattern 5's example already does (fetch → mutate → commit, no synth call inside the `with Session(...)` block).
**Warning signs:** Intermittent `OperationalError: database is locked` under a batch run, especially once real GPU synthesis (slower than mock) is in the loop.

### Pitfall 6: Re-rendering the entire table on every keystroke
**What goes wrong:** If a cell's `onChange` calls `table.options.meta.updateData` (or otherwise touches parent state) on every keystroke instead of only `onBlur`, every row re-renders on every keystroke in any cell — sluggish on a book-length segment table.
**How to avoid:** Local `useState` inside each cell component, commit upward only `onBlur` (Pattern 1) — exactly the convention `CharacterCard.tsx` already established for name/voice-instructions fields.

## Code Examples

See Architecture Patterns 1–7 above for the primary verified patterns (editable cell, row selection, auto-regen-on-blur, content-hash cache, resumable batch loop, project list, Quadlet units). No additional standalone examples beyond those are needed — this phase's code is mostly recomposition of patterns already proven in this exact codebase.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `docker-compose`/manual `podman run` for "production" container services | Podman Quadlet (`.container`/`.pod`/`.volume` units, systemd-managed) | Quadlet became Podman's recommended path for persistent services from Podman 4.4 (2023) onward, now the default guidance in Podman 5.x docs | Gets systemd's restart/ordering/logging semantics without a docker-compose-equivalent daemon; matches this project's already-locked Podman-only constraint |
| Binding an app to `0.0.0.0` + relying on network topology for "private" access | `tailscale serve`/`tailscale funnel` as an explicit proxy layer | Tailscale Serve has been GA for some time; it's now the documented recommended pattern for exposing a local dev/self-hosted service to a tailnet | Removes the app's own listen-address choice from the security boundary — the boundary becomes "did you run `tailscale serve`," which is easy to audit |

**Deprecated/outdated:** None specific to this phase's stack — the project's existing choices (FastAPI SSE, SQLModel/SQLite, ffmpeg concat demuxer, TanStack Table v8) are all current, actively-maintained versions already verified in Phase 1/2 research.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The exact content-hash field composition — (resolved speaker preset, segment voice instructions, segment text, a hardcoded `TTS_MODEL_VERSION` constant) — correctly satisfies GEN-02's stated "(character, voice instructions, text, voice/model version)" key | Architecture Patterns → Pattern 4 | If "character" was meant to be the character's *name*/*id* rather than its *resolved preset*, a character rename with an unchanged preset would spuriously invalidate cache (harmless — just wasted regeneration) or, if it were the reverse, a preset-only change on the character (outside the table) might not bust segment-level cache. Confirm with the user/planner during plan-checking if this distinction matters for the exact wording. |
| A2 | New `Segment` fields are named `generation_status`, `generation_error`, `audio_path`, `cache_key`, `generation_version` | Architecture Patterns → Pattern 5, Recommended Project Structure | Purely a naming choice — no functional risk, but the plan should lock these names once so frontend/backend don't drift |
| A3 | `Project` needs a new `created_at` timestamp column to satisfy D-04's "date" column in the project list | Pattern 6 | If the planner instead infers "date" from filesystem mtime of some artifact, or decides insertion order is sufficient, this assumption is moot — flagged as a concrete schema decision the planner should make explicitly |
| A4 | Batch generation should skip (not abort) on a per-segment error, per GEN-05's phrasing "resume ... after an interruption or crash" implying per-segment isolation | Pattern 5 | If the intended behavior is "abort the whole batch on first error," the loop's `continue`-on-exception needs to become a `break`/re-raise instead — see Open Questions |
| A5 | `PRAGMA journal_mode=WAL` should be enabled given Phase 3's new concurrent-write load | Common Pitfalls → Pitfall 5 | Low risk if wrong — WAL is safe to enable and is SQLite's own stated general recommendation; worst case it's an unnecessary change for this app's actual concurrency level |

**If this table is empty:** N/A — see rows above; all are flagged for planner/CONTEXT confirmation rather than blocking.

## Open Questions (RESOLVED)

1. **What happens when the final join runs while one or more segments are in `error` status?**
   - What we know: GEN-03 says "regenerates only that segment, then rejoins the full output file, leaving unchanged rows untouched" — implying the join always runs over whatever's current.
   - What's unclear: Whether an `error`-status segment should (a) block the join entirely with a surfaced error, (b) join with its last-known-good cached audio if one exists, or (c) join with a placeholder/silence and flag it.
   - Recommendation: Simplest correct default — block the join (return an error to the user) if any segment lacks a valid `audio_path`, since ENH-02 ("last good" fallback) is explicitly deferred to v2. Confirm this reading with the user during plan-checking if it matters.
   - **RESOLVED (plan 03-03):** Adopted option (a) — block the join. 03-03 Task 2's action and `key_links` require the batch join to surface an error if any segment lacks a valid `audio_path` (no last-good fallback in v1). See `03-03-PLAN.md`.

2. **Does `PublishPort=127.0.0.1:8000:8000` in the Quadlet pod unit actually reach the host's `tailscale serve` correctly, or does `tailscale serve` need the container's port published on all interfaces bound to loopback specifically?**
   - What we know: `tailscale serve 8000` on the host proxies to whatever's listening on `localhost:8000` on the host network namespace.
   - What's unclear: Whether Podman's `127.0.0.1:8000:8000` port-publish binds in a way `tailscale serve` (running as a normal host process, not inside any container) can reach — this needs a real-hardware check during execution (matches D-01/D-02's "validate early, not just at the end" instruction).
   - Recommendation: Verify with `curl 127.0.0.1:8000/healthz` from the host once the Quadlet pod is up, then `tailscale serve --bg 8000` and confirm from a second tailnet device before considering DEPL-02 done.
   - **RESOLVED (plan 03-05):** Verified on real hardware during 03-05 execution — 03-05 Task 2 stands the Quadlet pod up and Task 3 runs the `curl 127.0.0.1:8000/healthz` → `tailscale serve --bg 8000` → second-tailnet-device check before DEPL-02 is considered done. See `03-05-PLAN.md`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Podman | Quadlet deployment (DEPL-02) | ✓ (dev sandbox) | 5.4.2 | Production VM already confirmed Podman-capable per D-01; reconfirm version there via Tailscale SSH before finalizing Quadlet unit syntax (key set varies slightly 4.4–5.x) |
| systemd | Quadlet unit management (DEPL-02) | ✓ (dev sandbox) | 257 | Production VM is Debian 13 (systemd-based) per D-01 — no fallback needed |
| ffmpeg | `audio_join.join_wavs` (GEN-03 rejoin) | ✗ (dev sandbox — not installed here) | — | Baked into `Containerfile.backend` via `apt-get install ffmpeg`; not needed on the bare dev sandbox unless running `audio_join` tests outside a container. No fallback needed for containerized execution. |
| Tailscale CLI (`tailscale serve`) | DEPL-02 tailnet-only exposure | Not checked in this sandbox | — | Confirmed already installed on the production VM per `bootstrap-vm.sh`/D-01/D-02 |
| Node.js / npm | Frontend build (`@tanstack/react-table` already installed) | ✓ | node v20.19.2, npm 9.2.0 | — |
| Python | Backend (`uv`-managed venv, not this sandbox's system Python) | ✓ (sandbox has 3.13; project pins 3.12 via `uv`) | System 3.13.5 (irrelevant — `uv sync` provisions its own 3.12 venv per `pyproject.toml`) | None needed — `uv` manages the pinned interpreter |

**Missing dependencies with no fallback:** None — every gap above either has a documented fallback or is already resolved on the actual target VM per D-01/D-02.

**Missing dependencies with fallback:** ffmpeg (containerized at execution time, not needed bare in this research sandbox).

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Explicitly out of scope — Tailscale tailnet membership is the sole access control (CLAUDE.md, REQUIREMENTS.md Out of Scope) |
| V3 Session Management | No | No sessions/cookies introduced by this phase |
| V4 Access Control | No (app layer) / Yes (network layer) | No app-level authorization; network-layer control is `tailscale serve` + tailnet ACLs (Pattern 7) |
| V5 Input Validation | Yes | Segment PATCH bodies (Narrator/Voice Instructions/Text edits) and bulk-reassign requests validated via Pydantic models, same discipline as existing `CharacterPatch`/`MergeRequest` |
| V6 Cryptography | No direct app use | The only "hash" in this phase (GEN-02's content-hash cache key) is for cache addressing, not a security control — SHA-256 is appropriate there regardless (collision-resistance, not secrecy) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Cache-key/audio-path used to construct a filesystem path from user-controlled input | Tampering | Continue the existing convention (`preview_audio_path`, `_generate_preview`) of server-generated identifiers for filenames — the cache key itself (a hex SHA-256 digest) is safe to use directly as a filename component since it's alphanumeric-only and never derived from a raw, unsanitized client string |
| Bulk-reassign endpoint accepting an arbitrary list of segment ids + a target character id | Tampering | Validate every segment id belongs to the same `project_id` as the target character (same discipline `merge_character` already applies for `source.project_id != target.project_id`) before applying the reassignment |
| A compromised/malicious device on the tailnet hitting any endpoint (no auth layer) | Spoofing / Elevation of Privilege | Explicitly accepted risk per project constraints — Tailscale tailnet membership is the trust boundary; out of scope to add app-level auth (REQUIREMENTS.md Out of Scope: "Multi-user accounts / login / RBAC") |
| Podman Quadlet unit files world-readable/writable under `/etc/containers/systemd/` | Tampering | Standard root-owned config file permissions (0644, root:root) — no different from any other systemd unit; no project-specific secret material lives in these unit files (env vars used are non-sensitive: `TTS_BACKEND`, `TTS_SERVICE_URL`) |

## Sources

### Primary (HIGH confidence)
- Codebase: `backend/app/models.py`, `analysis_worker.py`, `main.py`, `tts_client.py`, `audio_join.py`, `db.py`, `config.py` — existing verified patterns this phase extends
- Codebase: `frontend/src/components/SegmentPreview.tsx`, `CharacterCard.tsx`, `App.tsx`, `hooks/useAnalysisStream.ts`, `api/client.ts` — existing verified UI conventions
- `frontend/package.json` — confirmed `@tanstack/react-table` `^8.21.3` already installed
- `deploy/run-local.sh`, `deploy/README.md`, `deploy/bootstrap-vm.sh`, `backend/Containerfile.backend`, `backend/Containerfile.tts` — existing verified deployment topology this phase's Quadlet units translate

### Secondary (MEDIUM confidence — CITED, official docs)
- [docs.podman.io — podman-systemd.unit(5)](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html) — Quadlet `.pod`/`.container` syntax, `AddDevice=`, `User=`/`Group=`, `Volume=`, `PublishPort=`, rootful vs. rootless unit search paths
- [tanstack.com/table/v8/docs/framework/react/examples/editable-data](https://tanstack.com/table/v8/docs/framework/react/examples/editable-data) — editable-cell `meta.updateData` pattern
- [tanstack.com/table/v8/docs/guide/row-selection](https://tanstack.com/table/v8/docs/guide/row-selection) — checkbox column, `getRowId`, `rowSelection` state
- [tailscale.com/docs/features/tailscale-serve](https://tailscale.com/docs/features/tailscale-serve) — tailnet-only exposure via `tailscale serve`, localhost-bind recommendation

### Tertiary (LOW confidence — web search synthesis, not a single authoritative doc)
- SHA-256 hexdigest as standard TTS-cache key composition, and truncation/collision risk (synthesized from multiple web sources, no single canonical spec)
- SQLite `journal_mode=WAL` + `busy_timeout` recommendation for concurrent FastAPI background-task writes (well-established general SQLite guidance, not verified against this project's actual concurrency profile)
- FastAPI resumable background-job patterns without Celery (general community guidance; this project's own `analysis_worker.py` precedent is the stronger, HIGH-confidence source for the actual pattern used)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; every mechanism composes already-installed/already-mandated tooling
- Architecture: MEDIUM-HIGH — UI/blur-commit/SSE patterns are direct extensions of proven Phase 1/2 code; content-hash/resumable-batch/Quadlet designs are sound but genuinely untested against real GPU inference (CONTEXT.md D-02)
- Pitfalls: MEDIUM — Quadlet device-flag pitfall is directly documented project history (HIGH); concurrency/SQLite pitfalls are well-established general knowledge (MEDIUM), not yet observed in this specific app

**Research date:** 2026-07-11
**Valid until:** 2026-08-10 (30 days — stack is stable; Podman Quadlet key syntax has shifted across recent major versions, worth reconfirming against the production VM's exact Podman version at execution time rather than trusting this document past that window)
