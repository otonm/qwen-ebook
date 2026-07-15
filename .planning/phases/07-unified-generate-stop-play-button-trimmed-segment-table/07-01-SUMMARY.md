---
phase: 07-unified-generate-stop-play-button-trimmed-segment-table
plan: 01
subsystem: ui
tags: [react, typescript, tailwind, frontend-refactor]

# Dependency graph
requires:
  - phase: 06-config-panel-output-format-filename-download
    provides: "downloadUrl helper and /projects/{id}/download route pattern this plan's outputUrl mirrors"
provides:
  - "GspStatus type — idle/generating/stopping/ready"
  - "GenerateStopPlayButton presentational component (STATE_CLASSES/STATE_LABEL per UI-SPEC §1)"
  - "useGenerateStopPlay hook — shared poll/settle/error state machine"
  - "outputUrl(projectId) helper in api/client.ts"
affects: [07-02, 07-03, 07-04, 07-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Presentational component + stateful hook split for generate/stop/play controls"
    - "GspStatus precedence derivation: stopping > generating > ready > idle"

key-files:
  created:
    - frontend/src/components/GenerateStopPlayButton.tsx
    - frontend/src/hooks/useGenerateStopPlay.ts
  modified:
    - frontend/src/api/client.ts

key-decisions:
  - "outputUrl is a verbatim duplicate of downloadUrl (same route string) rather than an alias/re-export, matching the plan's explicit instruction to mirror downloadUrl's shape for the batch site's hidden <audio> element."
  - "useGenerateStopPlay's poll-ceiling error message (\"Generation is taking too long — try again.\") is a new string distinct from CharacterPreviewRow's existing \"Preview generation is taking too long — try again.\" — the hook is now the single generic error surface for all call sites, so its wording is intentionally site-agnostic; Wave 2 plans may override per-site if the exact string continuity matters."

patterns-established:
  - "Pattern 1 (07-RESEARCH.md): presentational button + stateful hook split — Wave 2 plans swap this hook/component in at all 4 call sites instead of re-deriving poll/settle logic."

requirements-completed: [GEN-12]

coverage:
  - id: D1
    description: "useGenerateStopPlay derives GspStatus in precedence order stopping > generating > ready > idle"
    requirement: GEN-12
    verification:
      - kind: unit
        ref: "source read: frontend/src/hooks/useGenerateStopPlay.ts ternary chain (isStopping -> isRowGenerating -> hasAudio -> idle)"
        status: pass
    human_judgment: false
  - id: D2
    description: "GenerateStopPlayButton renders exactly one <Button> with STATE_CLASSES/STATE_LABEL matching UI-SPEC §1"
    requirement: GEN-12
    verification:
      - kind: unit
        ref: "grep -c '<Button' frontend/src/components/GenerateStopPlayButton.tsx == 1; grep 'bg-amber-400'/'Generate Preview'/'Stop Generation'"
        status: pass
    human_judgment: false
  - id: D3
    description: "outputUrl(projectId) returns the identical route string as downloadUrl, no new backend endpoint"
    requirement: GEN-12
    verification:
      - kind: unit
        ref: "grep 'export function outputUrl' frontend/src/api/client.ts; source read confirms identical template literal"
        status: pass
    human_judgment: false
  - id: D4
    description: "frontend typecheck and lint pass with the 3 new/modified files introducing no new errors"
    verification:
      - kind: other
        ref: "cd frontend && npm run typecheck (clean); npm run lint (0 issues attributable to new files; 6 pre-existing issues in untouched files confirmed via git diff against base commit)"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-07-15
status: complete
---

# Phase 7 Plan 01: Unified Generate/Stop/Play Button Foundation Summary

**Extracted the shared `useGenerateStopPlay` hook and `<GenerateStopPlayButton>` presentational component (plus an `outputUrl` helper) that collapse the phase's four duplicated generate/stop/play implementations into one reusable foundation.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-15T21:57:xx+02:00
- **Completed:** 2026-07-15T21:59:28+02:00
- **Tasks:** 3
- **Files modified:** 3 (1 modified, 2 created)

## Accomplishments
- Added `outputUrl(projectId)` to `api/client.ts`, mirroring `downloadUrl`'s exact route template (`/projects/{id}/download`) — no new backend endpoint, reuses Phase 6's download route for the batch site's future hidden `<audio>` element.
- Built `useGenerateStopPlay`, a shared hook porting the poll/settle/error state machine duplicated across `SegmentTable.tsx`'s `GeneratePlayButton` and `ConfigPanel.tsx`'s `CharacterPreviewRow` — owns `isGenerating`/`isStopping`/`error`/`hasObservedGeneratingRef`, derives `GspStatus` in the load-bearing precedence order `stopping > generating > ready > idle`, and gates its 1500ms poll interval on both a `poll` flag and `isGenerating` so the batch site (which will drive status via SSE) can opt out.
- Built `<GenerateStopPlayButton>`, a pure presentational component rendering exactly one `<Button>` per call site with `STATE_CLASSES` (amber/red/green) and `STATE_LABEL` ("Generate Preview"/"Stop Generation"/"Stopping…"/"Play"→"Pause") matching UI-SPEC Component Contracts §1 verbatim, dispatching `onGenerate`/`onStop`/`onTogglePlay` by status and merging caller `className` via `cn()` so state color wins over `Button`'s default variant without touching `button.tsx`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add outputUrl helper to api/client.ts** - `d670ee5` (feat)
2. **Task 2: Create useGenerateStopPlay hook** - `5488fe8` (feat)
3. **Task 3: Create GenerateStopPlayButton presentational component** - `456d5d6` (feat)

**Plan metadata:** committed by orchestrator after wave completion (worktree mode — this agent does not write STATE.md/ROADMAP.md)

## Files Created/Modified
- `frontend/src/api/client.ts` - added `outputUrl(projectId): string`, adjacent to `downloadUrl`
- `frontend/src/hooks/useGenerateStopPlay.ts` (new) - shared poll/settle/error state machine hook, exports `GspStatus` and `UseGenerateStopPlayOptions`
- `frontend/src/components/GenerateStopPlayButton.tsx` (new) - presentational button component, imports `GspStatus` from the hook

## Decisions Made
- `outputUrl` is a byte-for-byte duplicate of `downloadUrl`'s route template rather than a re-export — plan explicitly required matching `downloadUrl` "verbatim in shape" as a distinct named export for the batch site's future `<audio src>` use.
- The hook's poll-ceiling error message is deliberately generic ("Generation is taking too long — try again.") rather than porting `CharacterPreviewRow`'s preview-specific wording, since the hook is now shared across segment/character/batch call sites with different subject nouns.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `frontend/node_modules` was not present in this worktree (gitignored, not carried over from the main checkout) — ran `npm install` before `npm run typecheck`/`npm run lint` could execute. This is standard worktree setup, not a plan deviation; it introduced no file changes tracked by git.
- `npm run lint` reported 6 pre-existing errors/warnings (2 `react-hooks/set-state-in-effect` and `react-hooks/incompatible-library` warnings, 2 `react-refresh/only-export-components` errors in `badge.tsx`/`button.tsx`, plus related noise) — confirmed via `git diff` against the plan's base commit that none of the affected files (`ProjectListScreen.tsx`, `SegmentPreview.tsx`, `SegmentTable.tsx`, `ui/badge.tsx`, `ui/button.tsx`) were touched by this plan. Out of scope per the deviation rules' scope boundary; not fixed.

## Next Phase Readiness
- `GspStatus`, `GenerateStopPlayButton`, `useGenerateStopPlay`, and `outputUrl` are all in place, typecheck clean, and match the UI-SPEC/RESEARCH contracts exactly — Wave 2 plans (07-02 through 07-05) can now swap these into `SegmentTable.tsx`, `ConfigPanel.tsx` (character rows + batch), `CharacterCard.tsx`, and `CastWizard.tsx`.
- No blockers. `package.json` diff against the base commit is empty — zero new npm dependencies, as required.

---
*Phase: 07-unified-generate-stop-play-button-trimmed-segment-table*
*Completed: 2026-07-15*
