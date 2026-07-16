---
phase: 07-unified-generate-stop-play-button-trimmed-segment-table
plan: 05
subsystem: ui
tags: [react, vite, generate-stop-play, human-verify]

# Dependency graph
requires:
  - phase: 07-02
    provides: GenerateStopPlayButton on segment rows, trimmed segment table (TBL-05)
  - phase: 07-03
    provides: GenerateStopPlayButton on ConfigPanel character rows and batch Generate All
  - phase: 07-04
    provides: GenerateStopPlayButton on CastWizard CharacterCard rows, layout fix (D-05)
provides:
  - Human sign-off that all four unified button sites, joined-output Play, GEN-12 edit-reverts behavior, the trimmed segment table, and the CastWizard layout fix work end-to-end in a real browser on the deploy target
  - Vite dev proxy covering /segments and /generation-status
  - useGenerateStopPlay settling for self-triggered generation when no external status signal exists (character previews)
  - GenerateStopPlayButton idleLabel prop, used by the batch control ("Generate All")
affects: [frontend generation UX, any future phase touching GenerateStopPlayButton or useGenerateStopPlay]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "GenerateStopPlayButton idleLabel prop overrides only the idle-state label; every other state/behavior stays shared across call sites."
    - "useGenerateStopPlay settle effect treats 'isGenerating true + hasAudio not yet true' as an observed-generating state for self-triggered (no external signal) callers, in addition to the existing isExternallyGenerating transition path."

key-files:
  created: []
  modified:
    - frontend/vite.config.ts
    - frontend/src/hooks/useGenerateStopPlay.ts
    - frontend/src/components/ConfigPanel.tsx
    - frontend/src/components/GenerateStopPlayButton.tsx

key-decisions:
  - "Fixed the settle-on-self-trigger bug once in the shared useGenerateStopPlay hook rather than per-caller, since CharacterPreviewRow and CharacterCard both hardcode isExternallyGenerating: false by design."
  - "idleLabel is optional and defaults to the existing 'Generate Preview' string, so only ConfigPanel's batch button needed a call-site change."

patterns-established: []

requirements-completed: [GEN-09, GEN-10, GEN-11, GEN-12, TBL-05]

coverage:
  - id: D1
    description: "Segment table shows exactly 3 editable content columns (Narrator | Voice Instructions | Text), no Status column; row button is amber/red/green Generate/Stop/Play"
    requirement: "TBL-05"
    verification:
      - kind: manual_procedural
        ref: "07-05-PLAN.md how-to-verify step 1-3"
        status: pass
    human_judgment: true
    rationale: "Visual/interactive color-state and layout verification with no frontend test framework in this project — requires a human looking at a real browser."
  - id: D2
    description: "Segment row Generate/Stop/Play button cycles amber -> red -> green correctly and plays generated audio"
    requirement: "GEN-09"
    verification:
      - kind: manual_procedural
        ref: "07-05-PLAN.md how-to-verify step 2"
        status: pass
    human_judgment: true
    rationale: "Interactive button-state and audio-playback verification requires a human in a real browser."
  - id: D3
    description: "Editing segment Text or Voice Instructions reverts the row button to amber Generate Preview with no separate status badge"
    requirement: "GEN-12"
    verification:
      - kind: manual_procedural
        ref: "07-05-PLAN.md how-to-verify step 3"
        status: pass
    human_judgment: true
    rationale: "Visual state-revert verification requires a human in a real browser."
  - id: D4
    description: "ConfigPanel character preview row follows the same Generate/Stop/Play pattern and reverts on edit"
    requirement: "GEN-10"
    verification:
      - kind: manual_procedural
        ref: "07-05-PLAN.md how-to-verify step 4"
        status: pass
    human_judgment: true
    rationale: "Interactive button-state verification requires a human in a real browser."
  - id: D5
    description: "CastWizard CharacterCard preview control uses the same button with a working mid-flight Stop, and the character-card column sizes to content instead of stretching full height"
    requirement: "GEN-10"
    verification:
      - kind: manual_procedural
        ref: "07-05-PLAN.md how-to-verify step 5"
        status: pass
    human_judgment: true
    rationale: "Interactive Stop behavior and layout sizing require a human in a real browser."
  - id: D6
    description: "Batch Generate All button cycles amber -> red -> green and plays the joined output; Download stays a separate button"
    requirement: "GEN-11"
    verification:
      - kind: manual_procedural
        ref: "07-05-PLAN.md how-to-verify step 6"
        status: pass
    human_judgment: true
    rationale: "Interactive batch-run and playback verification requires a human in a real browser."
  - id: D7
    description: "Pitfall 2 regression check: re-running Generate All on a project that already has a completed joined output shows red Stop Generation during the re-run, never green Play (would otherwise play the stale file)"
    requirement: "GEN-11"
    verification:
      - kind: manual_procedural
        ref: "07-05-PLAN.md how-to-verify step 7 (mandatory)"
        status: pass
    human_judgment: true
    rationale: "Silent-correctness regression explicitly flagged by phase research as requiring live human confirmation, not just a passing build."

