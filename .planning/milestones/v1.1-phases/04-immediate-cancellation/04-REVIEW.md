---
phase: 04-immediate-cancellation
reviewed: 2026-07-14T07:08:43Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - backend/app/generation_worker.py
  - backend/app/main.py
  - backend/app/tts_client.py
  - backend/tests/test_cancel_machinery.py
  - backend/tests/test_generation.py
  - backend/tests/test_generation_lock.py
  - backend/tests/test_immediate_cancel.py
  - backend/tests/test_tts_client_cancel.py
  - backend/tts_service/model.py
  - backend/tts_service/server.py
  - backend/tts_service/spike_cancel_hw.py
  - frontend/src/api/client.ts
  - frontend/src/components/ConfigPanel.tsx
  - frontend/src/components/ProjectScreen.tsx
  - frontend/src/components/SegmentTable.tsx
  - frontend/src/hooks/useGenerationStream.ts
findings:
  critical: 1
  warning: 7
  info: 3
  total: 11
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-07-14T07:08:43Z
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

The core true-kill cancellation machinery (`generation_worker.py`'s
`_stop_requested`/single-flight lock, `tts_client.cancel()`,
`tts_service/model.py`'s `_CancelStoppingCriteria` patch onto
`talker.generate`, and the three cancel endpoints in `main.py`) is carefully
reasoned and its "never release the lock via `task.cancel()`, only via the
task's own done-callback once the real call has finished" invariant is
consistently documented and enforced everywhere — except one place:
`delete_project` still uses the old raw `task.cancel()` mechanism, and its
own docstring's justification for that exception doesn't hold up under
scrutiny (CR-01 below) — it reintroduces exactly the two-concurrent-GPU-call
race this entire phase exists to prevent.

Beyond that, review surfaced a genuinely dead `stopping_criteria` kwarg in
`tts_service/model.py` (contradicted by the file's own adjacent comment), a
narrow error-masking race in the segment cancel handler, duplicated
task-lifecycle code in `main.py`, and several frontend issues: a stale-status
overlay bug that can show "Complete" on a segment that was just edited and
invalidated, polling ceilings shorter than the backend's own allowed
synthesis duration, and a cluster of async handlers with no `catch`,
producing unhandled promise rejections and silent failures instead of
user-facing errors.

## Critical Issues

### CR-01: `delete_project` uses raw `task.cancel()`, which can orphan a live GPU synthesis call and let a new generation start concurrently

**File:** `backend/app/main.py:284-328` (specifically the cancel at lines 306-310)

**Issue:** Every other cancel path in this phase (`cancel_segment_generation`,
`cancel_character_preview`, `cancel_generation`) deliberately avoids
`task.cancel()` because — per this same codebase's own extensively-documented
finding in `generation_worker.py:81-101` — cancelling an asyncio `Task` that's
awaiting `run_in_threadpool` does **not** wait for the underlying worker
thread to finish: the `await` unblocks almost immediately while the real
`synthesize()` call (an httpx POST to `tts_service`, or, on real hardware, an
in-flight ROCm decode) keeps running **detached** in the background thread.
Every other cancel handler therefore does `request_stop()` +
`tts_client.cancel()` (the real interrupt) + a plain `await task`, so the
task's done-callback — and therefore `release_generation()` — only fires once
the underlying call has *actually* finished.

`delete_project` breaks this discipline:

```python
task = get_generation_task(project_id)
if task is not None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
```

`task.cancel()` here causes `run_batch_generation` to unwind almost
instantly (the `await run_in_threadpool(synthesize, ...)` inside
`regenerate_segment` raises `CancelledError`, which — being a
`BaseException`, not an `Exception` — passes straight through both
`regenerate_segment`'s and `run_batch_generation`'s `except Exception`
blocks). The task's done-callback then fires and calls
`release_generation()` immediately — **while the real orphaned
`synthesize()` call for the segment that was mid-flight keeps running on the
GPU**, since `tts_client.cancel()` (the actual interrupt) is never invoked on
this path.

The global lock is released the instant `task.cancel()` returns, not once
the real GPU call is done — so a *second, unrelated* generation request
(e.g. a batch run started for a different project, or an automatic
best-effort preview regen after `undo_merge_character`) can immediately
claim the now-free lock and fire its own `/synthesize` call while the
orphaned call from the deleted project is still executing. Per
`generation_worker.py`'s own comment, `tts_service/server.py`'s
`/synthesize` "has no concurrency control of its own (a bare
`run_in_threadpool` with no lock or queue)" — two uncoordinated calls into
the same resident model instance on a single 16GB-VRAM GPU (CLAUDE.md's
hardware constraint) risk VRAM exhaustion or corrupted output from two
concurrent forward passes sharing the same process-wide `_cancel_event`
(`tts_service/model.py:61`).

