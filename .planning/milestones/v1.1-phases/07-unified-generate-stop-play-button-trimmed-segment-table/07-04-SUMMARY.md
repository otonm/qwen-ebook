---
phase: 07-unified-generate-stop-play-button-trimmed-segment-table
plan: 04
subsystem: ui
tags: [react, typescript, tailwind, frontend-refactor]

# Dependency graph
requires:
  - phase: 07-unified-generate-stop-play-button-trimmed-segment-table
    plan: 01
    provides: "GenerateStopPlayButton presentational component + useGenerateStopPlay hook"
provides:
  - "CharacterCard.tsx wizard preview control unified onto the shared GenerateStopPlayButton/useGenerateStopPlay pair (4th and final call site)"
  - "CastWizard.tsx outer flex container no longer stretches the character-card column to SegmentPreview's height"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CharacterCard's wizard-side preview button folded onto the same presentational-component + stateful-hook split as the other 3 sites (07-RESEARCH.md Pattern 1)"

key-files:
  created: []
  modified:
    - frontend/src/components/CharacterCard.tsx
    - frontend/src/components/CastWizard.tsx

key-decisions:
  - "isExternallyGenerating is hardcoded false for CharacterCard's useGenerateStopPlay call — unlike a segment's server-side generation_status or the batch site's SSE stream, there is no external 'this character is previewing' signal today; the card's own trigger is the only generating source, so the hook's internal isGenerating state is sufficient."
  - "Wrapped the button row in an extra flex-col div (button row + error paragraph) to add the missing per-row error surface (Rule 2) without touching the button row's own item layout — the row's internal flex items (button, badge, audio, merge button) are otherwise untouched."

patterns-established: []

requirements-completed: [GEN-10, GEN-12]

coverage:
  - id: D1
    description: "CharacterCard renders exactly one GenerateStopPlayButton driven by useGenerateStopPlay, gaining a working Stop control for the first time"
    requirement: GEN-10
    verification:
      - kind: unit
        ref: "grep -c 'GenerateStopPlayButton' frontend/src/components/CharacterCard.tsx == 1 (component usage); grep 'useGenerateStopPlay'"
        status: pass
    human_judgment: false
  - id: D2
    description: "Local hardcoded 60000ms poll ceiling is gone; GENERATION_POLL_CEILING_MS is used exclusively via the shared hook"
    requirement: GEN-10
    verification:
      - kind: unit
        ref: "grep -c '60000' frontend/src/components/CharacterCard.tsx == 0"
        status: pass
    human_judgment: false
  - id: D3
    description: "CastWizard's outer flex container gains xl:items-start; inner column classes and SegmentPreview.tsx are unchanged"
    requirement: GEN-12
    verification:
      - kind: unit
        ref: "grep -c 'xl:items-start' frontend/src/components/CastWizard.tsx >= 1; git diff --stat frontend/src/components/SegmentPreview.tsx is empty"
        status: pass
    human_judgment: false
  - id: D4
    description: "frontend typecheck and build pass; scoped lint on the two modified files is clean"
    verification:
      - kind: other
        ref: "cd frontend && npm run typecheck (clean); npm run build (succeeds); npx eslint on CharacterCard.tsx (0 problems) and CastWizard.tsx (1 pre-existing unrelated warning at line 54, untouched by this plan)"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-07-15
status: complete
---

# Phase 7 Plan 04: Unified Generate/Stop/Play Button — CharacterCard & CastWizard Layout Summary

**Folded CharacterCard's wizard-side preview button — the last of the four independently-coded generate/play implementations and the only one with no Stop control — onto the shared `GenerateStopPlayButton`/`useGenerateStopPlay` pair, and fixed CastWizard's stretched character-card column with one Tailwind class.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-15T19:56:14Z
- **Completed:** 2026-07-15T20:08:20Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Replaced `CharacterCard.tsx`'s `hasPreview ? <icon button> : <text 'Generate' button>` branch with one `<GenerateStopPlayButton size="sm">` driven by `useGenerateStopPlay`, giving the wizard's preview control a real, working Stop button for the first time (D-01, GEN-10).
- Deleted the card's local hand-rolled poll/settle scaffolding — the `isGenerating` state, the `isWaitingForPreview` derivation, and the hardcoded `window.setTimeout(..., 60000)` poll ceiling — in favor of the hook's shared `GENERATION_POLL_CEILING_MS` (330s), matching every other generate/stop/play site in the app (RESEARCH Pitfall 3: replaced wholesale, not patched).
- Added a per-row error paragraph (`role="alert"`) fed by the hook's `error` state, matching the pattern already established at the segment/character-preview/batch sites (Rule 2 — this card was the only site missing a visible error surface).
- Left the name `Input`, Preset `Select`, Voice Instructions `Textarea`, "Voice assigned" `Badge`, and merge `Dialog`/button completely untouched (D-02) — `git diff` on `CharacterCard.tsx` shows only the button block and its immediately surrounding state/imports changed.
- Fixed `CastWizard.tsx`'s stretched character-card column with a single added class, `xl:items-start`, on the outer two-column flex container — the `xl:w-[420px]` character-card column now sizes to its own content height instead of stretching to match `SegmentPreview`'s height (D-05). No other class changed; `SegmentPreview.tsx` was not touched (D-03).

