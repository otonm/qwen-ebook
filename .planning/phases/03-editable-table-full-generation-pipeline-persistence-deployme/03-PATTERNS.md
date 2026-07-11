# Phase 3: Editable Table, Full Generation Pipeline, Persistence & Deployment - Pattern Map

**Mapped:** 2026-07-11
**Files analyzed:** 15 (10 new, 5 modified)
**Analogs found:** 15 / 15 (all have a strong in-repo analog — this phase is almost entirely recomposition of Phase 1/2 patterns per RESEARCH.md)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `backend/app/models.py` (modify) | model | CRUD | itself (`Segment`/`Character`/`Project` classes) | exact — additive fields only |
| `backend/app/cache_key.py` (new) | utility | transform | `backend/app/token_estimate.py` (small pure-function stdlib utility module) | role-match |
| `backend/app/generation_worker.py` (new) | service | event-driven / batch | `backend/app/analysis_worker.py` | exact |
| `backend/app/main.py` (modify — new routes) | controller/route | request-response, streaming | itself (`create_project`, `patch_character`, `analysis_stream`, `merge_character`) | exact |
| `backend/app/db.py` (modify — WAL pragma) | config | — | itself (`engine = create_engine(...)`) | exact |
| `frontend/src/components/SegmentTable.tsx` (new) | component | CRUD (editable grid) | `frontend/src/components/SegmentPreview.tsx` | exact |
| `frontend/src/components/ProjectListScreen.tsx` (new) | component | request-response (list+select) | `frontend/src/components/UploadScreen.tsx` (screen-level component, simple fetch-and-render) + `CastWizard.tsx` (screen composition) | role-match |
| `frontend/src/components/ConfigPanel.tsx` (new) | component | request-response | `frontend/src/components/CharacterCard.tsx` (right-hand panel, blur-commit fields, play/pause preview) | exact |
| `frontend/src/hooks/useGenerationStream.ts` (new) | hook | streaming (SSE) | `frontend/src/hooks/useAnalysisStream.ts` | exact |
| `frontend/src/api/client.ts` (modify — new endpoints) | utility (API layer) | request-response | itself (existing fetch wrappers) | exact |
| `frontend/src/App.tsx` (modify — routing/project list entry) | component | request-response | itself (`PROJECT_ID_STORAGE_KEY` localStorage logic) | exact |
| `deploy/qwen-ebook.pod` (new) | config | — | `deploy/run-local.sh` (`podman pod create -p ...`) | role-match (imperative → declarative translation) |
| `deploy/qwen-ebook-tts.container` (new) | config | — | `deploy/run-local.sh` (TTS `podman run` block) | role-match |
| `deploy/qwen-ebook-backend.container` (new) | config | — | `deploy/run-local.sh` (backend `podman run` block) | role-match |
| `backend/app/db.py` self-check / `backend/app/cache_key.py` self-check (tests) | test | — | none exist yet (no `backend/tests/` dir found) — see "No Analog Found" | none |

## Pattern Assignments

### `backend/app/models.py` (model, CRUD) — modify

**Analog:** itself, lines 21-43 (`Character`, `Segment`)

