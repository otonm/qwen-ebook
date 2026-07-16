---
phase: 04-immediate-cancellation
plan: 03
subsystem: api
tags: [fastapi, asyncio, anyio, tts-service, cancellation, generation-lock]

# Dependency graph
requires:
  - phase: 04-immediate-cancellation
    provides: "POST /cancel on tts_service (202/499), tts_client.cancel() best-effort HTTP call (04-02)"
provides:
  - "label-keyed generation task registry (register_generation_task/get_generation_task_by_label/is_generation_running_by_label) in generation_worker.py, generalized from the old project_id-only _running_generations"
  - "POST /segments/{id}/generate is now fire-and-return 202 {\"status\":\"generating\"}, registered under segment:{id} — no longer awaits regenerate_segment inline"
  - "POST /segments/{segment_id}/generate/cancel — true-kill cancel for a single segment, resets a stopped row to \"pending\" (never \"error\")"
  - "POST /characters/{character_id}/preview/cancel — true-kill cancel for a character preview"
  - "POST /projects/{id}/generate/cancel extended to also call tts_client.cancel() so the in-flight segment aborts, not just the queue"
  - "generation_worker.request_stop/consume_stop_requested/is_stop_requested — label-keyed stop-request flags that replace task.cancel() as the cancellation signal (see key-decisions)"