## Task Commits

Each task was committed atomically:

1. **Task 1: Swap CharacterCard's button block to the shared component, gaining a Stop control (D-01/D-02, GEN-10)** - `76a5650` (feat)
2. **Task 2: Fix CastWizard's stretched character-card column (D-05)** - `c58a477` (fix)

**Plan metadata:** committed by orchestrator after wave completion (worktree mode — this agent does not write STATE.md/ROADMAP.md/REQUIREMENTS.md)

## Files Created/Modified
- `frontend/src/components/CharacterCard.tsx` - button block swapped to `<GenerateStopPlayButton>` + `useGenerateStopPlay`; local 60s poll ceiling and `isGenerating`/`isWaitingForPreview` state removed; per-row error paragraph added
- `frontend/src/components/CastWizard.tsx` - one class, `xl:items-start`, added to the outer flex container

## Decisions Made
- `isExternallyGenerating` is hardcoded `false` in CharacterCard's `useGenerateStopPlay` call — this component has no server-side "is previewing" signal analogous to a segment's `generation_status`; the card's own trigger is the only generating source for it, so the hook's internally-owned `isGenerating` fully covers the state.
- Added a thin `flex-col` wrapper around the existing button row purely to host the new error paragraph beneath it — the button row's own internal item layout (button, badge, hidden audio, merge button) is unchanged, so this does not count as reshaping the row per D-02's intent (only the generate/stop/play control's internal branch was the "layout" that D-02 protects).

## Deviations from Plan

None — plan executed exactly as written. (One out-of-scope, pre-existing lint issue was found and logged rather than fixed; see Issues Encountered.)

## Issues Encountered
- `frontend/node_modules` was not present in this worktree (gitignored) — ran `npm install` before `npm run typecheck`/`npm run lint`/`npm run build` could execute. Standard worktree setup, introduced no tracked file changes.
- Whole-project `npm run lint` fails on 3 pre-existing errors in files this plan does not touch: `ProjectListScreen.tsx:57` (`react-hooks/set-state-in-effect`), `ui/badge.tsx:49` and `ui/button.tsx:67` (`react-refresh/only-export-components`). Confirmed pre-existing via `git status --short` (only `CharacterCard.tsx`/`CastWizard.tsx` ever modified in this worktree) and a scoped `npx eslint` run on each of this plan's two modified files individually (`CharacterCard.tsx`: 0 problems; `CastWizard.tsx`: 1 pre-existing, unrelated warning at line 54 about `timeoutsRef.current` in an effect cleanup, from code this plan's single-class edit does not touch). Logged to `deferred-items.md` in this phase directory per the scope-boundary rule; not fixed.

## Known Stubs

None.

## Threat Flags

None — both changes stay within the trust boundary and threat register already declared in the plan (`T-07-07` mitigated by the wholesale hook swap; `T-07-08` accepted as a pure presentational class change).

## Next Phase Readiness
- All four generate/stop/play call sites this milestone identified (`SegmentTable.tsx`, `ConfigPanel.tsx` character rows + batch, `CharacterCard.tsx`) are now unified onto `GenerateStopPlayButton`/`useGenerateStopPlay`, assuming Wave 2 siblings 07-02/07-03 land alongside this plan.
- `CastWizard.tsx`'s E4 layout bug (character-card column stretching to `SegmentPreview`'s height) is closed with the single-class fix; no independent scroll panes or other layout changes were introduced.
- No blockers. `package.json` diff against the base commit is empty — zero new npm dependencies.

---
*Phase: 07-unified-generate-stop-play-button-trimmed-segment-table*
*Completed: 2026-07-15*

## Self-Check: PASSED

All created/modified files verified present: `frontend/src/components/CharacterCard.tsx`, `frontend/src/components/CastWizard.tsx`, this SUMMARY.md. Both commits (`76a5650`, `c58a477`) verified present in git log.
