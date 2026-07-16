---
phase: 07-unified-generate-stop-play-button-trimmed-segment-table
fixed_at: 2026-07-15T22:14:23Z
review_path: .planning/phases/07-unified-generate-stop-play-button-trimmed-segment-table/07-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 7: Code Review Fix Report

**Fixed at:** 2026-07-15T22:14:23Z
**Source review:** .planning/phases/07-unified-generate-stop-play-button-trimmed-segment-table/07-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (Critical: 3, Warning: 5 — fix_scope=critical_warning, Info findings IN-01..IN-04 excluded)
- Fixed: 8
- Skipped: 0

All fixes verified with `npx tsc -b --noEmit` (no errors, including no new errors in modified files) after each individual change, in addition to re-reading the modified sections.

## Fixed Issues

### CR-01: Model swap isn't blocked while a generation is in flight

**Files modified:** `frontend/src/components/ConfigPanel.tsx`
**Commit:** b86f38e
**Applied fix:** Added `generationLocked` to the Model `<Select>`'s `disabled` prop (alongside the existing `isSwapping`) and added a `title` on `SelectTrigger` explaining why it's disabled when locked but not currently swapping — matching the `disabledReason` pattern used by `GenerateStopPlayButton` elsewhere in this panel.

### CR-02: `handleStop` optimistically cleared "generating" state even when the stop request failed

**Files modified:** `frontend/src/hooks/useGenerateStopPlay.ts`
**Commit:** a6ba075
**Applied fix:** Moved `setIsGenerating(false)`/`setIsStopping(false)`/`onRefresh()` into the success path (after `await onStop()` resolves) instead of an unconditional `finally`. The `catch` branch now only clears `isStopping` and sets the error, leaving `isGenerating` untouched so a failed stop doesn't misrepresent a still-running generation as stopped.

### CR-03: A batch failure with zero failed segments was completely silent

**Files modified:** `frontend/src/components/ConfigPanel.tsx`
**Commit:** b4697e3
**Applied fix:** Added a `role="alert"` error branch that fires whenever `generation.status === "error" && failedCount === 0`, alongside the existing `joinBlocked` branch. Confirmed `GenerationStreamState` (`useGenerationStream.ts`) already carries an `errorDetail` field from the SSE `error` event, so the new branch renders that message when present, falling back to a generic string otherwise (per the review's own suggestion to check for this).

### WR-01: Settle logic in `useGenerateStopPlay` depended on an invariant enforced only by a different component

**Files modified:** `frontend/src/hooks/useGenerateStopPlay.ts`
**Commit:** 05dde08
**Applied fix:** The review's literal suggested diff (set `hasObservedGeneratingRef.current = true` synchronously inside `handleGenerate`, and drop the `isGenerating && !hasAudio` half of the settle effect's condition) was traced through and found to introduce a real regression: since the ref would already read `true` by the time the settle effect's first run fires after the click (ref mutation happens synchronously, before React flushes the batched state update + effect), the effect would immediately clear `isGenerating` back to `false` right after every Generate click, breaking the "generating" spinner state entirely for all self-triggered sites. Applied a corrected fix instead: snapshot `hasAudio`'s value at the moment `handleGenerate` fires into `hadAudioAtGenerateStartRef`, and compare against that snapshot (`hasAudio === hadAudioAtGenerateStartRef.current`) instead of a hardcoded `!hasAudio`. This reproduces the exact current behavior bit-for-bit for the real-world path (where the snapshot is always `false`, since `GenerateStopPlayButton` only calls `onGenerate` while `hasAudio` is false), while also correctly marking "still generating, don't clear yet" for the previously-unreachable case where `handleGenerate` is invoked while `hasAudio` is already `true`. The residual case where `hasAudio` never transitions at all (a boolean, not a version counter, so a same-state regeneration is undetectable from it alone) remains bounded by the pre-existing WR-02 poll-ceiling timeout (`GENERATION_POLL_CEILING_MS`, ~330s) rather than truly stuck forever.

### WR-02: Poll-ceiling effect keyed on `onRefresh` identity could indefinitely reset the stuck-forever safety net

**Files modified:** `frontend/src/hooks/useGenerateStopPlay.ts`
**Commit:** 48350ae
**Applied fix:** Added an `onRefreshRef` that's kept current via a separate effect, and changed the poll/ceiling effect's `setInterval` callback to call `onRefreshRef.current()` instead of `onRefresh` directly, removing `onRefresh` from that effect's dependency array. The timer's lifecycle (and therefore the `GENERATION_POLL_CEILING_MS` countdown) is now decoupled from `onRefresh`'s identity, so a parent re-render that hands down a fresh closure no longer tears down and restarts the ceiling timer.

### WR-03: Several async handlers in `CastWizard`/`CharacterCard` had no error handling

**Files modified:** `frontend/src/components/CastWizard.tsx`, `frontend/src/components/CharacterCard.tsx`
**Commit:** 00660b7
**Applied fix:** Added the `errorMessage`/`role="alert"` pattern (already used elsewhere in both files) to all four flagged call sites: `CastWizard.refetch` and `CastWizard.handleUndoMerge` now have `.catch()` handlers feeding a new `castError` state rendered near the top of the wizard; `CharacterCard.saveField` and `CharacterCard.confirmMerge` now have `try/catch` feeding new `saveError` (rendered below the name/voice-instructions fields) and `mergeError` (rendered inside the merge dialog, cleared on dialog close) states respectively.

### WR-04: Preview/segment/output audio URLs were fixed per-id with no cache-busting

**Files modified:** `frontend/src/api/client.ts`, `frontend/src/hooks/useGenerateStopPlay.ts`, `frontend/src/components/CharacterCard.tsx`, `frontend/src/components/ConfigPanel.tsx`, `frontend/src/components/SegmentTable.tsx`
**Commit:** 8f7fc4c
**Applied fix:** `previewUrl`, `segmentAudioUrl`, and `outputUrl` in `client.ts` now accept an optional `version` param appended as a `?v=` query string. `useGenerateStopPlay` now tracks and returns an `audioVersion` counter, incremented only when the settle effect genuinely observes a generating->settled transition (i.e. exactly when new audio landed) — this is passed through by `CharacterPreviewRow`/`CharacterCard`/`SegmentTable.GeneratePlayButton`, all of which use the shared hook. For the batch output URL (no `useGenerateStopPlay` involved in `ConfigPanel`'s top-level batch section), added a separate `outputVersion` counter bumped via the render-time state-adjustment pattern already used in this file (`lastSyncedFilename`) whenever `generation.status` transitions to `"ready"`.

### WR-05: `autoplayRef` stayed `true` after a failed generate, risking an unrelated future autoplay

**Files modified:** `frontend/src/components/SegmentTable.tsx`
**Commit:** a49969d
**Applied fix:** Added a small effect keyed on `error` (from `useGenerateStopPlay`) that resets `autoplayRef.current = false` whenever an error is set, so a failed generation no longer leaves the ref armed to autoplay whatever audio the row happens to pick up later through an unrelated trigger.

## Skipped Issues

None — all 8 in-scope findings were fixed.

---

_Fixed: 2026-07-15T22:14:23Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