affects: [04-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cancel handlers never call task.cancel() on a task awaiting run_in_threadpool — only tts_client.cancel() (the real interrupt) followed by a plain `await task`, so the lock/loop only advances once the underlying call has genuinely finished"
    - "A label-keyed 'stop requested' flag set (generation_worker._stop_requested) replaces raw asyncio task cancellation as the signal a long-running loop (run_batch_generation) or a synth-failure handler (regenerate_segment) checks to distinguish a user-requested stop from a genuine error"

key-files:
  created:
    - backend/tests/test_immediate_cancel.py
  modified:
    - backend/app/generation_worker.py
    - backend/app/main.py
    - backend/tests/test_generation.py
    - backend/tests/test_generation_lock.py

key-decisions:
  - "Cancel handlers do NOT call task.cancel(): empirically verified (two isolated repros plus this plan's own hold-until-stopped test) that cancelling an asyncio Task awaiting starlette's run_in_threadpool (anyio to_thread) does not wait for the underlying worker thread — the await unblocks in ~50 microseconds while the real call keeps running detached for its full duration. Calling task.cancel() would therefore release the generation lock (via the done-callback) the instant cancel() is issued, violating the plan's own must_haves truth verbatim (\"never released merely because task.cancel() was issued\") and Pitfall 2. Fixed by calling tts_client.cancel() (the real interrupt) then plainly `await`ing the task to its true completion."
  - "run_batch_generation's 'stop the loop' signal moved from asyncio-level cancellation to a checked flag (consume_stop_requested, polled at the top of each loop iteration) — the one remaining case with a \"next item\" to skip once task.cancel() could no longer be used for that purpose."
  - "regenerate_segment's except-Exception branch now distinguishes a cancel-caused synth failure from a genuine error by peeking/consuming the same stop-request flags, writing status=\"pending\"/error=None instead of status=\"error\" — required because the cancel handlers no longer force-cancel the task, so regenerate_segment's own exception handling always runs to completion first (there is no longer a window where the row is caught mid-flight at \"generating\")."
  - "The segment cancel handler's post-await DB reset was broadened from \"if generation_status == 'generating'\" to \"if generation_status != 'complete'\" for the same reason — the row will already show a terminal status (usually \"error\", now correctly redirected to \"pending\" by regenerate_segment itself) by the time control returns to the handler, not \"generating\"."

patterns-established:
  - "A test's mock synthesize simulating an in-flight GPU call must be genuinely interruptible (poll a threading.Event) to meaningfully test a cancel path — an unconditional time.sleep() cannot honor an interrupt at all, so a test built against one can only prove the wrong thing (either that cancel does nothing, or — worse, if the handler forcibly cancels the task — that the lock releases prematurely without the underlying call actually having stopped)."

requirements-completed: [GEN-06, GEN-07, GEN-08]

coverage:
  - id: D1
    description: "POST /segments/{id}/generate is now fire-and-return 202 registered under segment:{id}, making it addressable for a cancel endpoint (GEN-06 prerequisite, Pitfall 3)"
    requirement: "GEN-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py::test_generate_segment_produces_audio"
        status: pass
      - kind: other
        ref: "grep -n 'status_code=202' backend/app/main.py (generate_segment decorator)"
        status: pass
    human_judgment: false
  - id: D2
    description: "POST /segments/{id}/generate/cancel and POST /characters/{id}/preview/cancel both call tts_client.cancel() and stop the local task, resetting the affected row to a clean non-error state"
    requirement: "GEN-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_immediate_cancel.py::test_segment_cancel_true_kills_and_resets_to_pending"
        status: pass
      - kind: unit
        ref: "backend/tests/test_immediate_cancel.py::test_preview_cancel_true_kills_and_releases_lock"
        status: pass
      - kind: unit
        ref: "backend/tests/test_immediate_cancel.py::test_segment_cancel_when_nothing_running_is_noop"
        status: pass
      - kind: unit
        ref: "backend/tests/test_immediate_cancel.py::test_preview_cancel_when_nothing_running_is_noop"
        status: pass
    human_judgment: false
  - id: D3
    description: "POST /projects/{id}/generate/cancel (batch) additionally calls tts_client.cancel() so the currently-synthesizing segment aborts, not just the queue"
    requirement: "GEN-08"
    verification:
      - kind: unit
        ref: "backend/tests/test_immediate_cancel.py::test_batch_cancel_true_kills_in_flight_segment"
        status: pass
      - kind: unit
        ref: "backend/tests/test_generation_lock.py::test_lock_releases_after_batch_cancel"
        status: pass
    human_judgment: false
  - id: D4
    description: "The global generation lock stays held until the underlying call has actually returned, never released merely because task.cancel() was issued (Pitfall 2)"
    requirement: "GEN-06"
    verification:
      - kind: unit
        ref: "backend/tests/test_immediate_cancel.py::test_lock_stays_active_until_cancel_settles"
        status: pass
    human_judgment: false
---

# Phase 4 Plan 3: Addressable, Cancellable Generation Tasks + True-Kill Cancel Endpoints Summary

**Segment generate flips from a synchronous 200-with-body call to a fire-and-return 202 registered in a label-keyed task registry; three new/extended cancel endpoints (segment, character preview, batch) each call the real `tts_client.cancel()` interrupt and hold the generation lock until the underlying call has genuinely finished — discovered along the way that `task.cancel()` on a thread-pooled call does NOT wait for the real work, and replaced it with a checked stop-request flag instead.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-07-13T16:45:00Z (approx, first task commit `b9be90e` at 16:51:12Z)
- **Completed:** 2026-07-13T17:09:30Z
- **Tasks:** 3/3
- **Files modified:** 5 (2 source, 2 fixed existing tests, 1 new test file)

## Accomplishments

- `generation_worker._running_generations` generalized from a `project_id`-keyed dict to a label-keyed one (`segment:{id}`/`preview:{id}`/`batch:{id}`), with `register_generation_task`/`get_generation_task_by_label`/`is_generation_running_by_label` helpers; `is_generation_running`/`get_generation_task` retained as back-compat delegates to the `batch:{id}` label.
- `POST /segments/{id}/generate` converted to fire-and-return 202 `{"status":"generating"}`, spawning `regenerate_segment` via `_spawn_claimed_generation` (now label-aware) and registering under `segment:{id}` — mirrors the existing `trigger_character_preview` pattern. **Contract change for 04-04**: no more synchronous segment body in the response.
- New `POST /segments/{segment_id}/generate/cancel` and `POST /characters/{character_id}/preview/cancel`: resolve the task via `get_generation_task_by_label`, call `tts_client.cancel()` (the true GPU-call kill from 04-02), then wait for the task to genuinely finish. A stopped segment row settles to `"pending"` (never `"error"`).
- Existing batch `cancel_generation` extended to also call `tts_client.cancel()` so the currently-synthesizing segment is actually killed (D-01), not just the queue of remaining segments; its superseded `ponytail:` ceiling comment removed.
- **Mid-implementation correctness finding**: empirically proved that `task.cancel()` on a Task awaiting `run_in_threadpool` does not wait for the underlying worker thread — see Deviations below. Fixed by never calling `task.cancel()` in any cancel handler, adding a label-keyed stop-request-flag mechanism instead, and updating `regenerate_segment`/`run_batch_generation` to consult it.
- `backend/tests/test_immediate_cancel.py` (new, 8 tests): segment/preview/batch true-kill coverage plus a dedicated hold-until-stopped test that runs the cancel call on a background thread and polls `/generation-status` concurrently to prove the lock stays `active: true` for the call's full real duration.

## Task Commits

Each task was committed atomically:

1. **Task 1: Generalize the task registry to be label-keyed with lookup helpers** - `b9be90e` (feat)
2. **Task 2: Segment generate becomes async 202 + three cancel behaviors + hold-lock-until-stopped** - `559cd56` (feat)
   - Rule 1 fix (existing tests broken by the intentional 202 contract change) - `19a47cd` (fix)
3. **Task 3: Regression tests for immediate, true-kill cancellation across all three paths** - `32e2539` (test) — bundled with the Rule 1/Rule 2 fix for premature lock release discovered while writing this task's hold-until-stopped test (see Deviations)

**Plan metadata:** this commit (docs: complete plan)

## Files Created/Modified

- `backend/app/generation_worker.py` - label-keyed `_running_generations`; `register_generation_task`/`get_generation_task_by_label`/`is_generation_running_by_label`; `is_generation_running`/`get_generation_task` back-compat delegates; new `request_stop`/`consume_stop_requested`/`is_stop_requested` stop-flag mechanism; `run_batch_generation`'s loop checks `consume_stop_requested` at the top of each iteration instead of relying on `task.cancel()`
- `backend/app/main.py` - `generate_segment` is now async 202, registered under `segment:{id}`; `_spawn_claimed_generation` takes a `label` and registers/deregisters the task; new `POST /segments/{segment_id}/generate/cancel` and `POST /characters/{character_id}/preview/cancel`; `cancel_generation` (batch) extended with `tts_client.cancel()` and `request_stop`; `regenerate_segment`'s except-Exception branch distinguishes a cancel-caused failure from a genuine error
- `backend/tests/test_generation.py` - updated 7 call sites for the 202 contract (poll via `_wait_for_terminal` instead of reading the response body synchronously)
- `backend/tests/test_generation_lock.py` - updated 4 call sites for the 202 contract; added a trailing `_wait_for_idle()` at 3 sites where a leftover slow-monkeypatched background task could otherwise leak into the next test
- `backend/tests/test_immediate_cancel.py` (new) - 8 regression tests for the true-kill cancel contract across all three paths, plus the hold-until-stopped concurrency test

## Decisions Made

- **No `task.cancel()` in any cancel handler** (see Deviations — this is the plan's single largest deviation from its literal Task 2 instruction, made necessary by an empirically-verified anyio/starlette behavior, not a stylistic choice).
- **499 is not needed as a client-side signal for "was this cancelled"** — the backend distinguishes cancel-caused failures from genuine ones via its own `_stop_requested` flag set (checked in `regenerate_segment`), not by inspecting the exception's shape. This keeps the mechanism working identically whether the interrupt is real (server responds 499) or the best-effort `tts_client.cancel()` call itself failed and the underlying call just runs to its natural conclusion.
- **A row that races to a genuine `"complete"` success despite an in-flight cancel request is left alone**, not force-reset to `"pending"` — no reason to discard valid, already-written audio just because the user's stop request lost the race.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated `test_generation.py`/`test_generation_lock.py` for the segment-generate 202 contract change**
- **Found during:** Task 2 (converting `generate_segment` to async 202)
- **Issue:** Both files asserted the old synchronous `200`-with-segment-body response from `POST /segments/{id}/generate`; several sites read the resulting row's fields immediately after the POST, which is no longer valid once the call returns before the background task runs.
- **Fix:** Updated status-code assertions to `202`; sites that need the resulting state now poll via `_wait_for_terminal`/`_wait_for_idle` first. Also found and fixed a latent test-isolation bug in `test_generation_lock.py`: three trailing generate calls reused a test's slow-monkeypatched `synthesize` and used to be synchronous (so their lock was released before the test returned) — made fire-and-return by this plan's contract change, the spawned task could now outlive the test and leak a held lock into the next one. Added a trailing `_wait_for_idle()` at each site.
- **Files modified:** `backend/tests/test_generation.py`, `backend/tests/test_generation_lock.py`
- **Verification:** Full backend suite green (87 passed, 1 skipped, 1 deselected pre-existing failure), 3 repeated runs of the affected files with no flakiness.
- **Committed in:** `19a47cd`

**2. [Rule 1 - Bug + Rule 2 - Missing Critical] `task.cancel()` releases the generation lock before the underlying call truly stops**
- **Found during:** Task 3, while writing `test_lock_stays_active_until_cancel_settles` (the plan's own required "hold-until-stopped" test)
- **Issue:** The plan's Task 2 literally specified `task.cancel()` + `await`-suppressing `CancelledError` for all three cancel handlers. Empirically verified (two isolated `asyncio.create_task`/`run_in_threadpool` repros, then the test itself failing) that cancelling a Task awaiting starlette's `run_in_threadpool` (anyio `to_thread.run_sync`, default `abandon_on_cancel=False`) does **not** wait for the underlying worker thread on this app's installed anyio/starlette versions — the `await task` call returns in ~50 microseconds while the real blocking call (`synthesize`) keeps running detached for its full duration. Since `_spawn_claimed_generation`'s done-callback releases the lock when the *task* transitions to done, this meant the lock was released the instant `task.cancel()` was issued — precisely the race the plan's own frontmatter `must_haves` truth forbids verbatim ("never released merely because task.cancel() was issued") and Pitfall 2 describes.
- **Fix:** Removed `task.cancel()` from all three cancel handlers. They now call `tts_client.cancel()` (the real, hardware-verified interrupt from 04-01/04-02) and then plainly `await task`, which only returns once the underlying call has genuinely finished — quickly if the interrupt landed, or after its full natural duration if it didn't. Since `run_batch_generation`'s loop still needs a way to stop advancing to the next segment (the one case with a "next item"), added a label-keyed stop-request flag (`request_stop`/`consume_stop_requested`/`is_stop_requested` in `generation_worker.py`) that the loop checks at the top of each iteration. `regenerate_segment`'s except-Exception branch also now peeks/consumes the same flags to distinguish a cancel-caused synth failure from a genuine error, writing `"pending"` instead of `"error"` — necessary because the handler no longer force-cancels the task, so `regenerate_segment` always runs its own exception handling to completion first (there's no longer a window where the row is caught mid-flight at `"generating"`). `delete_project`'s unrelated, pre-existing `task.cancel()` usage (cleaning up a task when a project is being fully deleted) was left untouched — timing precision doesn't matter there since the rows are being deleted regardless.
- **Files modified:** `backend/app/generation_worker.py`, `backend/app/main.py`
- **Verification:** `test_lock_stays_active_until_cancel_settles` passes (runs the cancel call on a background thread, polls `/generation-status` concurrently, asserts `active: true` throughout the mock synth's full duration, `active: false` only after); full backend suite green; 3 repeated runs with no flakiness.
- **Committed in:** `32e2539` (bundled with Task 3's new test file, since the bug was discovered while writing that file's own required test)

---

**Total deviations:** 2 auto-fixed (1 Rule 1 test-contract fix, 1 Rule 1+2 correctness fix)
**Impact on plan:** Both fixes were necessary for the plan's own must_haves/acceptance criteria to actually hold — no scope creep beyond what Task 2's contract change and Task 3's required test demanded. The task.cancel() removal is a meaningful implementation change from the plan's literal wording but preserves 100% of its intent (true-kill via tts_client.cancel(), hold-until-stopped, clean reset-to-pending) — verified by the plan's own required test, which failed under the literal instruction and passes under the fix.

## Issues Encountered

None beyond the deviations above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All three generation paths (segment, character preview, batch) are now addressable and cancellable with a hardware-honest true-kill contract; the lock is provably held until the underlying call is confirmed stopped.
- **04-04 (frontend) must account for the segment-generate contract change**: `POST /segments/{id}/generate` now returns `202 {"status":"generating"}` instead of `200` with the segment body — the frontend's `generateSegment()` call site needs to switch from await-for-result to await-202-then-poll (matching the existing character-preview and batch patterns already used elsewhere in the codebase).
- 04-04 can wire the three cancel endpoints directly: `POST /segments/{id}/generate/cancel`, `POST /characters/{id}/preview/cancel`, and the extended `POST /projects/{id}/generate/cancel` — each already returns `{"status": "cancelled"}` or `{"status": "not_running"}`.
- No blockers for 04-04.

---
*Phase: 04-immediate-cancellation*
*Completed: 2026-07-13*

## Self-Check: PASSED

All created/modified files confirmed present on disk; all task commit hashes
(`b9be90e`, `559cd56`, `19a47cd`, `32e2539`) confirmed present in `git log`.
