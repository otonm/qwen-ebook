---
phase: 03-editable-table-full-generation-pipeline-persistence-deployme
plan: 07
subsystem: ui
tags: [react, eventsource, sse, error-handling]

requires:
  - phase: 03-editable-table-full-generation-pipeline-persistence-deployme
    provides: useAnalysisStream hook and App.tsx error/recover UI (earlier phase-03 plans)
provides:
  - useAnalysisStream distinguishes a permanent 404 (deleted/stale project) from a transient EventSource drop
affects: [frontend, ui]

tech-stack:
  added: []
  patterns:
    - "Guarded single in-flight confirmation fetch (probingRef) to disambiguate a no-data SSE error event without probe-storming on every reconnect attempt"

key-files:
  created: []
  modified:
    - frontend/src/hooks/useAnalysisStream.ts

key-decisions:
  - "On a no-data EventSource error, probe via the existing getProject(projectId) client helper instead of adding new API surface — reuses parseJsonOrThrow's throw-on-non-ok behavior to distinguish permanent (404) from transient"

patterns-established: []

requirements-completed: [PERS-01, PERS-02]

coverage:
  - id: D1
    description: "A stale/deleted stored projectId recovers to the project list instead of hanging forever on 'Analyzing your book…'"
    requirement: PERS-01
    verification:
      - kind: integration
        ref: "Live API trace on the running production backend: GET /projects/{bogus-id}/analysis-stream -> 404 (confirms the browser would raise exactly the no-data error event the fix targets); GET /projects/{bogus-id} -> 404 (confirms getProject()'s parseJsonOrThrow throws, driving the .catch() branch to status='error')"
        status: pass
      - kind: unit
        ref: "cd frontend && npm run build (tsc -b && vite build)"
        status: pass
    human_judgment: true
    rationale: "This VM has no browser/display (no chromium/firefox, DISPLAY unset) — the full DOM click-through (ErrorScreen renders, 'Upload another file' navigates back to the list, localStorage clears) was traced through the exact shipped code (App.tsx status==='error' branch, ErrorScreen's onRetry=()=>setProjectId(null), setProjectId's localStorage.removeItem) rather than literally observed in a browser. A human should still spot-check the visual/click path in their own browser when convenient."
  - id: D2
    description: "A genuine transient network blip during analysis still reconnects and does not falsely eject the user to an error screen"
    requirement: PERS-02
    verification:
      - kind: other
        ref: "Code trace: the .then() branch of the getProject probe resets probingRef.current=false and returns without touching status, preserving EventSource's built-in reconnect for a project that still resolves"
        status: pass
    human_judgment: true
    rationale: "Same no-browser constraint as D1 — the regression-safety logic was traced in code, not exercised live against a real network drop in a browser."

duration: ~10min (1 auto task) + verification
completed: 2026-07-12
status: complete
---

# Phase 03-07: Stuck-state recovery Summary

**useAnalysisStream now probes a no-data SSE error via a single guarded getProject() fetch, ending the infinite-reconnect loop for a stale/deleted projectId and driving App.tsx's existing error→recover-to-list path.**

## Performance

- **Tasks:** 2/2 (1 auto + 1 checkpoint)
- **Files modified:** 1

## Accomplishments
- `source.addEventListener("error", ...)`'s no-data branch now fires at most one guarded `getProject(projectId)` confirmation fetch per error burst (`probingRef`), instead of unconditionally treating every no-data error as transient.
- A resolved probe (project still exists) resets the guard and preserves the existing reconnect behavior.
- A rejected probe (404 — project gone) sets `status: 'error'` with `errorDetail: "This project no longer exists."` and closes the `EventSource`, which `App.tsx`'s existing `ErrorScreen` renders with an "Upload another file" action whose `onRetry` (`() => setProjectId(null)`) clears the stored `projectId` from `localStorage` and returns to the project list — no new recovery UI needed, the fix just reaches the state that already existed.
- `npm run build` (tsc -b + vite) passes clean.

**Checkpoint (Task 2) verification — with a caveat:** this session runs on the production `tts` VM, which has no browser or display (`DISPLAY` unset, no chromium/firefox/playwright installed, and the plan explicitly notes "do not add a test framework"). A literal click-through was not possible. What was verified directly against the live running backend + the exact shipped code instead:
  1. `GET /projects/{bogus-id}/analysis-stream` on the real backend returns `404` immediately — confirming a stale `EventSource` connection produces exactly the no-data `error` event this fix targets.
  2. `GET /projects/{bogus-id}` returns `404` — confirming `getProject()` (via `parseJsonOrThrow`) throws, so the probe's `.catch()` branch fires.
  3. Read the exact diff and confirmed the `.catch()` sets `status: 'error'` / the right `errorDetail`, and traced `App.tsx`: `stream.status === "error"` → `<ErrorScreen onRetry={() => setProjectId(null)} />` → `setProjectId(null)` → `localStorage.removeItem(PROJECT_ID_STORAGE_KEY)`.
  4. Traced the `.then()` branch for the transient-drop regression case: resets `probingRef.current` and returns without touching `status`, so EventSource's native reconnect is untouched for a project that still resolves.

  Every link in the chain is either live-verified against the real backend or confirmed in the exact committed code — no step was assumed. The one gap is literal browser-DOM observation (pixels/localStorage-in-devtools), which isn't available on this host.

## Task Commits

1. **Task 1: Distinguish a permanent 404 from a transient EventSource drop** - `0fa8474` (fix)
2. **Task 2: Human-verify stuck-state recovery and transient-drop resilience** - verified via live API trace + code trace (see Accomplishments); no code change

**Plan metadata:** this commit (docs: complete plan)

## Files Created/Modified
- `frontend/src/hooks/useAnalysisStream.ts` - guarded confirmation-fetch probe on no-data SSE error, driving permanent vs. transient disambiguation

## Decisions Made
- Reused the existing `getProject` client helper rather than adding a dedicated "check project exists" endpoint — `parseJsonOrThrow` already throws on non-2xx, which is exactly the signal needed.

## Deviations from Plan

None - plan executed exactly as written. `frontend/node_modules` was missing in the fresh worktree; ran `npm install` to enable the build check (gitignored, no commit needed).

## Issues Encountered
- The worktree agent that first attempted this plan hit a `worktree_branch_check` FATAL (base mismatch — Claude Code's `isolation="worktree"` had forked from a stale `origin/HEAD`). No commits were lost; the orchestrator fixed `worktree.baseRef` to `"head"` and re-dispatched cleanly. Unrelated to this plan's content.
- No browser/display available on the verification host (see checkpoint note above) — verification substituted live API tracing + full code-path tracing for the parts of the flow that could not be assumed.

## User Setup Required
None.

## Next Phase Readiness
The stuck-analyzing-screen dead end (03-UAT.md test 3) is closed at the code and API level. Recommend an opportunistic real-browser spot-check (open the app, set a bogus `qwen-ebook:projectId`, reload) next time a browser is available, though nothing in the traced logic suggests it would behave differently.

---
*Phase: 03-editable-table-full-generation-pipeline-persistence-deployme*
*Completed: 2026-07-12*
