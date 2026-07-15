---
phase: 07-unified-generate-stop-play-button-trimmed-segment-table
verified: 2026-07-15T21:47:12Z
status: passed
score: 5/5 must-haves verified (roadmap success criteria); 38/38 plan-level must_have truths verified
behavior_unverified: 0 # All behavior-dependent truths (state transitions, precedence, edit-reverts) already have live-browser human evidence from the 07-05 checkpoint (approved after 3 bug fixes, commits 9e2fe56/09d01f7/e4ba4d0) — none left unexercised
overrides_applied: 0
---

# Phase 7: Unified Generate/Stop/Play Button & Trimmed Segment Table Verification Report

**Phase Goal:** Every place audio is generated (segment, character preview, batch) uses one consistent yellow/red/green generate/stop/play UI component, and the segment table shows only the 3 core editable columns with no separate status indicator.
**Verified:** 2026-07-15T21:47:12Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Each segment row shows a single yellow/red/green button | VERIFIED | `SegmentTable.tsx:105-134` — `GeneratePlayButton` renders exactly one `<GenerateStopPlayButton size="sm">` fed by `useGenerateStopPlay`; `STATE_CLASSES`/`STATE_LABEL` in `GenerateStopPlayButton.tsx:32-46` match amber/red/green + the 4 labels verbatim. Human-confirmed live (07-05-SUMMARY.md step 2, "approved"). |
| 2 | Each character preview control follows the same pattern | VERIFIED | `ConfigPanel.tsx:93-103` (`CharacterPreviewRow`) and `CharacterCard.tsx:199-209` both render one `<GenerateStopPlayButton>` fed by `useGenerateStopPlay`. Human-confirmed live (07-05-SUMMARY.md steps 4-5, "approved"). |
| 3 | Generate All follows the same pattern + green Play for joined output | VERIFIED | `ConfigPanel.tsx:292-298` derives `batchStatus` in order `isCancelling → isSelfRunning → hasOutput → idle`; `ConfigPanel.tsx:392-413` renders one `<GenerateStopPlayButton className="w-full">` plus a hidden `<audio src={outputUrl(project.id)}>` gated on `hasOutput`, toggled via `onTogglePlay`. Blue Download stays a separate `<Button>` (`ConfigPanel.tsx:441-456`). Human-confirmed live including the mandatory Pitfall-2 regenerate-with-existing-output case (07-05-SUMMARY.md step 6-7, "approved"). |
| 4 | Editing text/voice/narrator reverts control to yellow, no separate status badge | VERIFIED | `useGenerateStopPlay.ts:137-143` derives `status` purely from `hasAudio`/`isRowGenerating`/`isStopping` props (no independent status field) — editing clears server-side audio/generation_status via PATCH, `hasAudio` goes false, hook reactively returns `idle`. No status text/icon renders anywhere near any of the 4 buttons (confirmed by absence of `STATUS_BADGE`/`StatusBadge` in the whole frontend tree, see Anti-Patterns below). Human-confirmed live for segment Text, segment Voice Instructions cell, and character edits (07-05-SUMMARY.md steps 3-4, "approved"). |
| 5 | Segment table shows exactly 3 editable columns (Narrator, Voice Instructions, Text), Status column gone | VERIFIED | `SegmentTable.tsx:321-386` — `columns` array has exactly 5 entries in order `select, narrator, voice_instructions, text, controls`; `grep -c 'id: "status"'` and `grep -c 'STATUS_BADGE'` both return 0. Human-confirmed live (07-05-SUMMARY.md step 1, "approved"). |