**Field-versioning pattern to copy** (lines 30-34, `Character.voice_version`):
```python
    # Bumped on every PATCH that changes voice_preset/voice_instructions;
    # eager preview generation (Plan 02-04, Pitfall 5) only writes
    # preview_audio_path back if this still matches the version it started
    # with — last-request-wins under rapid re-assignment.
    voice_version: int = 0
```
Add the same shape to `Segment`: `generation_version: int = 0`, plus `generation_status: str = "pending"`, `generation_error: str | None = None`, `audio_path: str | None = None`, `cache_key: str | None = None`. Add `Project.created_at: datetime = Field(default_factory=datetime.utcnow)` (A3 in RESEARCH.md — needed for PERS-02's "date" column) and `Project.output_path: str | None = None` for the joined-output file.

**Docstring pattern** (lines 1-6): the module header currently says "D-02: no Phase 3 fields here" — update this comment when adding fields since it will otherwise mislead future readers.

---

### `backend/app/cache_key.py` (utility, transform) — new

**Analog:** `backend/app/token_estimate.py` (13 lines, pure function, stdlib only)
```python
# backend/app/token_estimate.py — the whole file, for shape reference
def estimate_tokens(text: str) -> int:
    ...
```
Same shape: no class, one pure function (`compute_cache_key`), stdlib-only import (`hashlib`), a short module docstring. RESEARCH.md Pattern 4 (lines 276-303) has the exact function body to use verbatim — `hashlib.sha256(payload).hexdigest()` over `\x1f`-joined fields, plus the `TTS_MODEL_VERSION` constant.

---

### `backend/app/generation_worker.py` (service, event-driven/batch) — new

**Analog:** `backend/app/analysis_worker.py` (full file, 235 lines)

**Imports pattern** (lines 9-24):
```python
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator

from sqlmodel import Session

from app.config import settings
from app.db import engine
from app.models import Character, Project, Segment
```

**Progress-queue registry pattern** (lines 28-60, `_progress_queues`/`_get_queue`/`has_pending_queue`/`progress_events`) — copy verbatim, just keyed the same way (per-project) or per-segment if the plan wants finer granularity; this exact registry + drain-until-terminal-event shape is what `main.py`'s `analysis_stream` SSE endpoint already consumes.

**Terminal-status persistence pattern** (lines 198-236, `run_analysis`) — copy the try/except-with-queue.put shape:
```python
async def run_analysis(project_id: str) -> None:
    queue = _get_queue(project_id)
    try:
        ...
        await queue.put(("done", {"status": "ready"}))
    except Exception as exc:
        with Session(engine) as session:
            project = session.get(Project, project_id)
            if project is not None:
                project.status = "error"
                project.error_detail = str(exc)
                session.add(project)
                session.commit()
        await queue.put(("error", {"detail": str(exc)}))
```
`generation_worker.run_batch_generation` follows the same try/except/queue.put("done"|"error") skeleton, but per-segment errors must `continue` rather than raise (GEN-05, RESEARCH.md Pattern 5) — see RESEARCH.md's full `run_batch_generation` code block (lines 310-365) for the exact loop body to adapt, including the stale-`"generating"`-row reset at the top (Pitfall 1).

**Error handling for a background task** (CLAUDE.md convention): every `except Exception` in this file must call `logger.exception(...)`, matching `analysis_worker.py`'s own convention (implicit — no bare `except: pass` anywhere in that file) and `main.py`'s `_generate_preview` (line 336, `logger.exception(f"preview generation failed for character {character_id}")`).

---

### `backend/app/main.py` (controller/route, request-response + streaming) — modify

**Analog:** itself — `patch_character`/`_generate_preview` (lines 254-361) is the direct precedent for the new `PATCH /segments/{id}` + regenerate-on-blur flow; `analysis_stream` (lines 220-245) is the direct precedent for the new generation-stream SSE route; `get_project`/`_serialize_project` (lines 149-203) is the read-shape precedent for the new `GET /projects` list route.

**Auto-regen-on-blur pattern** (lines 261-296, `patch_character`) — copy this exact shape for `patch_segment`:
```python
class CharacterPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    voice_preset: str | None = None
    voice_instructions: str | None = None


@app.patch("/characters/{character_id}")
async def patch_character(character_id: str, patch: CharacterPatch) -> dict:
    voice_changed = patch.voice_preset is not None or patch.voice_instructions is not None

    with Session(engine) as session:
        character = session.get(Character, character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Character not found")
        if patch.name is not None:
            character.name = patch.name
        ...
        if voice_changed:
            character.voice_version += 1
        session.add(character)
        session.commit()
        session.refresh(character)
        result = _serialize_character(character)
        version = character.voice_version

    if voice_changed:
        task = asyncio.create_task(_generate_preview(character_id, version))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return result
```
RESEARCH.md Pattern 3 (lines 252-274) already adapts this exact shape to `patch_segment`/`regenerate_segment` — use that as the literal starting point; bump `generation_version` instead of `voice_version`.

**Last-request-wins race guard** (lines 299-360, `_generate_preview`) — the direct precedent for `regenerate_segment`'s "only write back if version still matches" guard:
```python
    with Session(engine) as session:
        character = session.get(Character, character_id)
        if character is None or character.voice_version != version:
            preview_path.unlink(missing_ok=True)
            return
        old_path = character.preview_audio_path
        character.preview_audio_path = str(preview_path)
        session.add(character)
        session.commit()
    if old_path and old_path != str(preview_path):
        Path(old_path).unlink(missing_ok=True)
```

**SSE route pattern** (lines 220-245, `analysis_stream`) — copy verbatim shape for `GET /projects/{id}/generation-stream`, including the `_require_project_exists` dependency pattern (lines 205-217) for the 404-before-generator-entry trick, and the "already terminal, no pending queue" fast path (lines 237-242).

**Background task bookkeeping** (line 54, `_background_tasks: set[asyncio.Task] = set()`) — reuse the same module-level set for batch-generation tasks; no new registry needed.

**List-endpoint pattern** (lines 189-202, `get_project`) — adapt for `GET /projects`:
```python
@app.get("/projects/{project_id}")
async def get_project(project_id: str):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        ...
        return _serialize_project(project, characters, segments)
```
RESEARCH.md Pattern 6 (lines 372-382) has the exact `list_projects` body.

**Bulk-reassign validation precedent** — `merge_character` (lines 398-458) already validates cross-project ownership (`source.project_id != target.project_id`, line 413); the new bulk-reassign endpoint must apply the identical discipline (every segment id's `project_id` must match the target character's `project_id`) per RESEARCH.md's Security Domain table.

---

### `backend/app/db.py` (config) — modify

**Analog:** itself, lines 15-19
```python
engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
```
Add `PRAGMA journal_mode=WAL` + `busy_timeout` per RESEARCH.md Pitfall 5 — SQLModel/SQLAlchemy convention is an `event.listens_for(engine, "connect")` handler executing `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;` on each new connection. No existing in-repo analog for a pragma listener; this is the one genuinely new snippet in this file — keep it small (a single `_set_sqlite_pragma` function) matching the file's existing terse, single-purpose style (whole file is 29 lines).

---

### `frontend/src/components/SegmentTable.tsx` (component, CRUD editable grid) — new

**Analog:** `frontend/src/components/SegmentPreview.tsx` (full file, 93 lines) — its own docstring (lines 36-38) explicitly names this file as the precedent to extend: *"D-15: read-only preview only ... The full editable segment table is Phase 3's TBL-01..04, not this phase's scope."*

**Imports/table setup pattern** (lines 1-23):
```tsx
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { useMemo } from "react"

import type { Segment } from "@/api/client"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"

const columnHelper = createColumnHelper<Segment>()
```

**Column/render pattern** (lines 25-49, 51-93) — same `columnHelper.accessor`/`table.getHeaderGroups()`/`flexRender` shape; add `columnHelper.display({id: "select", ...})` per RESEARCH.md Pattern 2 for the checkbox column, and swap the plain `header`/text-only cells for editable-cell renderers per RESEARCH.md Pattern 1 (`meta.updateData` + local `useState` + `onBlur` commit).

**Blur-commit cell pattern to copy** (from `CharacterCard.tsx`, not `SegmentPreview.tsx` — see below) applies per-cell here.

---

### `frontend/src/components/ConfigPanel.tsx` (component, request-response) — new

**Analog:** `frontend/src/components/CharacterCard.tsx` (full file, 251 lines)

**Blur-commit text field pattern** (lines 51-54, 60-70, 77-85):
```tsx
  const [voiceInstructions, setVoiceInstructions] = useState(
    character.voice_instructions
  )
  ...
  function handleVoiceInstructionsBlur() {
    if (voiceInstructions !== character.voice_instructions) {
      void saveField({ voice_instructions: voiceInstructions })
    }
  }
```
This is the exact pattern RESEARCH.md Pattern 1/3 says the table's editable cells and CFG-02's character list should both reuse — no new blur-commit convention needed, just re-point `saveField` at the new PATCH endpoint.

**Play/pause preview pattern** (lines 92-100, 170-196) — reuse verbatim for CFG-02's per-segment or per-character audio preview control:
```tsx
  function togglePlayback() {
    const audio = audioRef.current
    if (!audio) return
    if (isPlaying) {
      audio.pause()
    } else {
      void audio.play()
    }
  }
  ...
  <audio
    ref={audioRef}
    src={previewUrl(character.id)}
    onPlay={() => setIsPlaying(true)}
    onPause={() => setIsPlaying(false)}
    onEnded={() => setIsPlaying(false)}
  />
```

**Field-reset-on-id-change pattern** (lines 60-70) — copy this guard whenever a panel shows per-selection state that must not be clobbered by unrelated re-renders:
```tsx
  const characterIdRef = useRef(character.id)
  useEffect(() => {
    if (characterIdRef.current !== character.id) {
      characterIdRef.current = character.id
      setName(character.name)
      setVoiceInstructions(character.voice_instructions)
    }
  }, [character.id, character.name, character.voice_instructions])
```

---

### `frontend/src/components/ProjectListScreen.tsx` (component, request-response) — new

**Analog:** `frontend/src/components/UploadScreen.tsx` (screen-level component shape) — read this file directly when implementing; not excerpted here since RESEARCH.md doesn't specify its content and no line-level pattern beyond "simple fetch + list render + navigate on select" is needed. Follow `client.ts`'s existing fetch-wrapper convention (see below) for the `listProjects()` call this screen uses.

---

### `frontend/src/hooks/useGenerationStream.ts` (hook, streaming SSE) — new

**Analog:** `frontend/src/hooks/useAnalysisStream.ts` (full file, 101 lines)

**EventSource lifecycle pattern** (lines 38-90) — copy verbatim shape:
```tsx
  useEffect(() => {
    if (!projectId) return undefined
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState(initialState())

    const source = new EventSource(`/projects/${projectId}/analysis-stream`)
    sourceRef.current = source

    source.addEventListener("progress", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as AnalysisProgress
      setState((prev) => ({ ...prev, progress: payload }))
    })

    source.addEventListener("done", () => { ... .finally(() => source.close()) })

    source.addEventListener("error", (event) => {
      const messageEvent = event as MessageEvent
      if (!messageEvent.data) return  // transient network drop, not a real failure
      ...
      source.close()
    })

    return () => {
      source.close()
      sourceRef.current = null
    }
  }, [projectId])
```
Re-point the URL at `/projects/{id}/generation-stream`; extend the `"progress"` payload shape to carry `{segment_id, n, total, status}` per RESEARCH.md Pattern 5's event schema instead of `AnalysisProgress`'s `{stage, n, total}`.

**Refetch-without-resubscribing helper pattern** (lines 94-101, `refreshProject`) — same shape for a `refreshSegmentStatus`/`refreshProject` helper this hook's consumers call after a non-SSE-driven PATCH.

---

### `frontend/src/api/client.ts` (utility/API layer, request-response) — modify

**Analog:** itself — every existing wrapper function is the pattern to replicate for new endpoints.

**Typed fetch wrapper pattern** (lines 71-78, 85-95, 97-107):
```ts
export async function patchCharacter(
  id: string,
  body: CharacterPatch
): Promise<Character> {
  const response = await fetch(`/characters/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  return parseJsonOrThrow(response)
}
```
Add `listProjects()`, `patchSegment(id, body)`, `generateSegment(id)`, `bulkReassignSegments(ids, characterId)`, `runBatchGeneration(projectId)` following this exact shape — one function per endpoint, `parseJsonOrThrow` reused unchanged (lines 60-69).

**Type interface pattern** (lines 5-58) — extend `Segment` with the new status/cache fields (`generation_status`, `generation_error`, `audio_path`) mirroring how `Character` already carries `preview_audio_path`/`voice_version` (lines 5-13); add a `SegmentPatch` interface mirroring `CharacterPatch` (lines 38-43).

---

### `deploy/qwen-ebook.pod` / `qwen-ebook-tts.container` / `qwen-ebook-backend.container` (config) — new

**Analog:** `deploy/run-local.sh` (full file, 106 lines) — the imperative commands these Quadlet units translate declaratively.

**Device-flag pattern to preserve exactly** (lines 70-78 of `run-local.sh`):
```bash
${PODMAN} run -d --pod "${POD_NAME}" --name "${POD_NAME}-tts" \
  --user 0:0 \
  --device /dev/kfd --device /dev/dri \
  ...
  -v "${HF_CACHE_VOLUME}:/home/ubuntu/.cache/huggingface" \
  "${TTS_IMAGE}"
