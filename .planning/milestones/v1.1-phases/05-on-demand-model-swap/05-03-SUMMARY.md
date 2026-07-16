---
phase: 05-on-demand-model-swap
plan: 03
subsystem: ui
tags: [react, typescript, shadcn, config-panel, tts-model-swap]

# Dependency graph
requires:
  - phase: 05-on-demand-model-swap (Plan 01)
    provides: tts_service ensure_loaded swap machinery, VRAM-safe load/unload
  - phase: 05-on-demand-model-swap (Plan 02)
    provides: backend /projects/{id}/model endpoint, single-flight lock, segment/preview invalidation on swap
provides:
  - "Config Panel Model dropdown bound to project.tts_model (server state)"
  - "setProjectModel API mutation + tts_model field on the Project type"
  - "D-01 immediate load on select, D-02 automatic revert + inline error on failure, D-03 persistent 0.6B steering warning"
  - "Human-verified end-to-end swap on the real RX 9070 XT deploy target"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Select value bound directly to server state (project.tts_model) rather than local optimistic state, so failure-revert (D-02) is automatic on refetch"
    - "generationLocked (pre-existing lock hook) reused to cover Generate/preview disabling during a model swap instead of introducing a new isModelSwapping prop"

key-files:
  created: []
  modified:
    - frontend/src/api/client.ts
    - frontend/src/components/ConfigPanel.tsx

key-decisions:
  - "Task 2 (Voice Instructions cell disabling, D-04) is a no-op: the Voice Instructions column was already removed from SegmentTable.tsx in a prior commit (fc9184a, before this plan was written) and its return is locked to Phase 7 (REQUIREMENTS.md TBL-05). CFG-05's steering-limitation surface is already satisfied by Task 1's D-03 warning note in ConfigPanel, so no code change was needed or made to SegmentTable.tsx."
  - "No new isModelSwapping prop introduced — the existing generationLocked prop already disables Generate All/per-row/preview controls during a swap because model-load claims the same single-flight backend lock (per UI-SPEC explicit instruction)."

patterns-established:
  - "Steering-limitation warnings for a currently-loaded low-capability model surface at the Config Panel level (D-03), not per-cell, until a per-cell surface (Voice Instructions column) actually exists again in the UI."

requirements-completed: [CFG-04, CFG-05]

coverage:
  - id: D1
    description: "Config Panel Model dropdown replaces the hardcoded TTS_MODEL_DISPLAY_NAME with a live Select bound to project.tts_model, showing both verbatim option labels ('Higher quality (1.7B)' / 'Faster (0.6B)')"
    requirement: "CFG-04"
    verification:
      - kind: automated_ui
        ref: "npx tsc --noEmit + grep assertions in Task 1 verify block (setProjectModel, tts_model, Higher quality (1.7B), Faster (0.6B) present; TTS_MODEL_DISPLAY_NAME removed)"
        status: pass
      - kind: manual_procedural
        ref: "Task 3 checkpoint:human-verify step 2 — live swap on http://100.76.155.0:8000, human approved"
        status: pass
    human_judgment: false
  - id: D2
    description: "D-01 immediate load on select with spinner/disabled trigger; D-02 automatic revert to still-resident model with inline destructive error on failure; D-03 persistent muted warning while 0.6B is active"
    requirement: "CFG-05"
    verification:
      - kind: manual_procedural
        ref: "Task 3 checkpoint:human-verify steps 2, 3, 5, 7 — spinner/disable during swap, warning note appears/clears, failure-revert path — human approved on the real deploy target"
        status: pass
    human_judgment: true
    rationale: "Swap timing (tens of seconds), spinner visibility, warning-note tone, and OOM/failure-revert behavior require live observation on the actual RX 9070 XT GPU target — not reproducible in a headless/mocked check."
  - id: D3
    description: "Per-segment Voice Instructions cell disabling while 0.6B is active (D-04)"
    verification: []
    human_judgment: true
    rationale: "Deferred, not implemented in this plan — see Deviations. The Voice Instructions column does not currently exist in SegmentTable.tsx (removed in fc9184a prior to this plan); re-adding it is Phase 7's locked scope (TBL-05). No verification applies until that column returns."

# Metrics
duration: ~35min
completed: 2026-07-14
status: complete
---

