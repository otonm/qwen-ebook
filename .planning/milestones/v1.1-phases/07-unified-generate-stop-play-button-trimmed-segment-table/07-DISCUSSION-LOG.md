# Phase 7: Unified Generate/Stop/Play Button & Trimmed Segment Table - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-15
**Phase:** 7-Unified Generate/Stop/Play Button & Trimmed Segment Table
**Areas discussed:** Todo fold, Wizard segment generation, Character-preview unification scope, Joined-output Play behavior, CastWizard layout fix, Label consistency

---

## Todo fold

| Option | Description | Selected |
|--------|-------------|----------|
| Fold (1) only | CharacterCard's wizard preview button gets a real Stop control; defer layout and SegmentPreview generate-all as separate backlog items | |
| Fold all 3 | Also fix CastWizard's layout sizing and add generate-all/stop to SegmentPreview | ✓ (initial) |
| Fold none — defer entirely | Leave the whole todo untouched for a dedicated follow-up phase | |

**User's choice:** "Fold all 3" initially — later refined down to effectively "Fold (1) only" once the Wizard segment generation question (below) was answered, since the user explicitly rejected building any SegmentPreview generation capability.
**Notes:** Net result across both questions: sub-issues (1) CharacterCard Stop control and (2) CastWizard layout are folded into Phase 7; sub-issue (3) SegmentPreview generate-all/stop is not.

---

## Wizard segment generation

| Option | Description | Selected |
|--------|-------------|----------|
| Full per-row controls (mirrors main table) | SegmentPreview gets the same per-row button as SegmentTable, duplicating that capability a screen earlier | |
| Aggregate Generate-All + Stop only | One button triggers batch generation from the wizard screen; progress shown via character cards | |
| Don't build this now — defer | Leave SegmentPreview read-only; add Stop to CharacterCard only | (effectively selected via free text) |

**User's choice:** Free text: "no segment generation or editing in the character generation/wizard view. serves only as a preview"
**Notes:** This resolves the "Fold all 3" answer above down to folding only sub-issues (1) and (2) of the pending todo. SegmentPreview.tsx is untouched by this phase.

---

## Character-preview unification scope

| Option | Description | Selected |
|--------|-------------|----------|
| Button only (recommended) | Extract just the generate/stop/play control into a shared component; everything else in CharacterCard stays as-is | ✓ |
| Button + surrounding preview row layout | Also reshape CharacterCard's row layout to match ConfigPanel's compact styling | |

**User's choice:** Button only (recommended)
**Notes:** None.

---

## Joined-output Play behavior (GEN-11)

| Option | Description | Selected |
|--------|-------------|----------|
| Generate All button becomes Play when done (recommended) | Same button flips through Generate All → Stop → Play once output exists; Download stays separate | ✓ |
| Separate dedicated Play button | Add a distinct Play button; Generate All stays clickable to force regeneration | |

**User's choice:** Generate All button becomes Play when done (recommended)
**Notes:** None.

---

## CastWizard layout fix

| Option | Description | Selected |
|--------|-------------|----------|
| Shrink-to-content (recommended) | Character card column sizes to its own content height, drops the stretch behavior | ✓ |
| Independent scroll panes | Both columns get independent max-height + scroll | |

**User's choice:** Shrink-to-content (recommended)
**Notes:** None.

---

## Label consistency

| Option | Description | Selected |
|--------|-------------|----------|
| Same 3 labels everywhere | Every control, including batch, reads "Generate Preview"/"Stop Generation"/"Play" | ✓ |
| Site-appropriate wording, same pattern (recommended) | Batch keeps "Generate All"/"Stop Generation"/"Play"; others use "Generate Preview" | |

**User's choice:** Same 3 labels everywhere
**Notes:** User picked full consistency over the site-appropriate recommendation — the batch button's idle/running labels change from "Generate All"/"Stop" to "Generate Preview"/"Stop Generation".

---

## Claude's Discretion

- Exact shared-component/hook shape for the unified button across the 4 sites.
- Exact colors/icons/spinner treatment for yellow/red/green states (expected to land in a UI-SPEC.md, per this phase's "UI hint: yes").
- Whether "Stop Generation" needs its own transient "Stopping…" sub-state (carried forward from Phase 4's D-03 requirement) — visual treatment only.
- Exact Tailwind classes for the CastWizard layout fix.

## Deferred Ideas

- `SegmentPreview.tsx` generate-all/stop capability — explicitly rejected for this phase; candidate for a dedicated future phase if ever needed.
- `CharacterCard.tsx` row-layout reshaping to match ConfigPanel's compact styling — considered and rejected, button-only swap instead.
- Independent scroll panes for CastWizard's two columns — considered and rejected in favor of shrink-to-content.