duration: 2min
completed: 2026-07-15
status: complete
---

# Phase 7 Plan 05: Human Verification Sign-off Summary

**All four unified Generate/Stop/Play button sites, the joined-output Play, GEN-12 edit-reverts, the trimmed 3-column segment table, and the CastWizard layout fix are confirmed working end-to-end in a real browser on the deploy target, after fixing 3 bugs surfaced during the first verification pass.**

## Performance

- **Duration:** 2 min (this closing session; full plan including the build/serve task and the two verification passes spanned the prior session)
- **Completed:** 2026-07-15T22:40:00Z
- **Tasks:** 2 (Task 1: build/serve — done earlier; Task 2: human-verify checkpoint — done this session)
- **Files modified:** 4 (across the 3 deviation-fix commits)

## Accomplishments

- Confirmed the segment table's trimmed 3-column layout (Narrator | Voice Instructions | Text, no Status column) live in the browser (TBL-05)
- Confirmed the unified amber/red/green Generate/Stop/Play button works correctly on segment rows, ConfigPanel character rows, and CastWizard CharacterCard rows (GEN-09, GEN-10)
- Confirmed GEN-12 edit-reverts-to-amber behavior on both segment Text edits and Voice Instructions cell edits
- Confirmed the batch "Generate All" control and joined-output Play work correctly, including the critical Pitfall 2 regenerate-with-existing-output case (red Stop Generation during re-run, never a stale green Play) (GEN-11)
- Confirmed the CastWizard character-card column sizes to content instead of stretching to full viewport height (D-05)
- Fixed 3 real bugs surfaced by the first verification pass; all 7 how-to-verify steps passed on re-test

## Task Commits

Task 1 (build and serve) and its deviation fixes were committed in the prior session:

1. **Task 1: Build and serve the frontend for verification** - `a2b73d0` (docs)
2. **Deviation fix: proxy /segments and /generation-status** - `9e2fe56` (fix)
3. **Deviation fix: settle self-triggered generation with no external signal** - `09d01f7` (fix)
4. **Deviation fix: label batch button "Generate All"** - `e4ba4d0` (fix)
5. **Task 2: Human-verify checkpoint** - no code commit (verification-only task); user responded "approved" after re-testing all 7 steps with the fixes applied

**Plan metadata:** this commit (docs: complete 07-05 plan)

## Files Created/Modified

- `frontend/vite.config.ts` - Added `/segments` and `/generation-status` to the dev proxy map so segment generate/cancel/patch/audio and status-poll routes reach the FastAPI backend instead of 404ing in Vite's dev server
- `frontend/src/hooks/useGenerateStopPlay.ts` - Settle effect now also fires when `isGenerating` is true and `hasAudio` catches up with no external status signal held, fixing character preview rows (ConfigPanel, CastWizard) that hardcode `isExternallyGenerating: false`
- `frontend/src/components/ConfigPanel.tsx` - Batch Generate All button now passes `idleLabel="Generate All"`
- `frontend/src/components/GenerateStopPlayButton.tsx` - Added optional `idleLabel` prop that overrides only the idle-state label, defaulting to the existing "Generate Preview" string

## Decisions Made

- Fixed the self-trigger settle bug once, in the shared `useGenerateStopPlay` hook, rather than patching `CharacterPreviewRow` and `CharacterCard` individually — both callers route through the same hook and hardcode `isExternallyGenerating: false` by design, so a single guard covers both call sites.
- Made `idleLabel` an optional prop on `GenerateStopPlayButton` (default: existing "Generate Preview" text) so only the one batch call site needed a change; every other consumer is unaffected.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Vite dev proxy missing /segments and /generation-status routes**
- **Found during:** Task 2, first human-verify pass, step 2 (clicking "Generate Preview" on a segment row)
- **Issue:** `vite.config.ts`'s dev proxy only forwarded `/projects`, `/characters`, `/voices` to FastAPI. Every `/segments/*` route (generate, cancel, patch, bulk-reassign, audio.wav) and `/generation-status` fell through to Vite's own 404, so segment generation failed immediately in the dev server.
- **Fix:** Added `/segments` and `/generation-status` to the proxy map, matching every route `client.ts` actually calls.
- **Files modified:** `frontend/vite.config.ts`
- **Verification:** Re-tested step 2 in browser — segment generation now reaches the backend and completes.
- **Committed in:** `9e2fe56`