# Phase 05 Plan 03: Config Panel Model Swap UI Summary

**Config Panel Model Select bound to server-state `project.tts_model`, with immediate-load/spinner/revert-on-failure UX and a persistent 0.6B steering warning; Voice-Instructions-cell disabling deferred to Phase 7 since that column doesn't currently exist.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-07-14 (Task 1 commit 8faded9)
- **Completed:** 2026-07-14
- **Tasks:** 3 (2 auto, 1 checkpoint:human-verify)
- **Files modified:** 2 (frontend/src/api/client.ts, frontend/src/components/ConfigPanel.tsx)

## Accomplishments
- Added `tts_model: string` to the frontend `Project` type and a `setProjectModel(id, model_id)` mutation POSTing to `/projects/{id}/model`, mirroring the existing mutation-helper pattern in `client.ts`.
- Replaced ConfigPanel's hardcoded `TTS_MODEL_DISPLAY_NAME` row with a real `Select` bound directly to `project.tts_model` (server state) — so a failed swap reverts automatically on refetch (D-02) with no separate rollback logic needed.
- Implemented D-01 (immediate load on select + "Switching model…" spinner + disabled trigger), D-02 (destructive `role="alert"` inline error on failure), and D-03 (persistent muted warning note, `text-muted-foreground`, while 0.6B is active) exactly per the UI-SPEC copywriting and color contracts.
- Confirmed no new `isModelSwapping` prop was needed — the pre-existing `generationLocked` prop already covers disabling Generate All / per-row / preview controls during a swap, since model-load claims the same single-flight backend lock.
- End-to-end swap verified live by the human operator on the real RX 9070 XT deploy target (http://100.76.155.0:8000), after the orchestrator rebuilt and restarted the deploy pod from this worktree's code.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add setProjectModel API + Model Select with swap/warn/error UX in ConfigPanel** - `8faded9` (feat)
2. **Task 2: Disable Voice Instructions cells while 0.6B is active (D-04)** - no commit (no-op; see Deviations)
3. **Task 3: Human-verify the full model swap end-to-end on the deploy target** - checkpoint approved by human operator, no code commit

**Plan metadata:** (this SUMMARY commit)

## Files Created/Modified
- `frontend/src/api/client.ts` - Added `tts_model` field to `Project` interface; added `setProjectModel(id, model_id)` mutation.
- `frontend/src/components/ConfigPanel.tsx` - Replaced hardcoded model display with live Model `Select`, swap spinner state, D-02 error paragraph, D-03 warning paragraph, and `handleModelChange` handler.

## Decisions Made
- **Task 2 deviation (Rule 4 — scope/architectural conflict, resolved by deferral, not by asking):** The plan's Task 2 called for disabling the Voice Instructions `Textarea` cell in `SegmentTable.tsx` while 0.6B is active (D-04). Investigation showed the Voice Instructions column was already removed from `SegmentTable.tsx` entirely in a prior commit (`fc9184a`, "fix(ui): remove Voice Instructions column from segment table", dated before this plan was authored). There is currently no `EditableTextCell` call site for `voice_instructions` to thread a `ttsModel` prop into or to disable. Re-introducing that column is explicitly locked to Phase 7 per `REQUIREMENTS.md` (`TBL-05`), so adding it back here would be out-of-scope architectural work for this plan. CFG-05 (the requirement Task 2 was partially serving) is still satisfied: Task 1's D-03 persistent warning note already tells the user that steering has no effect while 0.6B is active, which is the honest-limitation surface CFG-05 requires — it now lives at the Config Panel level instead of per-cell, because per-cell has no surface to attach to until Phase 7 re-adds the column. No code change was made to `SegmentTable.tsx`; the file is unmodified by this plan.
- **No new `isModelSwapping` prop** (Task 1, as directed by UI-SPEC): reused the existing `generationLocked` prop rather than plumbing a parallel disable-signal through ConfigPanel/SegmentTable, since both conditions gate on the same backend single-flight lock.
- **Select bound to server state, not local optimistic state** (Task 1, D-02 mechanism): choosing to read `project.tts_model` directly (re-fetched via `onRefresh()`) means a failed swap's revert is "free" — no explicit rollback branch, the UI just reflects whatever the backend actually settled on.

## Deviations from Plan

### Auto-fixed Issues

None in the Rule 1-3 sense (no bugs, no missing critical functionality, no blockers requiring inline fixes).

### Scope Deviation (Rule 4)

**1. [Rule 4 - Architectural/scope conflict] Task 2 (D-04 Voice Instructions cell disabling) deferred — column does not exist**
- **Found during:** Task 2 (Disable Voice Instructions cells while 0.6B is active)
- **Issue:** The plan's `<read_first>` for Task 2 pointed at "EditableTextCell at line 318" and "call sites around line 490" in `SegmentTable.tsx` as the location to thread a `ttsModel` prop into and add the `disabled`/`title` logic. Neither exists: the Voice Instructions column was removed from `SegmentTable.tsx` in commit `fc9184a` prior to this plan being written. There is no `voice_instructions` field rendered by `EditableTextCell` to gate.
- **Resolution:** No code change. Re-adding the Voice Instructions column is out of scope for this plan — it is Phase 7's locked deliverable (`TBL-05` in REQUIREMENTS.md). Implementing it here would be new UI surface area (an architectural addition, not a fix), which Rule 4 requires routing to a decision rather than auto-fixing. Given the column's absence is itself the reason the requirement it partially serves (CFG-05) is already met via Task 1's D-03 warning note, the pragmatic resolution — treating Task 2 as a documented no-op rather than escalating to a blocking checkpoint — was applied and is recorded here for visibility.
- **Files modified:** None (`frontend/src/components/SegmentTable.tsx` unchanged).
- **Verification:** `git diff` on `SegmentTable.tsx` for this plan's work is empty; `frontend_modified` files list confirmed only `client.ts` and `ConfigPanel.tsx` changed.
- **Committed in:** N/A — no commit for Task 2.

---

**Total deviations:** 1 scope deviation (Rule 4, resolved as documented no-op — see above)
**Impact on plan:** CFG-04 and CFG-05 are both still fully satisfied by Task 1's implementation. Task 2's original per-cell surface is deferred to Phase 7 alongside the column itself; tracked via TBL-05.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Human Verification (Task 3)

Task 3 was a `checkpoint:human-verify` gate. The orchestrator rebuilt and restarted the deploy pod (`bash deploy/run-local.sh`, run from this worktree) so the running backend/tts_service containers reflected Task 1's commit (`8faded9`), then presented the full 7-step verification checklist from the plan to the human operator on the real deploy target at `http://100.76.155.0:8000`. The checklist's step 3 (Voice Instructions cell graying-out) was adjusted/dropped in-flight per the Task 2 deviation above — not applicable since no such cell currently exists in the UI.

**Result: approved.** The human confirmed, on the RX 9070 XT deploy target:
- Model dropdown switch (1.7B → 0.6B) shows the "Switching model…" spinner, trigger disabled, Generate All/per-row/preview controls disabled for the swap duration.
- After swap: persistent muted D-03 warning note appears; segments and character preview revert to pending/uncached state (no stale cross-model audio).
- Regenerating a segment and a character preview under 0.6B produces fresh audio.
- Switching back to 1.7B clears the warning note.
- VRAM sanity (`mem_get_info` before/after) stable across the swap.
- Failure-revert path (D-02): dropdown reverts to the still-resident model with an inline destructive error, no "no model" limbo state.

## Next Phase Readiness
- Phase 05 (on-demand model swap) is functionally complete: tts_service load/unload machinery (Plan 01), backend swap endpoint + invalidation (Plan 02), and this plan's Config Panel UI are all live and human-verified on the real deploy target.
- Voice Instructions column (and therefore true D-04 per-cell disabling) remains Phase 7's deliverable (TBL-05) — no new blocker introduced by this plan, just confirming the existing roadmap boundary.

## Self-Check: PASSED

- FOUND: frontend/src/api/client.ts (modified, contains `setProjectModel`/`tts_model`)
- FOUND: frontend/src/components/ConfigPanel.tsx (modified, contains Model Select UX)
- FOUND commit 8faded9 in `git log --oneline --all`
- CONFIRMED: frontend/src/components/SegmentTable.tsx unmodified by this plan (Task 2 no-op, documented above)

---
*Phase: 05-on-demand-model-swap*
*Completed: 2026-07-14*
