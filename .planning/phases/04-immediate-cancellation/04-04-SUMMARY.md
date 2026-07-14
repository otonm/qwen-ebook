---
phase: 04-immediate-cancellation
plan: 04
subsystem: frontend
tags: [react, sse, generation-stream, cancellation, ui]

# Dependency graph
requires:
  - phase: 04-immediate-cancellation
    provides: "async 202 segment generate + three true-kill cancel endpoints (04-03): POST /segments/{id}/generate/cancel, POST /characters/{id}/preview/cancel, extended POST /projects/{id}/generate/cancel"
provides:
  - "generateSegment() 202+poll contract, cancelSegmentGeneration(), cancelCharacterPreview() in api/client.ts"
  - "bare-bones Stop + distinct idle/generating/stopping tri-state on segment rows (SegmentTable.tsx) and character-preview rows (ConfigPanel.tsx)"
  - "corrected D-06 batch Stop caveat copy: 'Stop interrupts the segment currently generating immediately.'"
  - "useGenerationStream.restart() — reopens the request-scoped generation-stream SSE connection on each Generate All click (see key-decisions)"
  - "generation_worker.ensure_generation_queue() — eagerly creates the progress queue before generate_project's handler returns, closing a race with the SSE reconnect"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A request-scoped SSE endpoint (drains one run's events, self-closes on terminal/empty) needs its frontend consumer to explicitly reconnect on every new trigger, not just on component mount — otherwise status can only ever reflect the first run"
    - "Local per-row transient UI state (isStopping/isGenerating) must be cleared in a finally block covering the success path, not just catch — an await that resolves without throwing still needs its own state reset, refetching alone does not clear component-local flags"

key-files:
  created: []
  modified:
    - frontend/src/api/client.ts
    - frontend/src/components/SegmentTable.tsx
    - frontend/src/components/ConfigPanel.tsx
    - frontend/src/components/ProjectScreen.tsx
    - frontend/src/hooks/useGenerationStream.ts
    - backend/app/generation_worker.py
    - backend/app/main.py

key-decisions:
  - "Task 4's checkpoint surfaced two real bugs during actual real-hardware verification, both fixed and re-verified before closing the plan: (1) the batch Generate All Stop button never reappeared past the first run this session, because useGenerationStream's EventSource opens once on mount while the backend's generation-stream endpoint is request-scoped and self-closes after each run's terminal event — generation.status could never report \"running\" again, so isBatchRunning stayed false and the Stop button never rendered even though the backend genuinely held the lock. Fixed by adding restart() to the hook (bumps a connectionKey the effect depends on) and calling it right after runBatchGeneration's POST resolves in ConfigPanel's handleGenerateAll. A companion backend fix (ensure_generation_queue, called synchronously in generate_project before the batch task is scheduled) closes a race where a same-tick SSE reconnect could still see \"nothing queued yet\" and self-close before the task's first progress event. (2) SegmentTable's handleStop only cleared isStopping in its catch block, so a *successful* cancelSegmentGeneration call left the row's local \"Stopping…\" state stuck — moved the reset into a finally block. This second fix was found already applied, uncommitted, in the worktree (likely from this same agent's own pre-checkpoint session) and was reviewed and committed as correct rather than discarded."
  - "The batch Stop bug was masking a separate, pre-existing, unrelated app-wide-lock UX gap: the Cast Review wizard (CastWizard.tsx/CharacterCard.tsx/SegmentPreview.tsx) has no stop mechanism at all for its own preview queue (per CONTEXT.md D-04, explicitly deferred to Phase 7) and no generate-all capability in SegmentPreview.tsx today. When that wizard's preview queue held the app-wide generation lock, the user had no way to interrupt it anywhere in the UI, twice requiring a service restart to unblock. This is out of scope for Phase 4 (never touched by this plan's files_modified) but is captured as backlog — see below."

patterns-established:
  - "Cross-referencing tts_service journal logs (request_cancel/talker.generate/vocoder decode timings) against the frontend's perceived \"slow stop\" complaint gave hard, verifiable numbers (10s and 34s across two real segment stops) rather than relying on subjective impression — confirmed the vocoder-tail-proportional-to-progress behavior from 04-01 was working as designed, not regressed, before concluding a bug existed elsewhere."

requirements-completed: [GEN-06, GEN-07, GEN-08]

coverage:
  - id: D1
    description: "generateSegment() awaits the 202 accept then the segment row polls onRefresh for completion, matching 04-03's async contract"
    requirement: "GEN-06"
    verification:
      - kind: unit
        ref: "frontend typecheck + lint clean"
        status: pass
      - kind: human
        ref: "real-hardware checkpoint: segment generate/stop cycle exercised against the live TTS container"
        status: pass
    human_judgment: true
  - id: D2
    description: "Segment row and character-preview row each show a bare-bones Stop control wired to the real cancel endpoints, with a distinct 'stopping…' state honoring D-03/D-05"
    requirement: "GEN-06, GEN-07"
    verification:
      - kind: human
        ref: "real-hardware checkpoint: both paths exercised; tts_service journal logs cross-referenced showing request_cancel -> talker.generate returns fast -> vocoder decode -> GenerationCancelled, 10-34s wall clock depending on how much was already generated (matches 04-01's documented vocoder-tail characteristic, not a regression)"
        status: pass
    human_judgment: true
  - id: D3
    description: "The batch Stop control interrupts the in-flight segment and the caveat copy no longer claims the current segment may still finish (D-06)"
    requirement: "GEN-08"
    verification:
      - kind: human
        ref: "real-hardware checkpoint, second pass after the Stop-button-never-reappears bug was found and fixed: Generate All -> Stop -> confirmed working"
        status: pass
    human_judgment: true
  - id: D4
    description: "Every Stop control's 'stopping…' state clears honestly once the backend confirms release, not on an instant optimistic flip and not stuck indefinitely"
    requirement: "GEN-06"
    verification:
      - kind: human
        ref: "real-hardware checkpoint, second pass after the isStopping-never-clears-on-success bug was found and fixed"
        status: pass
    human_judgment: true
---

# Phase 4 Plan 4: Frontend Stop Controls + D-01 Real-Hardware Checkpoint Summary

**Adapted the segment generate call site to 04-03's async 202+poll contract, added bare-bones Stop buttons with a distinct "stopping…" tri-state to segment rows and character-preview rows, fixed the now-false D-06 batch caveat copy — then, during the plan's own blocking real-hardware checkpoint, found and fixed two genuine bugs (a dead SSE reconnect that hid the batch Stop button past the first run, and a stuck "Stopping…" state on successful segment cancels) before the user could approve D-01's true-kill bar end-to-end.**

## Performance

- **Duration:** ~1h 45m from Task 1 commit to plan completion, including the async-mode checkpoint wait and the two post-checkpoint bug-fix rounds
- **Tasks:** 4/4 (Task 4's checkpoint required two fix-and-reverify cycles before approval)

## Accomplishments

- `frontend/src/api/client.ts`: `generateSegment()` return type changed to `Promise<{ status: string }>` (202 accept, no more synchronous segment body); added `cancelSegmentGeneration(id)` and `cancelCharacterPreview(id)`.
- `frontend/src/components/SegmentTable.tsx` + `ProjectScreen.tsx`: `onRefresh` threaded into `SegmentTable`; `GeneratePlayButton` polls after a 202 instead of awaiting a body; bare-bones Stop button; idle/generating/stopping tri-state.
- `frontend/src/components/ConfigPanel.tsx`: character-preview Stop + distinct stopping state; batch Stop's cancelling state relabeled to a distinct "Stopping…"; D-06 caveat copy corrected to "Stop interrupts the segment currently generating immediately."
- **Checkpoint-driven fixes** (found during Task 4's real-hardware verification, not part of the original plan scope, but required to honestly close it):
  - `frontend/src/hooks/useGenerationStream.ts`: added `restart()` — the generation-stream SSE connection is request-scoped server-side (drains one run, self-closes on terminal/empty), but the hook only opened it once on mount. A second "Generate All" click had no live connection, so `generation.status` could never report `"running"` again and the Stop button never rendered — even though the backend genuinely held the lock. `restart()` bumps a `connectionKey` the effect depends on, forcing a fresh `EventSource`.
  - `backend/app/generation_worker.py` + `main.py`: added `ensure_generation_queue()`, called synchronously in `generate_project` right after the batch task is registered — closes a race where the frontend's reconnect (right after the POST resolves) could land before `run_batch_generation`'s first `push_generation_event`, hitting the "nothing queued yet" fast path and self-closing prematurely.
  - `frontend/src/components/SegmentTable.tsx`: `GeneratePlayButton.handleStop` only cleared `isStopping` in its `catch` block — a *successful* cancel left the row stuck showing "Stopping…" forever. Moved the reset into a `finally` block alongside `onRefresh()`.

## Task Commits

1. **Task 1: Client fns — segment 202+poll contract, cancelSegmentGeneration, cancelCharacterPreview** - `d324b4d` (feat)
2. **Task 2: Segment row — 202+poll trigger + bare-bones Stop with distinct "stopping…" state** - `9b7661f` (feat)
3. **Task 3: Character-preview + batch Stop "stopping…" states and D-06 caveat copy** - `989c4f2` (feat)
4. **Task 4: D-01 true-kill end-to-end checkpoint** - reached, presented to user, resolved after two fix rounds:
   - `36da733` (fix): generation-stream SSE reconnect on each Generate All click
   - `3bd91a2` (fix): clear isStopping/isGenerating on successful segment stop
   - Plan metadata: this commit (docs: complete plan)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Batch Stop button never reappeared after the first Generate All run**
- **Found during:** Task 4's real-hardware checkpoint — user clicked Generate All a second time and reported the app "blocked" with no Stop button visible, requiring a service restart to recover (twice).
- **Root cause:** `useGenerationStream`'s `EventSource` opens once in a `useEffect` keyed only on `projectId`. The backend's `/projects/{id}/generation-stream` endpoint is request-scoped by design (checks `has_pending_generation_queue` once at connect time; if nothing is queued, or once a run's terminal event is drained, it yields one event and returns, closing the response). A second batch run has no live SSE connection reporting to it, so `generation.status` is stuck at whatever it last was — never `"running"` — and `ConfigPanel`'s `isBatchRunning` (which gates the Stop button's render) stays false even though the backend genuinely holds the generation lock.
- **Fix:** `useGenerationStream` now exposes `restart()`, which increments a `connectionKey` the connection effect depends on, forcing a fresh `EventSource`. `ConfigPanel.handleGenerateAll` calls `generation.restart()` immediately after `runBatchGeneration`'s POST resolves. A companion fix, `generation_worker.ensure_generation_queue()`, is called synchronously inside `generate_project`'s handler right after the task is registered — this closes a race where the frontend's reconnect could otherwise land in the same event-loop tick as task scheduling, before the task's first `push_generation_event`, and see "nothing queued yet."
- **Verification:** Two full real-hardware Generate-All-then-Stop cycles run by the user after the fix, both confirmed working ("works").
- **Committed in:** `36da733`

**2. [Rule 1 - Bug] Segment "Stopping…" state never cleared on a successful cancel**
- **Found during:** already present, uncommitted, in the worktree when Task 4's checkpoint work began — most likely from this same agent's own pre-checkpoint session investigating the "stop feels slow" report, but never committed before the checkpoint returned.
- **Issue:** `GeneratePlayButton.handleStop` set `isStopping(true)`, awaited `cancelSegmentGeneration`, called `onRefresh()`, and only reset `isStopping` to `false` inside the `catch` block — meaning a *successful* stop left the row's local `isStopping` (and `isGenerating`) state stuck indefinitely, since neither is derived from the refetched segment data.
- **Fix:** Moved `setIsGenerating(false)`, `setIsStopping(false)`, and `onRefresh()` into a `finally` block so both the success and error paths clear local state honestly, per D-03/D-05's tri-state requirement.
- **Verification:** Reviewed for correctness, covered by the same typecheck/lint pass as the SSE fix, then confirmed working by the user's retest.
- **Committed in:** `3bd91a2`

**Total deviations:** 2 auto-fixed (1 Rule 2 missing-critical, 1 Rule 1 bug) — both discovered specifically because the checkpoint was exercised against real hardware with a real user clicking real buttons, not a simulated pass. Neither was speculative scope creep: both were required for the plan's own must_haves (the tri-state honesty requirement, and the Stop control's basic presence/functionality on every run) to actually hold in practice.

## Issues Encountered

- **Root-cause investigation for "feels slow"**: cross-referenced `tts_service` journal logs against the user's report before assuming a regression. Two real segment-stop cycles showed 10s and 34s cancel-to-stop times — consistent with 04-01's documented vocoder-tail-proportional-to-progress characteristic (talker stops almost immediately; the vocoder then decodes whatever partial audio had already accumulated), not a new bug. This distinguished a real perception ("it feels slow when you wait a while before clicking Stop") from an actual defect, and kept the investigation focused on the two bugs that were real.
- **Out-of-scope but adjacent user feedback**: the Cast Review wizard (`CastWizard.tsx`/`CharacterCard.tsx`/`SegmentPreview.tsx`) has no stop mechanism for its own character-preview queue and no generate-all capability in `SegmentPreview.tsx` at all — confirmed via code read to be genuinely absent, not a Phase 4 regression (CONTEXT.md D-04 explicitly deferred `CharacterCard.tsx`'s wizard-side preview Stop to Phase 7; the wizard's `SegmentPreview.tsx` panel has zero generate/stop functionality today, so a bulk generate-all-with-per-item-tracking idea there is a new feature request, not existing Phase 4 scope). This wizard-side lock-holding was what caused the app to feel "blocked" earlier in the checkpoint session (twice requiring a manual service restart) — orthogonal to, and not fixed by, this plan's two bug fixes. Flagged to the user as a backlog item.

## User Setup Required

None — no external service configuration required. Both containers were rebuilt and the Quadlet-managed services restarted directly by the orchestrator during checkpoint verification (deployment-machine session, per CLAUDE.md's automation authorization).

## Next Phase Readiness

- All three cancellation paths (segment, character preview, batch) are verified end-to-end against real ROCm hardware: true GPU-call kill (D-01), honest tri-state UI (D-03/D-05), corrected caveat copy (D-06).
- ROADMAP Phase 4's 4 success criteria are satisfied: Stop halts in-flight GPU inference (not merely the queue) on all three paths; the app is immediately ready for a fresh generation after any stop.
- Backlog item captured (not part of this phase): Cast Review wizard has no interrupt mechanism for its own preview queue and no generate-all/stop capability — candidate for Phase 7's unification pass or a dedicated follow-up.

---
*Phase: 04-immediate-cancellation*
*Completed: 2026-07-14*

## Self-Check: PASSED

All modified files confirmed present on disk with the expected changes; all
commit hashes (`d324b4d`, `9b7661f`, `989c4f2`, `36da733`, `3bd91a2`)
confirmed present in `git log`. Frontend `typecheck` and `lint` clean (lint
warnings/errors present only in files this plan did not touch). Backend
`ruff check` clean on both modified files. Backend test suite: 87 passed, 1
skipped, 1 pre-existing deselected failure unrelated to this phase.