**Score:** 5/5 roadmap success criteria verified. All state-transition/precedence truths are behavior-dependent by nature (no frontend test framework exists in this project — confirmed by `deferred-items.md` and `07-05-PLAN.md`'s own rationale for a human-verify checkpoint plan); each one already has live-browser human evidence from the completed 07-05 UAT checkpoint (approved on the second pass, after 3 real bugs found on the first pass were fixed in commits `9e2fe56`, `09d01f7`, `e4ba4d0`, all of which are present in the current working tree — confirmed via `git log`). No item is left in `behavior_unverified`.

### Plan-Level Must-Have Truths (38 total across Plans 01-04)

All 38 `must_haves.truths` entries from the four execute plans (07-01 through 07-04) were checked individually against source. All VERIFIED. Representative spot-checks (full set traced during verification):

| Plan | Truth (abbreviated) | Status | Evidence |
|------|---------------------|--------|----------|
| 01 | GspStatus precedence `stopping > generating > ready > idle` | VERIFIED | `useGenerateStopPlay.ts:137-143` |
| 01 | Exactly one `<Button>` per site, STATE_CLASSES/STATE_LABEL exact | VERIFIED | `GenerateStopPlayButton.tsx:32-46,90-111`; `grep -c '<Button' GenerateStopPlayButton.tsx` = 1 |
| 01 | `outputUrl` == `downloadUrl` route string | VERIFIED | `client.ts:320-330` — both return `/projects/${projectId}/download` |
| 02 | Status column/badge/dead imports fully deleted; Voice Instructions column added; 5-entry columns array | VERIFIED | `SegmentTable.tsx:321-386`; `grep -c 'STATUS_BADGE\|AlertCircle\|CheckCircle2'` = 0 |
| 02 | Voice Instructions reuses generic `EditableTextCell`, no new component | VERIFIED | `SegmentTable.tsx:351-362`, `field="voice_instructions"` |
| 02 | `Loader2` kept (bulk-reassign toolbar) | VERIFIED | `SegmentTable.tsx:8,289` |
| 03 | Batch precedence `isCancelling → isSelfRunning → hasOutput → idle` (Pitfall 2) | VERIFIED | `ConfigPanel.tsx:292-298` — `isSelfRunning` checked strictly before `hasOutput` |
| 03 | Joined-output `<audio>` gated on `hasOutput`, no auto-play | VERIFIED | `ConfigPanel.tsx:405-413` — conditionally rendered, only `onTogglePlay` drives playback |
| 03 | Download button unchanged, separate from unified button | VERIFIED | `ConfigPanel.tsx:441-456` — distinct `<Button asChild={hasOutput}>` |
| 04 | CharacterCard's hardcoded 60000ms ceiling removed, shared `GENERATION_POLL_CEILING_MS` used | VERIFIED | `grep -c '60000' CharacterCard.tsx` = 0; `useGenerateStopPlay.ts` imports `GENERATION_POLL_CEILING_MS` |
| 04 | CharacterCard surrounding fields untouched (Input/Select/Textarea/Badge/Dialog) | VERIFIED | `CharacterCard.tsx:148-282` — all present and unmodified in shape |
| 04 | CastWizard gains exactly one class `xl:items-start` | VERIFIED | `CastWizard.tsx:108` |
| 04 | `SegmentPreview.tsx` NOT modified | VERIFIED | `git log -- frontend/src/components/SegmentPreview.tsx` shows last touch predates all Phase 7 commits (`d3b1825`, 2026-07-10-era) |
| 03 | GEN-11 ordering (backstop): batch is a singleton, no per-item ordering applies | VERIFIED (by construction) | Only one `<GenerateStopPlayButton>` renders for the batch site — no list/iteration exists for this control, so the claim is trivially true given the code structure inspected above |

No must_have truth failed. No artifact was missing or stub. All key_links (hook imports `GENERATION_POLL_CEILING_MS`/`errorMessage` from `client.ts`; `GenerateStopPlayButton` passes `STATE_CLASSES` through `cn()`; controls cells compute `hasAudio`/`isExternallyGenerating` and feed the hook; `generationLocked` arrives as a prop everywhere, never re-derived via `useGenerationLock()` inside the hook/button/table/panel/card) were confirmed present and wired.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/GenerateStopPlayButton.tsx` | New presentational component | VERIFIED | Exists, exports `GenerateStopPlayButton` + `GenerateStopPlayButtonProps`, one `<Button>`, correct STATE_CLASSES/STATE_LABEL, `idleLabel` override added during 07-05 |
| `frontend/src/hooks/useGenerateStopPlay.ts` | New shared hook | VERIFIED | Exists, exports `useGenerateStopPlay` + `GspStatus` + `UseGenerateStopPlayOptions`, correct precedence, poll/settle/error logic |
| `frontend/src/api/client.ts` (outputUrl) | New helper | VERIFIED | `outputUrl(projectId)` exported, identical route to `downloadUrl` |
| `frontend/src/components/SegmentTable.tsx` | Modified — unified button + trimmed columns | VERIFIED | 5-column array, one button per row, Status/badge code fully deleted |
| `frontend/src/components/ConfigPanel.tsx` | Modified — character rows + batch unified | VERIFIED | `CharacterPreviewRow` and batch block both use shared component/hook; joined-output `<audio>` added |
| `frontend/src/components/CharacterCard.tsx` | Modified — wizard row unified, gains Stop | VERIFIED | Shared component/hook wired; 60s ceiling removed |
| `frontend/src/components/CastWizard.tsx` | Modified — layout fix | VERIFIED | `xl:items-start` present, inner column classes untouched |
| `frontend/src/components/SegmentPreview.tsx` | Must stay unmodified | VERIFIED | Untouched since before Phase 7 (per git log) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `useGenerateStopPlay.ts` | `client.ts` | imports `GENERATION_POLL_CEILING_MS`, `errorMessage` | WIRED | `useGenerateStopPlay.ts:11` |
| `GenerateStopPlayButton.tsx` | Button's className merge | `cn(STATE_CLASSES[status], className)` | WIRED | `GenerateStopPlayButton.tsx:98` |
| `SegmentTable.tsx` controls cell | `useGenerateStopPlay` + `GenerateStopPlayButton` | `hasAudio`/`isExternallyGenerating` derivation | WIRED | `SegmentTable.tsx:72-81,107-117` |
| `ConfigPanel.tsx` `CharacterPreviewRow` | `useGenerateStopPlay` + `GenerateStopPlayButton` | same pattern | WIRED | `ConfigPanel.tsx:70-103` |
| `ConfigPanel.tsx` batch block | inline `batchStatus` derivation (SSE, `poll` not used) + `GenerateStopPlayButton` | `isCancelling`/`isSelfRunning`/`hasOutput` | WIRED | `ConfigPanel.tsx:292-298,392-404` |
| `CharacterCard.tsx` | `useGenerateStopPlay` + `GenerateStopPlayButton` | same pattern | WIRED | `CharacterCard.tsx:74-86,199-209` |
| `outputUrl(project.id)` | hidden joined-output `<audio>` | `src` attribute | WIRED | `ConfigPanel.tsx:408` |
| `generationLocked` prop | idle-state `disabled` on all 4 sites | prop pass-through (no `useGenerationLock()` re-derivation) | WIRED | Confirmed via grep: `useGenerationLock` called only in `CastWizard.tsx` and `ProjectScreen.tsx` (parent screens), never inside the hook/button/table/panel/card |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Frontend typechecks clean | `cd frontend && npm run typecheck` | No errors | PASS |
| Frontend builds clean | `cd frontend && npm run build` | Built in 185ms, no errors | PASS |
| Lint clean on Phase-7 files (whole-project lint has 3 pre-existing unrelated errors) | `cd frontend && npm run lint` | 3 errors in `badge.tsx`/`button.tsx`/`ProjectListScreen.tsx` (shadcn boilerplate + unrelated screen, confirmed pre-existing via `git log` and `deferred-items.md`); 0 errors in any Phase-7-modified file | PASS (scoped) |
| No `useGenerationLock()` inside hook/button | `grep -c useGenerationLock` on `useGenerateStopPlay.ts`, `GenerateStopPlayButton.tsx` | 0 | PASS |
| No dead Status-badge code remains anywhere | `grep -rn 'STATUS_BADGE\|StatusBadge' frontend/src` | 0 matches | PASS |
| No debt markers (TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER) in Phase-7-modified files | `grep -inE` across the 8 modified files | 0 matches | PASS |

Full app-run/manual-browser behavior (button color cycling, Stop mid-flight, edit-reverts, Pitfall-2 regenerate case) was already exercised and confirmed by the completed 07-05 human-verify checkpoint — not re-run here per the task's guidance to avoid duplicating completed human UAT.

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|-------------|--------|----------|
| GEN-09 | 07-02, 07-05 | Per-row segment control is single yellow/red/green button | SATISFIED | `SegmentTable.tsx` `GeneratePlayButton` wrapper |
| GEN-10 | 07-03, 07-04, 07-05 | Character preview control (ConfigPanel + CharacterCard) follows same pattern | SATISFIED | `ConfigPanel.tsx` `CharacterPreviewRow`, `CharacterCard.tsx` |
| GEN-11 | 07-03, 07-05 | Generate All follows same pattern + green Play for joined output | SATISFIED | `ConfigPanel.tsx` batch block, Pitfall-2 precedence order verified |
| GEN-12 | 07-01, 07-02, 07-03, 07-04, 07-05 | Any invalidating edit reverts control to yellow, single source of truth | SATISFIED | `useGenerateStopPlay.ts` status derivation is purely prop-driven |
| TBL-05 | 07-02, 07-05 | Segment table shows exactly 3 editable columns, Status column gone | SATISFIED | `SegmentTable.tsx` 5-entry columns array |

All 5 requirement IDs declared in the phase (`GEN-09, GEN-10, GEN-11, GEN-12, TBL-05`) are covered by at least one plan and cross-referenced in REQUIREMENTS.md (`.planning/REQUIREMENTS.md` lines 15-18, 30 — all marked `[x]` Complete, Phase 7). No orphaned requirements found: the union of every plan's `requirements:` frontmatter field (`GEN-12` ∪ `GEN-09,GEN-12,TBL-05` ∪ `GEN-10,GEN-11,GEN-12` ∪ `GEN-10,GEN-12` ∪ `GEN-09,GEN-10,GEN-11,GEN-12,TBL-05`) exactly equals the phase's declared requirement set.

### Anti-Patterns Found

None blocking. No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers, no empty stub implementations, no hardcoded-empty props in any of the 8 files this phase modified (`client.ts`, `useGenerateStopPlay.ts`, `GenerateStopPlayButton.tsx`, `SegmentTable.tsx`, `ConfigPanel.tsx`, `CharacterCard.tsx`, `CastWizard.tsx`, `vite.config.ts`).

**Code review advisory findings (07-REVIEW.md) — assessed against must_haves, none invalidate a phase truth:**

| ID | Finding | Invalidates a must_have truth? |
|----|---------|-------------------------------|
| CR-01 | Model swap `<Select>` in ConfigPanel isn't gated behind `generationLocked` (only `isSwapping`) | No — Model swap is a Phase 5 (CFG-04) control, not one of the 4 GEN-09/10/11/12 button sites or TBL-05's column set. Real concurrency risk, but out of this phase's must_have scope. |
| CR-02 | `useGenerateStopPlay.handleStop`'s `finally` block optimistically clears `isGenerating` even when `onStop()` throws | No — the precedence-order truths (`stopping > generating > ready > idle`) still hold structurally; this is an edge-case correctness gap on the network-failure path of Stop, not a violation of the documented button-state contract. Worth fixing but doesn't falsify a stated must_have. |
| CR-03 | A batch failure with `failedCount === 0` renders no error text anywhere (button silently reverts to idle) | No — GEN-11's must_haves cover the yellow/red/green precedence and the joined-output Play; they don't claim every failure mode surfaces an error message. Real UX gap, not a phase-goal violation. |

These 3 Critical findings are real, valuable follow-up work (especially CR-01, which has genuine GPU-state-corruption risk per CLAUDE.md's single-GPU constraint) but are advisory to this phase's goal as scoped by its must_haves and the roadmap's 5 success criteria — none of them is listed as a phase requirement or must_have truth. Recommend tracking as a fast-follow, not as a Phase 7 gap.

### Prohibitions (must_haves.prohibitions — judgment-tier, non-authoritative)

Per task guidance, these entries are descriptor-less and carry a flagged-unverified disposition by design (LLM-judge, not a hard gate). Reviewed against code for plausibility — no violation observed in any case, but flagged here per the fail-closed default rather than silently passed:

- "The amber/red/green state colors must not be promoted to app-wide `--warning`/`--success` CSS custom properties" — `index.css` not touched by this phase (not in any plan's `files_modified`); colors remain inline in `STATE_CLASSES` only. **flagged: human review recommended** (non-authoritative LLM judgment).
- "`GenerateStopPlayButton`/`useGenerateStopPlay` must not call `useGenerationLock()` themselves" — confirmed via grep (0 matches in both files). **flagged: human review recommended** (non-authoritative LLM judgment, though grep evidence here is strong).
- "No 4th 'queued' button state" — `GspStatus` type is `"idle" | "generating" | "stopping" | "ready"`, 4 states total matching spec exactly. **flagged: human review recommended** (non-authoritative LLM judgment).
- "No auto-play/auto-download on generation completion" — joined-output `<audio>` only plays via `onTogglePlay`/user click; no `.play()` call outside `togglePlayback`/`toggleOutputPlayback`. **flagged: human review recommended** (non-authoritative LLM judgment).
- "Batch status precedence must check `isSelfRunning` BEFORE `hasOutput`" — confirmed by source order in `ConfigPanel.tsx:292-298`. **flagged: human review recommended** (non-authoritative LLM judgment).
- "The blue Download button must not be merged into/replaced by the unified button" — confirmed two distinct `<Button>`/`<GenerateStopPlayButton>` elements remain. **flagged: human review recommended** (non-authoritative LLM judgment).
- "`SegmentPreview.tsx` must not gain generate/stop/audio capability" — confirmed untouched (git log). **flagged: human review recommended** (non-authoritative LLM judgment).
- "CharacterCard's surrounding row layout must not be reshaped" — confirmed Input/Select/Textarea/Badge/Dialog present unchanged in structure. **flagged: human review recommended** (non-authoritative LLM judgment).
- "CastWizard's inner column classes must not change" — confirmed `xl:w-[420px] xl:flex-none` unchanged, only the outer container gained one class. **flagged: human review recommended** (non-authoritative LLM judgment).

None of these prohibitions show evidence of violation; all are consistent with the code as inspected. Flagged per the fail-closed disposition rule rather than silently marked pass.

## Human Verification Required

None outstanding. This phase's UAT checkpoint (07-05-PLAN.md Task 2, `checkpoint:human-verify`, blocking gate) was already completed and approved by the developer on the deploy target, covering exactly the state-transition/visual behaviors that would otherwise require a fresh human-verification round here:

- All 4 unified button sites cycling amber → red → green correctly, and playing audio (steps 1-2, 4-6)
- GEN-12 edit-reverts-to-amber on segment Text, segment Voice Instructions, and character fields (steps 3-4)
- CharacterCard's new working Stop control (step 5)
- CastWizard's layout fix — card column sizes to content (step 5)
- The mandatory Pitfall-2 regenerate-with-existing-output case — red Stop Generation during re-run, never a stale green Play (step 7)

Three real bugs were found and fixed during the first verification pass (Vite dev-proxy missing `/segments`/`/generation-status` routes, character-preview buttons never settling from red to green, batch button mislabeled) — all three fixes are present in the current working tree (commits `9e2fe56`, `09d01f7`, `e4ba4d0`, confirmed via `git log`) and were re-verified by the developer on the second pass, which was approved.

The 3 code-review Critical findings (CR-01/02/03) are new advisory items surfaced after the human UAT was signed off; they represent real quality gaps worth a fast-follow but do not fall within any must_have truth or roadmap success criterion for this phase, so they do not trigger a new human-verification requirement here.

### Gaps Summary

No gaps. All 5 roadmap success criteria and all 38 plan-level must_have truths are verified against the current codebase. All artifacts exist, are substantive, and are wired. All key links are confirmed. Requirements coverage is complete with no orphans. The completed 07-05 human-verify checkpoint (approved after 3 bug fixes) supplies the behavioral evidence for every state-transition claim that static analysis alone cannot prove. Phase goal achieved.

---

_Verified: 2026-07-15T21:47:12Z_
_Verifier: Claude (gsd-verifier)_