```
Maps directly to `User=0`/`Group=0` + `AddDevice=/dev/kfd`/`AddDevice=/dev/dri` + `Volume=...` in `qwen-ebook-tts.container` — RESEARCH.md Pitfall 4 explicitly warns this exact flag set is the one most commonly dropped in a hand-translated Quadlet unit; use RESEARCH.md Pattern 7 (lines 384-440) as the literal `.pod`/`.container` file bodies, cross-checked line-by-line against `run-local.sh`'s `podman run` invocations (lines 73-84) so nothing is silently omitted.

**Port-publish pattern** (line 56, `${PODMAN} pod create --name "${POD_NAME}" -p "${BACKEND_HOST_PORT}:8000"`) — becomes `PublishPort=127.0.0.1:8000:8000` in the `.pod` unit (binding to loopback only, not `0.0.0.0`, per DEPL-02 + `tailscale serve`).

**Backend env-var pattern** (lines 81-84, `-e TTS_BACKEND=http -e TTS_SERVICE_URL=http://localhost:8001`) — becomes `Environment=TTS_BACKEND=http` / `Environment=TTS_SERVICE_URL=http://localhost:8001` in `qwen-ebook-backend.container`.

## Shared Patterns

### Blur-commit editing (no separate Save button)
**Source:** `frontend/src/components/CharacterCard.tsx` lines 51-85
**Apply to:** `SegmentTable.tsx`'s editable cells (Narrator/Voice Instructions/Text), `ConfigPanel.tsx`'s any editable fields.
```tsx
const [value, setValue] = useState(initialValue)
function handleBlur() {
  if (value !== initialValue) void saveField({ field: value })
}
```