The docstring's justification ("acceptable there because the project and
its rows are being deleted regardless of exactly when the lock frees") only
considers the deleted project's own data — it doesn't account for the
orphaned thread racing a subsequent, unrelated generation once the lock is
freed early.

**Fix:** Use the same true-kill sequence as the other cancel handlers,
before deleting rows/files (which is still safe — segments still exist in
the DB while `await task` is pending):

```python
task = get_generation_task(project_id)
if task is not None:
    request_stop(f"batch:{project_id}")
    await run_in_threadpool(tts_client.cancel)
    with contextlib.suppress(asyncio.CancelledError):
        await task
```

## Warnings

### WR-01: `cancel_segment_generation`'s blanket status reset can mask a genuine unrelated error as "cancelled"

**File:** `backend/app/main.py:1001-1022` (reset at lines 1014-1020)

**Issue:** `get_generation_task_by_label` returns a task even after it has
completed, until its done-callback has popped it from `_running_generations`
(a separate, later step scheduled via `asyncio.Task.add_done_callback`, not
synchronous with the task finishing). If a segment's synthesis fails for a
genuinely unrelated reason (e.g. a network blip to `tts_service`) at the
exact moment a user clicks Stop, `cancel_segment_generation` can observe a
not-yet-reaped, already-`done()` task, then unconditionally overwrite the
row:

```python
if segment is not None and segment.generation_status != "complete":
    segment.generation_status = "pending"
    segment.generation_error = None
```

This resets *any* non-"complete" status to "pending" and clears
`generation_error`, regardless of whether the failure the row landed on was
actually caused by this cancel request. A real, unrelated failure is
silently reported to the user as a clean stop instead of surfacing as an
error.

**Fix:** Only apply the reset when the observed error was actually caused by
this request — e.g. gate it on `consume_stop_requested`/`is_stop_requested`
having genuinely fired for this label rather than on the row's terminal
status alone, or accept the current row's status when the task was already
`done()` before this handler's own `request_stop()`/`tts_client.cancel()`
call.

### WR-02: `tts_service/model.py`'s explicit `stopping_criteria` kwarg to `generate_custom_voice` is dead code

**File:** `backend/tts_service/model.py:190-206`

**Issue:** `synthesize_wav` passes its own `_CancelStoppingCriteria()`
instance directly into `generate_custom_voice(..., stopping_criteria=...)`:

```python
wavs, sample_rate = model.generate_custom_voice(
    text=text,
    speaker=chosen_speaker,
    instruct=...,
    stopping_criteria=StoppingCriteriaList([_CancelStoppingCriteria()]),
)
```