**2. [Rule 1 - Bug] Character preview buttons never settled from red spinner to green Play**
- **Found during:** Task 2, first human-verify pass, step 4/5 (character preview and CastWizard rows)
- **Issue:** `useGenerateStopPlay`'s only settle path cleared `isGenerating`/`isStopping` on a transition of `isExternallyGenerating`. Segments have a real external signal (`segment.generation_status`), so that path works for `SegmentTable`. Character previews have no such field on the `Character` model — `CharacterPreviewRow` (ConfigPanel) and `CharacterCard` both call the hook with `isExternallyGenerating: false` (hardcoded by design), so the settle effect never fired for them: the button stayed a red spinner forever after a self-triggered generate, even once `hasAudio` flipped true.
- **Fix:** The settle effect now also treats "`isGenerating` is true and `hasAudio` hasn't caught up yet" as an observed-generating state, so once `hasAudio` goes true while nothing external is holding the row generating, the ref-guarded branch settles it. Safe for every current caller because the button only ever calls `onGenerate` while status is `"idle"`, which requires `hasAudio` to already be false — no stale-audio window this could prematurely settle through, unlike the batch-rerun case the external-signal branch exists for.
- **Files modified:** `frontend/src/hooks/useGenerateStopPlay.ts`
- **Verification:** Re-tested steps 4 and 5 in browser — character preview and CastWizard buttons now flip red -> green correctly.
- **Committed in:** `09d01f7`

**3. [Rule 1 - Bug] Batch button labeled "Generate Preview" instead of "Generate All"**
- **Found during:** Task 2, first human-verify pass, step 6 (batch Generate All button)
- **Issue:** `STATE_LABEL.idle` in `GenerateStopPlayButton` is a single hardcoded "Generate Preview" string shared by every idle-state consumer. The ConfigPanel batch button reuses the same component/status machine as the per-row and per-character buttons, so it inherited the same idle label even though its action generates every segment, not a single preview.
- **Fix:** Added an optional `idleLabel` prop to `GenerateStopPlayButton` that overrides `STATE_LABEL.idle` only in the idle state. ConfigPanel's batch button now passes `idleLabel="Generate All"`; every other call site is unaffected (prop is optional).
- **Files modified:** `frontend/src/components/ConfigPanel.tsx`, `frontend/src/components/GenerateStopPlayButton.tsx`
- **Verification:** Re-tested step 6 in browser — batch button now reads "Generate All" in the idle state.
- **Committed in:** `e4ba4d0`

---

**Total deviations:** 3 auto-fixed (all Rule 1 - bugs surfaced by real-browser human verification, not caught by typecheck/lint/build)
**Impact on plan:** All three fixes were necessary for the plan's own acceptance criteria (steps 2, 4, 5, 6 of the how-to-verify list) to pass. No scope creep — each fix stayed within the shared component/hook the plan's four sites already route through.

## Issues Encountered

None beyond the 3 deviations above, which were resolved and re-verified within this checkpoint.

## User Setup Required

None - no external service configuration required.

## Human Verification Record

- **First pass:** user found 3 bugs (proxy 404s, character preview buttons stuck on red, batch button mislabeled) — reported via checkpoint resume signal, not "approved"
- **Fixes applied:** commits `9e2fe56`, `09d01f7`, `e4ba4d0` (see Deviations above)
- **Second pass:** user re-ran all 7 how-to-verify steps from `07-05-PLAN.md` on the deploy target and responded **"approved"**
- **Pitfall 2 check (step 7, mandatory):** confirmed — re-running Generate All on a project with an existing joined output shows red "Stop Generation" during the re-run, never a stale green "Play"

## Dev Environment Note

A Vite dev server (`npm run dev --host 100.76.155.0 --port 5173`) and the FastAPI backend (port 8000) were left running on the deploy target for this verification and remain running — the user may continue exploratory testing. No action needed to tear them down as part of this plan.

## Next Phase Readiness

- Phase 7's five success criteria (GEN-09, GEN-10, GEN-11, GEN-12, TBL-05, plus D-05 layout) are all human-confirmed live in a browser.
- This closes out Phase 7 (Unified Generate/Stop/Play Button & Trimmed Segment Table) — the last phase in the v1.1 "Generation UX & Config Rework" milestone roadmap.
- No blockers carried forward from this plan.

---
*Phase: 07-unified-generate-stop-play-button-trimmed-segment-table*
*Completed: 2026-07-15*

## Self-Check: PASSED

All referenced commits (a2b73d0, 9e2fe56, 09d01f7, e4ba4d0) and files (frontend/vite.config.ts, frontend/src/hooks/useGenerateStopPlay.ts, frontend/src/components/ConfigPanel.tsx, frontend/src/components/GenerateStopPlayButton.tsx) confirmed present on disk/in git log.