### Last-request-wins version guard for background regeneration
**Source:** `backend/app/main.py` lines 282-283 (`voice_version` bump on PATCH) and lines 346-352 (`_generate_preview`'s version check before writing back)
**Apply to:** `patch_segment`'s `generation_version` bump + `regenerate_segment`'s "discard if version moved on" guard; `run_batch_generation`'s per-segment write must apply the same check (RESEARCH.md Pitfall 2) so a mid-batch edit isn't clobbered by a stale batch write or vice versa.

### Fire-and-forget background task bookkeeping
**Source:** `backend/app/main.py` line 54 (`_background_tasks: set[asyncio.Task] = set()`) + lines 142-144 (`task.add_done_callback(_background_tasks.discard)`)
**Apply to:** every new `asyncio.create_task(...)` call in `main.py` (per-row regen trigger, batch-generation trigger) — reuse the same module-level set, do not create a second one.

### SSE progress push
**Source:** `backend/app/analysis_worker.py` lines 28-60 (queue registry) + `backend/app/main.py` lines 220-245 (`analysis_stream` endpoint) + `frontend/src/hooks/useAnalysisStream.ts` (client subscriber)
**Apply to:** `generation_worker.py`'s progress queue + new `/projects/{id}/generation-stream` route + `useGenerationStream.ts`. Exact event schema is open (RESEARCH.md Claude's Discretion) but the queue/drain/terminal-event mechanics should be copied unchanged.