But the file's own adjacent comment (lines 102-120) documents, from reading
the installed `qwen-tts==0.1.1` wheel, that a `stopping_criteria` kwarg
passed into `generate_custom_voice(**kwargs)` is **silently dropped** before
it ever reaches the real decode loop — confirmed live on hardware ("an
unpatched `stopping_criteria` never interrupted generation"). That's
precisely why `model.model.talker.generate` is monkeypatched
(`_talker_generate_with_cancel`, which injects its *own*, separate
`_CancelStoppingCriteria()` instance via `kwargs.setdefault`) — that patched
call is the only one that actually matters.

The explicit `stopping_criteria=...` passed at the `generate_custom_voice`
call site therefore does nothing: it's dropped before reaching the talker,
and a second, different criteria instance (created inside the monkeypatch)
is what's actually checked. Leaving it in place misleads a future
maintainer into believing cancellation is wired through the public
`generate_custom_voice` call, when the entire mechanism actually depends on
the `talker.generate` patch holding.

**Fix:** Remove the dead kwarg from the `generate_custom_voice` call (or
add a comment explicitly stating it's a no-op left for forward-compatibility
with a future qwen-tts version that might start honoring it — the module
docstring already gestures at this reasoning for `kwargs.setdefault`, but
that reasoning belongs where the code that actually might use it is, not on
a call that's proven not to).

### WR-03: `main.py` reaches into `generation_worker`'s private `_running_generations` dict directly, and duplicates its cleanup logic

**File:** `backend/app/main.py:46-63, 95-99, 1111-1121`

**Issue:** `main.py` imports the underscore-prefixed, module-private
`_running_generations` dict from `generation_worker` and manipulates it
directly in two separate places instead of going through a public accessor:

```python
def _cleanup(completed_task: asyncio.Task) -> None:
    _background_tasks.discard(completed_task)
    if _running_generations.get(label) is completed_task:
        _running_generations.pop(label, None)
    release_generation()
```

This exact block (`_spawn_claimed_generation`, lines 95-99) is duplicated
almost verbatim in `generate_project` (lines 1115-1121), which builds its own
`asyncio.create_task`/`register_generation_task`/`add_done_callback` sequence
instead of calling `_spawn_claimed_generation` — the function that already
exists specifically to do this. Two independent implementations of the same
"deregister + release" contract mean a future change to the cleanup
semantics (e.g. adding logging, or fixing WR-01) has to be made in two
places, and a private module attribute is a two-way coupling that
`generation_worker.py` can't safely refactor without also checking
`main.py`.

**Fix:** Add a `deregister_generation_task(label, task)` helper to
`generation_worker.py` (encapsulating the `_running_generations.pop`
guard), and have `generate_project` call
`_spawn_claimed_generation(run_batch_generation(project_id), label)` after
`ensure_generation_queue(project_id)` instead of re-implementing task
creation/registration/cleanup inline.

### WR-04: Frontend polling ceilings (60s) are shorter than the backend's own allowed synthesis duration (300s)

**File:** `frontend/src/components/ConfigPanel.tsx:66-74`,
`frontend/src/components/SegmentTable.tsx:139-147`

**Issue:** Both `CharacterPreviewRow` and `GeneratePlayButton` poll
`onRefresh` every 1500ms while a generation they triggered is in flight, and
stop polling after a fixed 60-second ceiling:

```javascript
const interval = setInterval(onRefresh, 1500)
const timeout = setTimeout(() => clearInterval(interval), 60000)
```

But `tts_client.py`'s `synthesize()` uses `httpx.Timeout(..., read=300.0,
...)` — the backend explicitly allows up to 5 minutes for a single synth
call, and `CharacterPreviewRow`'s own comment even acknowledges "real GPU
synthesis can run well past a few seconds on a cold/idle-GPU downclock-
recovery spike ... a fresh TTS container's very first request measured ~38s
in production" — i.e. the authors already know real calls can approach this
ceiling. For any segment whose real generation genuinely takes longer than
60s (well within the backend's own allowed window, and plausible for longer
segments beyond the ~38s cold-start example), polling silently stops. There
is no SSE for per-row/preview generation, so nothing else will trigger a
refresh — the button/badge is left showing "Generating…" indefinitely even
though the backend eventually finishes successfully, with no automatic way
for the UI to notice. The only recovery is the user manually clicking Stop
(which happens to reset local state in its `finally` block) or reloading the
page.

**Fix:** Either raise the ceiling to comfortably exceed the backend's real
timeout (e.g. 300s+), or — better — poll indefinitely while the row/character
is locally known to be "the one we triggered" and rely on the row's own
terminal `generation_status`/`preview_audio_path` to end polling, only
falling back to a hard ceiling as a last-resort safety net well above the
backend's own timeout.

### WR-05: `ProjectScreen`'s `liveSegments` overlay can show a stale status from a finished batch run instead of a freshly-edited segment's real status

**File:** `frontend/src/components/ProjectScreen.tsx:44-66`

**Issue:** `generation.segmentStatuses` (from `useGenerationStream`) is only
reset to `{}` when a *new* SSE connection is opened via `restart()`
(`useGenerationStream.ts:52-53`, keyed on `connectionKey`) — i.e. only when
`ConfigPanel.handleGenerateAll` starts a new batch. It is never cleared when
a batch's terminal "done" event arrives, nor when an individual segment is
edited via `patchSegment`.

`liveSegments` unconditionally prefers the stale overlay whenever it
differs from the segment's real, freshly-fetched status:

```javascript
const liveStatus = generation.segmentStatuses[segment.id]
return liveStatus && liveStatus !== segment.generation_status
  ? { ...segment, generation_status: liveStatus }
  : segment
```

Concrete repro: run a batch to completion (every touched segment's
`segmentStatuses[id]` settles at `"complete"`). Afterward, edit one of those
segments' text via `EditableTextCell` — `patch_segment` correctly flips its
real `generation_status` to `"pending"` and clears `audio_path` (GEN-03
invalidate-only), and `handleSegmentChange` updates `project.segments`
accordingly. But `generation.segmentStatuses[segment.id]` is still
`"complete"` from the earlier batch run (nothing ever cleared it), so
`liveSegments` overrides the freshly-patched `"pending"` status back to
`"complete"` for display — the `StatusBadge` shows "Complete" for a segment
that was just invalidated and has no audio, contradicting
`GeneratePlayButton`'s own `hasAudio` check (which correctly reads
`audio_path` from the same object, since only `generation_status` is
overridden) and producing an inconsistent, misleading UI (badge says
"Complete", Play button shows "Generate").

**Fix:** Clear (or otherwise invalidate) the relevant `segmentStatuses`
entry whenever a segment is locally patched (e.g. have
`handleSegmentChange` also drop that segment's id from the overlay), or
simplify by only trusting `segmentStatuses` while `generation.status ===
"running"`.

### WR-06: Several async event handlers omit error handling, producing unhandled promise rejections and no user-facing failure feedback

**File:** `frontend/src/components/ConfigPanel.tsx:96-109, 218-241`;
`frontend/src/components/SegmentTable.tsx:185-199, 263-266, 312-315,
344-353`

**Issue:** A cluster of handlers wrap their API call in `try { ... } finally
{ ... }` with no `catch`, or call the API with no error handling at all
(`.then(onSegmentChange)` and no `.catch`) — e.g.:

```javascript
// ConfigPanel.tsx handleStop
async function handleStop() {
  setIsCancelling(true)
  try {
    await cancelBatchGeneration(project.id)
    onRefresh()
  } finally {
    setIsCancelling(false)
  }
}
```

```javascript
// SegmentTable.tsx NarratorCell
function handleChange(value: string) {
  if (value === segment.character_id) return
  void patchSegment(segment.id, { character_id: value }).then(onSegmentChange)
}
```

If the underlying `fetch` throws (network failure) or `parseJsonOrThrow`
rejects (a non-2xx backend response, e.g. a 409/404/500), the promise
rejects with no handler attached anywhere in the chain — this surfaces only
as an "Uncaught (in promise)" console warning, with the loading flag reset
(where `finally` exists) but zero feedback to the user about *why* their
Stop/Reassign/Narrator-change/Edit action silently did nothing. This
pattern repeats across `handleStopPreview`, `handleStop` (both
`ConfigPanel`/`SegmentTable`), `BulkReassignToolbar.handleConfirm`,
`NarratorCell.handleChange`, and `EditableTextCell.handleBlur`.

**Fix:** Add a `.catch`/`catch` at each of these call sites (even a minimal
one — log + surface a toast/inline error) so API failures are visible to
the user instead of only appearing in devtools.

### WR-07: `ProjectScreen.refetch()` discards already-loaded project state on any transient fetch failure

**File:** `frontend/src/components/ProjectScreen.tsx:27-29`

**Issue:**

```javascript
const refetch = useCallback(() => {
  getProject(projectId).then(setProject).catch(() => setProject(null))
}, [projectId])
```

`refetch` is called not just on initial mount but after every
generate/cancel/reassign action (`onRefresh` throughout `ConfigPanel` and
`SegmentTable`) and whenever `generation.status` reaches a terminal value.
Any transient failure of this call (a momentary network blip, a backend
restart mid-request) sets `project` to `null`, which unconditionally renders
the full-page "Loading project…" state with no error message and no retry —
discarding whatever was already successfully loaded and displayed, even
though the project itself is fine and the next successful poll would have
recovered on its own.

**Fix:** On failure, keep the previous `project` state (don't null it out)
and surface a transient error indicator instead, e.g.
`.catch(() => { /* log + show inline error banner */ })` without touching
`setProject`.

## Info

### IN-01: `refreshSegments` is unused dead code

**File:** `frontend/src/hooks/useGenerationStream.ts:99-105`

**Issue:** `refreshSegments` is exported but has no callers anywhere in
`frontend/src` (verified via repo-wide grep).

**Fix:** Remove it, or wire it in wherever it was intended to replace a
direct `getProject(...).then((p) => p.segments)` call.

### IN-02: Poll-ceiling magic number `60000` duplicated with no shared constant

**File:** `frontend/src/components/ConfigPanel.tsx:69`;
`frontend/src/components/SegmentTable.tsx:142`

**Issue:** The same `60000` (ms) polling ceiling appears in two unrelated
components with no shared constant, so a future change to the ceiling (see
WR-04) has to be made in two places and can silently drift out of sync.

**Fix:** Extract a shared `GENERATION_POLL_CEILING_MS` constant (e.g. in
`api/client.ts` alongside the related type definitions) and import it in
both components.

### IN-03: `handleGenerateAll` silently ignores "busy"/"already_running" responses

**File:** `frontend/src/components/ConfigPanel.tsx:218-231`

**Issue:** `runBatchGeneration` always resolves successfully for a 202
response, even when the backend's `status` field is `"busy"` or
`"already_running"` (i.e. the batch did **not** actually start). The handler
ignores that field entirely and unconditionally calls `generation.restart()`
— since `generationLocked` is only updated via a separate poll, a user can
click "Generate All" in the narrow window right after another generation
grabs the global lock elsewhere; the button briefly spins, then reverts to
"Generate All" with no explanation of why nothing happened.

**Fix:** Check `response.status` and surface a brief message (e.g. "Another
generation is already running") when it isn't `"started"`.

---

_Reviewed: 2026-07-14T07:08:43Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
