---
phase: 07-unified-generate-stop-play-button-trimmed-segment-table
plan: 02
subsystem: ui
tags: [react, typescript, tailwind, frontend-refactor]

# Dependency graph
requires:
  - phase: 07-unified-generate-stop-play-button-trimmed-segment-table
    plan: 01
    provides: "GspStatus, GenerateStopPlayButton, useGenerateStopPlay, outputUrl"
provides:
  - "SegmentTable.tsx segment row wired to the shared GenerateStopPlayButton/useGenerateStopPlay (GEN-09)"
  - "SegmentTable.tsx 5-entry columns array with a Voice Instructions editable column (TBL-05)"
affects: [07-03, 07-04, 07-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "GeneratePlayButton reduced to a thin wrapper: useGenerateStopPlay for state, <GenerateStopPlayButton> for presentation, hidden <audio> + isPlaying kept local to the wrapper"

key-files:
  modified:
    - frontend/src/components/SegmentTable.tsx

key-decisions:
  - "autoplay-on-generate is preserved via a local autoplayRef set in a handleGenerateClick wrapper around the hook's handleGenerate, since the shared hook has no autoplay concept of its own (it's per-consumer UX, not shared state machine)."

requirements-completed: [GEN-09, GEN-12, TBL-05]

coverage:
  - id: D1
    description: "Each segment row renders exactly one <GenerateStopPlayButton size=\"sm\">, no second adjacent Stop button"
    requirement: GEN-09
    verification:
      - kind: unit
        ref: "grep -c '<GenerateStopPlayButton' frontend/src/components/SegmentTable.tsx == 1 (single call site inside GeneratePlayButton)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Status column, STATUS_BADGE map, StatusBadge function, and dead Badge/AlertCircle/CheckCircle2/Clock/GenerationStatus imports all removed"
    requirement: TBL-05
    verification:
      - kind: unit
        ref: "grep -c 'STATUS_BADGE|function StatusBadge|id: \"status\"' frontend/src/components/SegmentTable.tsx == 0; grep -cE 'AlertCircle|CheckCircle2|Clock' == 0"
        status: pass
    human_judgment: false
  - id: D3
    description: "Voice Instructions editable column added between narrator and text, reusing the generic EditableTextCell (field=\"voice_instructions\")"
    requirement: TBL-05
    verification:
      - kind: unit
        ref: "grep -q 'id: \"voice_instructions\"' and 'field=\"voice_instructions\"' frontend/src/components/SegmentTable.tsx; source read confirms column order select, narrator, voice_instructions, text, controls"
        status: pass
    human_judgment: false
  - id: D4
    description: "generationLocked is consumed as a prop, not re-derived via useGenerationLock"
    requirement: GEN-09
    verification:
      - kind: unit
        ref: "grep -c 'useGenerationLock' frontend/src/components/SegmentTable.tsx == 0"
        status: pass
    human_judgment: false
  - id: D5
    description: "frontend typecheck, lint, and build all pass with no new issues introduced by this plan's edits"
    verification:
      - kind: other
        ref: "cd frontend && npm run typecheck (clean); npm run lint (6 pre-existing issues, same set documented in 07-01-SUMMARY.md, none in files touched by this plan beyond the pre-existing react-hooks/incompatible-library warning on SegmentTable.tsx's own useReactTable call, unrelated to this plan's edits); npm run build (clean, 216ms)"
        status: pass
    human_judgment: false

duration: 14min
completed: 2026-07-15
status: complete
---

# Phase 7 Plan 02: Segment Table — Unified Button + Trimmed Columns Summary

**Replaced `SegmentTable.tsx`'s hand-rolled two-button `GeneratePlayButton` with a thin wrapper over the shared `useGenerateStopPlay`/`<GenerateStopPlayButton>` foundation, deleted the separate Status column and its badge code, and added a Voice Instructions editable column so the table shows exactly 3 editable content columns (Narrator, Voice Instructions, Text).**

## Performance

- **Duration:** 14 min
- **Started:** 2026-07-15T19:52:xx+02:00
- **Completed:** 2026-07-15T20:06:xx+02:00
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Deleted `STATUS_BADGE`, `StatusBadge`, and the `status` column entry entirely, along with the now-dead `Badge`, `AlertCircle`, `CheckCircle2`, `Clock`, and `GenerationStatus` imports.
- Added a `voice_instructions` `columnHelper.display` entry between `narrator` and `text`, reusing the existing generic `EditableTextCell` verbatim (`field="voice_instructions"`) — no new cell component, no backend change. Columns array is now exactly 5 entries: `select`, `narrator`, `voice_instructions`, `text`, `controls`.
- Replaced `GeneratePlayButton`'s internal state (local `isGenerating`/`isStopping`/poll effects/`hasObservedGeneratingRef`) with a single `useGenerateStopPlay({ hasAudio, isExternallyGenerating, poll: true, onGenerate, onStop, onRefresh })` call, rendering one `<GenerateStopPlayButton size="sm">` — amber idle / red generating-stopping / green ready, per GEN-09/GEN-12.
- Preserved the hidden `<audio>` element, `isPlaying` toggle (`onPlay`/`onPause`/`onEnded`), autoplay-on-generate behavior (via a local `autoplayRef` wrapper around the hook's `handleGenerate`), and the per-row `<p className="text-xs text-destructive" role="alert">` error paragraph fed by the hook's `error`.
- `generationLocked` continues to arrive as a prop and gates only the idle button's `disabled` state (`generationLocked && status === "idle"`) — never re-derived via a hook.

## Task Commits

Each task was committed atomically:

1. **Task 1: Delete the Status column + StatusBadge/STATUS_BADGE + dead imports, add Voice Instructions column** - `489998a` (feat)
2. **Task 2: Replace GeneratePlayButton with the shared component wired via useGenerateStopPlay** - `f1662f9` (feat)

**Plan metadata:** committed by orchestrator after wave completion (worktree mode — this agent does not write STATE.md/ROADMAP.md)

## Files Created/Modified
- `frontend/src/components/SegmentTable.tsx` - Status column/badge code removed, Voice Instructions column added, `GeneratePlayButton` internals swapped for the shared hook + component

## Decisions Made
- Autoplay-on-first-generate (existing UX: audio auto-plays once it lands after clicking Generate) is preserved locally in the wrapper via `autoplayRef`, since `useGenerateStopPlay` intentionally has no autoplay concept — that behavior is per-consumer UX, not part of the shared poll/settle/error state machine.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `frontend/node_modules` was not present in this worktree (gitignored) — ran `npm install` before typecheck/lint/build could execute, per the worktree setup note in the executor prompt. No tracked file changes resulted.
- `npm run lint` reports the same 6 pre-existing issues already documented in `07-01-SUMMARY.md` (`CastWizard.tsx`, `ProjectListScreen.tsx`, `SegmentPreview.tsx`, `SegmentTable.tsx`'s pre-existing `useReactTable` incompatible-library warning, `ui/badge.tsx`, `ui/button.tsx`) — none newly introduced by this plan's edits; confirmed no new warnings/errors appear on the lines this plan touched.

## Next Phase Readiness
- `SegmentTable.tsx` now matches TBL-05 (3 editable content columns: Narrator, Voice Instructions, Text) and GEN-09/GEN-12 (single button, color/label is the sole per-row state indicator).
- Plans 07-03 (ConfigPanel character rows + batch), 07-04 (CharacterCard wizard row), and 07-05 (CastWizard layout fix) can proceed independently — no shared code between this plan's edits and their target files beyond the already-landed Plan 01 foundation.
- No blockers.

---
*Phase: 07-unified-generate-stop-play-button-trimmed-segment-table*
*Completed: 2026-07-15*

## Self-Check: PASSED

Verified `frontend/src/components/SegmentTable.tsx` exists and contains the expected changes (grep checks for `STATUS_BADGE`, `id: "status"`, `AlertCircle`/`CheckCircle2`/`Clock`, `field="voice_instructions"`, `id: "voice_instructions"`, `GenerateStopPlayButton`, `useGenerateStopPlay`, `useGenerationLock` all pass as documented above). Both commits (`489998a`, `f1662f9`) verified present in `git log --oneline`.
