# Phase 7: Unified Generate/Stop/Play Button & Trimmed Segment Table - Context

**Gathered:** 2026-07-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Every place audio is generated today (segment row, character voice preview, batch "Generate All") converges on one consistent yellow "Generate Preview" → red "Stop Generation" → green "Play" button pattern, replacing four independently-coded implementations. The segment table drops its separate Status badge column — state is conveyed by the button alone. Once the joined output file exists, the batch control itself additionally becomes the green "Play" state for in-browser preview of the joined file (Download stays a separate, unchanged blue button from Phase 6).

This phase also folds in a related pending todo surfaced during Phase 4 testing (`.planning/todos/pending/2026-07-14-cast-review-wizard-stop-control-and-layout.md`): the Cast Review wizard's `CharacterCard.tsx` preview button — a 4th, previously out-of-scope implementation of the same character-preview capability `ConfigPanel.tsx`'s `CharacterPreviewRow` already has — gets the same unified button and a real Stop control (it currently has none, which required a backend restart to unblock during Phase 4 testing). `CastWizard.tsx`'s layout bug (character-card column stretching to full window height instead of sizing to content) is fixed alongside it.

Out of scope (per REQUIREMENTS.md v1.1 / user decision during this discussion): adding any segment-audio generation capability to the wizard's `SegmentPreview.tsx` — it stays a pure read-only text preview, no controls, no audio, exactly as today. Also out of scope: process-level force-kill beyond Phase 4's `StoppingCriteria` mechanism; a 4th "queued" button state; a configurable output-format fallback strategy.

</domain>

<decisions>
## Implementation Decisions

### Component consolidation scope
- **D-01:** The unified button replaces **four** existing implementations, not three: `SegmentTable.tsx`'s `GeneratePlayButton` (segment row), `ConfigPanel.tsx`'s `CharacterPreviewRow` (character preview), `ConfigPanel.tsx`'s Generate All/Stop batch control, **and** `CharacterCard.tsx`'s wizard-side preview button (folded in from the pending todo — same underlying capability as `CharacterPreviewRow`, just a second independently-coded UI for it).
- **D-02:** For `CharacterCard.tsx`, only the **generate/stop/play control itself** is replaced with the shared/unified piece. Everything else in that component — name input, voice preset select, voice instructions textarea, merge dialog/button — stays exactly as-is. Do not reshape the surrounding row layout to match `ConfigPanel`'s more compact styling; that's a separate concern not raised as in-scope here.

