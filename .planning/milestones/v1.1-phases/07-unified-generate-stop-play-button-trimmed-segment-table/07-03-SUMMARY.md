---
phase: 07-unified-generate-stop-play-button-trimmed-segment-table
plan: 03
subsystem: ui
tags: [react, typescript, tailwind, frontend-refactor]

# Dependency graph
requires:
  - phase: 07-unified-generate-stop-play-button-trimmed-segment-table
    provides: "GspStatus type, GenerateStopPlayButton presentational component, useGenerateStopPlay hook, outputUrl helper (Plan 01)"
provides:
  - "ConfigPanel.tsx CharacterPreviewRow collapsed to one <GenerateStopPlayButton size=\"sm\"> per character (GEN-10)"
  - "ConfigPanel.tsx batch Generate All/Stop block collapsed to one <GenerateStopPlayButton size=\"default\" className=\"w-full\"> with joined-output green Play (GEN-11, D-04)"
affects: [07-04, 07-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Presentational component + stateful hook split (from Plan 01) now applied at 2 of 4 call sites"
    - "Batch site status derivation via inline precedence ternary (isCancelling -> isSelfRunning -> hasOutput -> idle) instead of the poll-driven hook, since it's SSE-driven"

key-files:
  modified:
    - frontend/src/components/ConfigPanel.tsx

key-decisions:
  - "The batch site's status derivation stays a hand-written ternary (batchStatus) rather than calling useGenerateStopPlay with poll:false — the existing isSelfRunning/isCancelling/hasOutput variables were already correct and SSE-driven; re-deriving them through the hook's isGenerating/isStopping local state would have meant threading three externally-owned booleans through a hook built around one (isExternallyGenerating), adding indirection with no behavior change."
  - "Dropped the 'Resume Generation' label (and the now-dead isResuming/hasAnyComplete/hasAnyIncomplete variables) per UI-SPEC's D-06: GenerateStopPlayButton has one fixed label per status everywhere, and CONTEXT.md explicitly recorded rejecting a batch-specific exception."
  - "Kept the 'Stop interrupts the segment currently generating immediately.' helper paragraph, gated on isBatchRunning as before, even though it's no longer paired with a separate Stop button element — the explanatory copy is still accurate and useful once the button is red."

patterns-established: []

requirements-completed: [GEN-10, GEN-11, GEN-12]

coverage:
  - id: D1
    description: "CharacterPreviewRow renders exactly one GenerateStopPlayButton (no icon Play + separate Stop pair); hasAudio maps from preview_audio_path; subjectLabel interpolates character.name verbatim (Unicode-safe); hidden <audio>/isPlaying playback and per-row error paragraph preserved"
    requirement: GEN-10
    verification:
      - kind: unit
        ref: "source read: ConfigPanel.tsx CharacterPreviewRow renders one <GenerateStopPlayButton>; grep 'GenerateStopPlayButton'/'useGenerateStopPlay' both present"
        status: pass
      - kind: other
        ref: "cd frontend && npm run typecheck && npm run lint (ConfigPanel.tsx: 0 issues)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Batch control is one GenerateStopPlayButton className=w-full; status precedence order isCancelling -> isSelfRunning -> hasOutput -> idle (source order, isSelfRunning checked before hasOutput per Pitfall 2); hidden joined-output <audio src=outputUrl> gated on hasOutput, toggled via onTogglePlay, never auto-played; blue Download button (downloadUrl) unchanged"
    requirement: GEN-11
    verification:
      - kind: unit
        ref: "source read: ConfigPanel.tsx batchStatus ternary (isCancelling ? stopping : isSelfRunning ? generating : hasOutput ? ready : idle); grep 'outputUrl'/'isSelfRunning'/'downloadUrl' all present"
        status: pass
      - kind: other
        ref: "cd frontend && npm run typecheck && npm run lint && npm run build (all pass)"
        status: pass
    human_judgment: true
    rationale: "The load-bearing Pitfall 2 behavior (batch button stays red during an active re-run of a project with existing output_path, never showing a stale green Play) is only provable end-to-end by a real click-through against a running backend — source-read confirms the precedence order is correct, but the human-verify regenerate-with-existing-output check deferred to Plan 05 is the actual proof this doesn't regress under real timing."
  - id: D3
    description: "Editing a character's fields still reverts the button to amber idle via the hook's reactive hasAudio prop read (GEN-12) — no separate status badge exists at this site"
    requirement: GEN-12
    verification:
      - kind: unit
        ref: "source read: hasPreview = Boolean(character.preview_audio_path) feeds useGenerateStopPlay's hasAudio, re-evaluated every render off the character prop; no local status state duplicates it"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-07-15
status: complete
---

# Phase 7 Plan 03: Config Panel — Character Preview & Batch Button Unification Summary

**Collapsed ConfigPanel.tsx's two remaining hand-rolled generate/stop/play implementations (per-character preview row, batch Generate All/Stop) into the shared GenerateStopPlayButton, and added the joined-output green Play state backed by a new hidden `<audio src={outputUrl(project.id)}>`.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-15T22:02:45+02:00
- **Completed:** 2026-07-15T22:07:44+02:00
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- `CharacterPreviewRow` now renders one `<GenerateStopPlayButton size="sm">` per character, wired through `useGenerateStopPlay` (`hasAudio` from `preview_audio_path`, `onGenerate`/`onStop` calling `triggerCharacterPreview`/`cancelCharacterPreview`), replacing the old icon Play/Pause button + conditional "Generate preview"/"Stop" text-button pair and ~50 lines of duplicated local poll/settle state (GEN-10).
- The batch Generate All/Stop block is now one `<GenerateStopPlayButton size="default" className="w-full">` whose `batchStatus` is derived from the existing SSE-driven `isCancelling`/`isSelfRunning`/`hasOutput` booleans in the exact load-bearing precedence order `stopping > generating > ready > idle` (GEN-11, Pitfall 2) — a re-run of a project with an existing `output_path` correctly stays red "Stop Generation" throughout, never showing a stale green Play.
- Added the joined-output preview (D-04): a new hidden `<audio ref={outputAudioRef} src={outputUrl(project.id)}>` gated on `hasOutput`, toggled by a new `isOutputPlaying` state via the button's `onTogglePlay`, never auto-played. The separate blue Download button is completely unchanged and still sits below the unified button in the same `gap-3` Generation section.
- Dropped the batch button's `"Resume Generation"` relabeling (and the now-dead `isResuming`/`hasAnyComplete`/`hasAnyIncomplete` derivations) per UI-SPEC's D-06 mandate for one fixed label set across all 4 sites.

## Task Commits

Each task was committed atomically:

1. **Task 1: Collapse CharacterPreviewRow to the shared component (GEN-10)** - `7a19278` (feat)
2. **Task 2: Unify the batch Generate All control + joined-output Play (GEN-11, D-04)** - `dec685d` (feat)

**Plan metadata:** committed by orchestrator after wave completion (worktree mode — this agent does not write STATE.md/ROADMAP.md)

## Files Created/Modified
- `frontend/src/components/ConfigPanel.tsx` - `CharacterPreviewRow` and the batch Generation block both swap to `<GenerateStopPlayButton>`; adds `isOutputPlaying`/`outputAudioRef` state and a hidden joined-output `<audio>`; removes ~100 lines of duplicated poll/settle/label logic

## Decisions Made
- Kept the batch site's `batchStatus` as a hand-written precedence ternary rather than routing it through `useGenerateStopPlay({ poll: false })` — the existing `isSelfRunning`/`isCancelling`/`hasOutput` were already correct, externally (SSE-)driven booleans; wrapping them in the hook would add an indirection layer (the hook's own `isGenerating`/`isStopping` local state) with no behavioral benefit, matching the plan's "either call the hook with poll:false or keep this ~4-line inline derivation" guidance.
- Dropped `"Resume Generation"` and its supporting `isResuming`/`hasAnyComplete`/`hasAnyIncomplete` variables (dead code once `GenerateStopPlayButton`'s fixed `STATE_LABEL` map takes over) per UI-SPEC D-06, which explicitly records that keeping a batch-specific label was proposed and rejected.
- Kept the "Stop interrupts the segment currently generating immediately." helper paragraph (still gated on `isBatchRunning`) even without a separate Stop button element — the explanatory copy remains accurate once the unified button turns red.

## Deviations from Plan

None - plan executed exactly as written. Two adjacent code comments referencing the now-removed `isRunning`/"the Stop button (gated on isBatchRunning)" were reworded for accuracy as part of the same edit (Rule 1 - comment/code consistency, not a behavior change), committed within Task 2's commit.

## Issues Encountered
- `frontend/node_modules` was not present in this worktree (gitignored, not carried over from the main checkout) — ran `npm install` before `npm run typecheck`/`npm run lint`/`npm run build` could execute. Standard worktree setup per the parallel-execution instructions, introduced no tracked file changes.
- `npm run lint` reports 6 pre-existing errors/warnings in files this plan does not touch (`ProjectListScreen.tsx`, `SegmentPreview.tsx`, `SegmentTable.tsx`, `ui/badge.tsx`, `ui/button.tsx`) — confirmed already present and out of scope in Plan 01's SUMMARY; `ConfigPanel.tsx` itself lints and typechecks clean.

## Next Phase Readiness
- 2 of 4 call sites (`SegmentTable.tsx`'s per-segment button and `CharacterCard.tsx`'s wizard preview button remain) are now on the shared `GenerateStopPlayButton`/`useGenerateStopPlay` foundation; Plans 02/04/05 cover the remaining sites and the segment-table column trim.
- The GEN-11 Pitfall 2 precedence order (isCancelling before isSelfRunning before hasOutput) is implemented and source-verified; the load-bearing real-timing proof (regenerate a project with existing output, confirm the button stays red not green) is deferred to Plan 05's human-verify checkpoint per the plan's own verification note.
- No blockers. `npm run build` succeeds with the new hidden `<audio>` and unified buttons in place.

---
*Phase: 07-unified-generate-stop-play-button-trimmed-segment-table*
*Completed: 2026-07-15*

## Self-Check: PASSED

All modified files verified present: `frontend/src/components/ConfigPanel.tsx`, this SUMMARY.md. Both commits (`7a19278`, `dec685d`) verified present in git log.