### Server-generated file identifiers, never client-derived
**Source:** `backend/app/main.py` line 343 (`preview_path = preview_dir / f"{uuid.uuid4().hex}.wav"`), line 130 (`project_id = uuid.uuid4().hex`)
**Apply to:** `generation_worker.py`'s per-segment `.wav` output paths and the joined-output file path — never derive a filename from `Segment.text` or any client-supplied string (Security Domain, T-02-10 convention).

### Broad-except + `logger.exception` in background tasks
**Source:** `backend/app/main.py` lines 330-337 (`_generate_preview`'s `except Exception: logger.exception(...)`)
**Apply to:** `generation_worker.py`'s per-segment synth failure handling (must not crash the batch loop, per GEN-05 + CLAUDE.md's logging convention) and any fire-and-forget regen task in `main.py`.

### Cross-project ownership validation
**Source:** `backend/app/main.py` line 413 (`merge_character`'s `source.project_id != target.project_id` check)
**Apply to:** the new bulk-reassign endpoint — every segment id in the request body must belong to the same `project_id` as the target character before applying the reassignment (RESEARCH.md Security Domain).

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `backend/tests/test_cache_key.py` (or equivalent self-check) | test | transform | No `backend/tests/` directory exists yet in this repo — RESEARCH.md and prior phases have no test-file precedent to copy from. Follow CLAUDE.md's test-file `noqa` leniency conventions and keep it a plain `assert`-based script/pytest function, no fixtures/framework scaffolding, per ponytail guidance ("smallest thing that fails if the logic breaks"). |
| `backend/app/db.py`'s WAL pragma listener | config | — | No existing SQLAlchemy `event.listens_for` usage anywhere in the codebase to copy from; this is standard SQLAlchemy/SQLite boilerplate (well-documented externally), not a project-specific pattern — implement directly from SQLAlchemy's own docs rather than an in-repo analog. |

## Metadata

**Analog search scope:** `backend/app/`, `frontend/src/components/`, `frontend/src/hooks/`, `frontend/src/api/`, `deploy/`
**Files scanned:** 13 backend modules, 6 frontend components/hooks/api files, 3 deploy scripts
**Pattern extraction date:** 2026-07-11