### Wizard segment-generation capability — explicitly deferred
- **D-03:** `SegmentPreview.tsx` (the Cast Review wizard's read-only right-panel segment table) stays **exactly as it is today**: no per-row controls, no aggregate Generate All/Stop, no audio, text-only preview. The user was explicit: "no segment generation or editing in the character generation/wizard view — serves only as a preview." This reverses the "fold all 3" initial framing down to folding only the CharacterCard Stop control (D-01) and the CastWizard layout fix (D-05) from the pending todo — the SegmentPreview generate-all idea from that todo is not built in this phase.

### Joined-output Play button (GEN-11)
- **D-04:** The batch **"Generate All" button IS the yellow/red/green control** — same single button, same 3-state pattern as every other site. Once the joined output file exists, that same button (which said "Generate All" while idle, "Stop Generation" while running) becomes the green "Play" state and toggles in-browser playback of the joined file. **Download stays a separate, distinct blue button**, unchanged from Phase 6 (CFG-08) — Play and Download are two different buttons once output exists, but Play is not a 3rd new button, it's what "Generate All" turns into.

### CastWizard layout fix
- **D-05:** Folded from the pending todo. Fix the character-card column (left side of `CastWizard.tsx`) so it **sizes to its own content** instead of stretching to full window/viewport height, while the segment preview column (right side) continues to render at its own natural height alongside it. (Rejected alternative: independent scroll panes for each column — user chose the simpler shrink-to-content fix.)

### Label consistency across all sites
- **D-06:** All unified buttons use the **exact same 3 labels everywhere**, including the batch control: **"Generate Preview" → "Stop Generation" → "Play"**. This literally replaces the batch button's current "Generate All"/"Stop" copy with "Generate Preview"/"Stop Generation" while idle/running — the user explicitly chose full label consistency over site-appropriate wording (the alternative that kept "Generate All" for the batch button specifically was presented and rejected). Apply this same 3-label set to the character-preview sites too (replacing `CharacterCard`'s current "Generate" and `ConfigPanel`'s current "Generate preview").

### Status column removal (TBL-05)
- **D-07:** `SegmentTable.tsx`'s separate "Status" column (the `StatusBadge`/`STATUS_BADGE` map, `status` columnHelper entry) is removed entirely. No status text or icon renders anywhere near the button beyond what the button's own yellow/red/green state already conveys — this is the single visual source of truth per GEN-12, not merely "de-emphasized."

### Edit invalidation (GEN-12) — already correct, no new backend work expected
- **D-08:** Confirmed via code read: both segment edits (`generation_status` reverts to "pending" server-side, per Phase 3's GEN-03 mechanism) and character edits (`preview_audio_path` is already cleared server-side on `PATCH /characters/{id}`, bumping `voice_version`) already invalidate correctly today. The unified button only needs to keep reading `hasAudio`/`generation_status`/`preview_audio_path` reactively off props, the way `GeneratePlayButton` and `CharacterPreviewRow` already do — no new invalidation logic is expected, just consistent rendering off state that already exists.

### Folded Todos
- **`.planning/todos/pending/2026-07-14-cast-review-wizard-stop-control-and-layout.md`** — "Cast Review wizard stop control and layout." Partially folded:
  - Sub-issue (1), `CharacterCard.tsx`'s missing Stop control → **folded**, see D-01/D-02.
  - Sub-issue (2), `CastWizard.tsx`'s layout stretch bug → **folded**, see D-05.
  - Sub-issue (3), `SegmentPreview.tsx`'s missing generate-all/stop → **not folded**, explicitly deferred, see D-03.
  - Delete or update this todo file after Phase 7 ships to reflect that (1) and (2) are resolved but (3) remains open (candidate for a future phase if ever needed).

### Claude's Discretion
- Exact shared-component/hook shape for the unified button (a single `<GenerateStopPlayButton>` component parametrized by label-set/status/handlers, reused across all 4 sites, is the natural fit given the codebase's existing pattern-reuse style — e.g. `GeneratePlayButton` already documents reusing "CharacterCard's play/pause + isPlaying + hidden `<audio>` pattern"). Researcher/planner should confirm the cleanest extraction point given the 4 sites' differing data shapes (segment vs. character vs. project-level batch).
- Exact colors/icons for yellow/red/green (this phase has "UI hint: yes" in ROADMAP.md — a `/gsd-ui-phase` design contract is the expected place to pin down exact Tailwind/shadcn tokens, not this discussion).
- Whether "Stop Generation" needs its own transient "Stopping…" sub-state visually distinct from "Stop Generation" (Phase 4's D-03 established this requirement for the *existing* bare-bones Stop buttons) — carrying that requirement forward into the unified component is expected but the exact visual treatment is Claude's/the UI-SPEC's call.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 7 requirements and scope
- `.planning/REQUIREMENTS.md` — GEN-09, GEN-10, GEN-11, GEN-12, TBL-05 (locked requirements for this phase); Out of Scope table (no process-level force-kill beyond Phase 4, no 4th "queued" state, no 3rd model size, no WAV)
- `.planning/ROADMAP.md` §Phase 7 — success criteria (5 numbered TRUE statements), dependency note (Phase 4's async stop contract + Phases 5-6's model/format/download controls), "UI hint: yes"

### Folded todo (this discussion's scope decision)
- `.planning/todos/pending/2026-07-14-cast-review-wizard-stop-control-and-layout.md` — source of D-01/D-02/D-05; only sub-issues (1) and (2) are folded, sub-issue (3) is explicitly deferred per D-03

### Prior phase decisions this phase builds on
- `.planning/phases/04-immediate-cancellation/04-CONTEXT.md` — D-01 (true-kill promise, already delivered), D-03/D-04/D-05 (the "stopping…" transient state requirement and the bare-bones-Stop-buttons-are-Phase-7's-job handoff), D-06 (batch caveat copy, superseded by this phase's unified copy per D-06 here)
- `.planning/phases/05-on-demand-model-swap/05-CONTEXT.md` — D-05/D-06 (model-swap invalidation reuses the exact same clear-cache/revert-to-pending mechanism GEN-03 already uses — same invariant this phase's D-08 confirms still holds)
- `.planning/phases/06-config-panel-output-format-filename-download/06-CONTEXT.md` — D-06 (existing blue Download button, unchanged per this phase's D-04), `downloadUrl`/`downloadFilename` construction in `ConfigPanel.tsx`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `frontend/src/components/SegmentTable.tsx`'s `GeneratePlayButton` (lines ~99-269) — the most complete existing 3-state implementation (idle/generating/stopping/play + poll-until-settled + error surfacing) and the closest template for the unified component's internal logic.
- `frontend/src/components/ConfigPanel.tsx`'s `CharacterPreviewRow` (lines ~55-204) — near-identical pattern to `GeneratePlayButton` but for character previews; the two should collapse into the same shared piece.
- `frontend/src/components/CharacterCard.tsx`'s generate/play toggle (lines ~122-140, ~209-251) — the 4th implementation, currently has **no Stop button at all** (D-01/D-02 target); its `isWaitingForPreview` + 60s ceiling poll pattern is the piece to replace with the shared component's own poll/cancel logic.
- `frontend/src/components/ConfigPanel.tsx`'s batch Generate All/Stop block (lines ~282-307, ~353-364, ~456-536) — has its own `isStarting`/`isCancelling`/`isBatchRunning`/`isResuming` state machine; needs a Play sub-state added for D-04 once `project.output_path` exists.
- `cancelSegmentGeneration`, `cancelCharacterPreview`, `cancelBatchGeneration`, `generateSegment`, `triggerCharacterPreview`, `runBatchGeneration` (all in `frontend/src/api/client.ts`) — the existing API surface every site already calls; the unified component wraps these per-site, doesn't change their contracts.
- `GENERATION_POLL_CEILING_MS` (`api/client.ts`) — the shared poll-ceiling constant already used by 2 of the 3 sites (`SegmentTable`, `ConfigPanel`'s `CharacterPreviewRow`); `CharacterCard.tsx` currently uses its own hardcoded 60000ms — should converge on the shared constant too.

### Established Patterns
- All three existing "generating" implementations already poll `onRefresh`/`onCastRefresh` every 1500ms while waiting, mirroring each other almost exactly — strong signal the extraction is low-risk (same shape, not a redesign).
- `useGenerationLock()` hook (`frontend/src/hooks/useGenerationLock.ts`) already provides the app-wide single-flight lock signal consumed by `CastWizard.tsx`, `ConfigPanel.tsx`, and (implicitly via `generationLocked` prop) `SegmentTable.tsx` — the unified component should take this as a prop, not re-derive it.
- Server-side invalidation (D-08) is already correct for both segments and characters — confirmed via `backend/app/main.py` grep (`preview_audio_path = None` on character PATCH; segment `generation_status` reset per Phase 3's GEN-03 path). No backend changes expected for this phase beyond whatever the batch-output Play state needs (likely none — `project.output_path` already exists from Phase 6).

### Integration Points
- `SegmentTable.tsx`'s `columns` array (line ~456) — remove the `"status"` column entry entirely (D-07); the `"controls"` column's cell swaps `GeneratePlayButton` for the new shared component.
- `ConfigPanel.tsx`'s character list section (line ~442) and Generation section (line ~456) both swap their local button logic for the shared component, with the Generation section additionally gaining the D-04 Play-on-complete behavior gated on `project.output_path`.
- `CharacterCard.tsx`'s button block (line ~209-239) swaps in the shared component while every other prop/handler (`saveField`, `handlePresetChange`, merge dialog) stays untouched (D-02).
- `CastWizard.tsx`'s outer flex container (line ~108-121) — the `xl:w-[420px] xl:flex-none` column needs its height/stretch behavior fixed per D-05; exact Tailwind classes are Claude's discretion.

</code_context>

<specifics>
## Specific Ideas

- User's own words on wizard scope: "no segment generation or editing in the character generation/wizard view. serves only as a preview" — direct quote backing D-03, use verbatim if the researcher/planner needs to justify why `SegmentPreview.tsx` isn't touched.
- No other specific visual/copy examples given beyond D-06's label decision — exact colors/icons/spinner treatment are Claude's discretion (see above), expected to land in a UI-SPEC.md per this phase's "UI hint: yes".

</specifics>

<deferred>
## Deferred Ideas

- **`SegmentPreview.tsx` generate-all/stop capability** — raised by the folded todo's sub-issue (3), explicitly rejected for this phase per D-03. If ever wanted, it's a new capability (segment audio generation surfaced a screen earlier than today), not a unification task — candidate for a dedicated future phase, not a Phase 7 add-on.
- **`CharacterCard.tsx` row-layout reshaping** to match `ConfigPanel`'s more compact preview-row styling — considered and rejected per D-02; only the button itself is swapped, not the surrounding layout.
- **Independent scroll panes** for `CastWizard.tsx`'s two columns — considered and rejected per D-05 in favor of the simpler shrink-to-content fix.

### Reviewed Todos (not folded)
- `.planning/todos/pending/2026-07-14-cast-review-wizard-stop-control-and-layout.md` sub-issue (3) only (SegmentPreview generate-all/stop) — reviewed and explicitly deferred per D-03; sub-issues (1) and (2) from the same todo file ARE folded (see Folded Todos above). The todo file itself should be updated/closed after Phase 7 ships to reflect this split resolution.

</deferred>

---

*Phase: 7-Unified Generate/Stop/Play Button & Trimmed Segment Table*
*Context gathered: 2026-07-15*
</code_context>
