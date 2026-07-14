---
phase: 04
slug: immediate-cancellation
status: draft
shadcn_initialized: true
preset: radix-nova (baseColor zinc, cssVariables true, no prefix)
created: 2026-07-14
---

# Phase 04 — UI Design Contract

> **Retroactive contract.** Phase 4's frontend (04-04-PLAN.md) is already implemented, merged, and hand-verified end-to-end against real ROCm hardware (two real bugs found and fixed during the human-verify checkpoint — see `04-04-SUMMARY.md`). This document formalizes the design decisions already locked in `04-CONTEXT.md` (D-01 through D-06) and already shipped in `SegmentTable.tsx`, `ConfigPanel.tsx`, `ProjectScreen.tsx`, and `useGenerationStream.ts`, into the standard UI-SPEC template. It is documentation of what was built, not a proposal for what to build — the `gsd-ui-checker` and any future `gsd-ui-auditor` pass should validate the shipped code against these sections as the source of truth.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | shadcn (already initialized in an earlier phase — Phase 4 reused it, did not (re)configure it) |
| Preset | `radix-nova`, baseColor `zinc`, cssVariables on, no class prefix (`frontend/components.json`) |
| Component library | Radix primitives via shadcn `ui/` (`Button`, `Progress`, plus pre-existing `Badge`/`Table`/`Select`/`Checkbox`/`Textarea` this phase reused unchanged) |
| Icon library | `lucide-react` — this phase's only new icon use is `Loader2` (already in the codebase's spinner vocabulary; no new icon added) |
| Font | Inter Variable (`--font-sans`, `frontend/src/index.css`) — unchanged by this phase |

This phase added zero new tokens, zero new shadcn components, and zero new dependencies. It composed exclusively from the `Button` component and Tailwind utility classes already present in `SegmentTable.tsx` / `ConfigPanel.tsx`.

---

## Spacing Scale

Declared values (must be multiples of 4) — inherited from the existing design system, not redefined here:

| Token | Value | Usage in this phase |
|-------|-------|-------|
| xs | 4px | `gap-1` between the segment row's Play/Stop button pair (`SegmentTable.tsx` controls cell) |
| sm | 8px | `gap-2` in `CharacterPreviewRow`'s flex layout (Play icon / name / Stop or Generate button) |
| md | 16px | unchanged — panel-level spacing this phase did not touch |
| lg | 24px | unchanged — panel-level spacing this phase did not touch |

Exceptions: none introduced by this phase. (The `py-1.5` on `CharacterPreviewRow`'s container and `gap-3`/`gap-1` elsewhere are pre-existing Phase 3 patterns this phase reused verbatim, not new exceptions.)

---

## Typography

Inherited from the existing design system — this phase introduced exactly one new text element (the batch caveat line) and one new label pattern ("Stopping…"), both using existing type roles, no new sizes/weights.

| Role | Size | Weight | Line Height | Used by this phase for |
|------|------|--------|-------------|-------------------------|
| Label (button) | 14px (`text-sm`, shadcn `Button` default) | 500 (Button default) | 1.43 | "Stop" / "Stopping…" / "Generate preview" labels |
| Caption | 12px (`text-xs`) | 400 (regular) / 600 (`font-semibold` on the "Can't create..." heading, unaffected by this phase) | 1.33 | D-06 batch caveat paragraph under the batch Stop button |

No new font sizes or weights were declared. Both roles reuse the 2-weight system already established (regular 400 / semibold 600, per the project's pre-existing type scale) plus the Button component's own default (500) — this phase did not add a third weight, it inherited the shadcn Button's built-in weight.

---

## Color

Inherited from the existing zinc/radix-nova palette (`frontend/src/index.css`) — this phase deliberately did **not** introduce new color-state semantics.

| Role | Value | Usage in this phase |
|------|-------|-------|
| Dominant (60%) | `--background` (white / `oklch(1 0 0)`) | Unchanged |
| Secondary (30%) | `--secondary` (`oklch(0.967 0.001 286.375)`) | `CharacterPreviewRow` sits on `--background` inside the `--secondary` config panel; unchanged by this phase |
| Accent (10%) | `--primary` (`oklch(51.1% 0.262 276.966)`) | Not used by any control this phase added — see below |
| Destructive | `--destructive` (`oklch(0.577 0.245 27.325)`) | Not used by any control this phase added — see below |

**D-04 is a color decision, not just a scope decision:** every Stop control this phase added or touched (segment row, character-preview row, batch) uses `variant="outline"` — neutral border, no `--primary` or `--destructive` fill. This is deliberate: D-04 explicitly reserves the yellow (idle/generate) / red (stop) / green (play) color-coded system for Phase 7's unified button. Phase 4's job was to prove the backend interrupt is real, not to claim the color contract early. The one pre-existing exception this phase did not touch: the segment row's own generate/play icon button keeps its prior `variant={isPlaying ? "default" : "outline"}` (uses `--primary` only when actively playing) — untouched Phase 3 behavior, out of this phase's diff.

Accent reserved for: nothing new in this phase. (Project-wide accent usage — primary buttons, active-play state — predates Phase 4 and is unchanged.)

Destructive reserved for: nothing in this phase. No Stop control uses `--destructive`/red — that mapping is explicitly deferred to Phase 7 (GEN-09/10/11, ROADMAP Phase 7).

---

## Component Inventory (Stop Controls)

Three call sites, three independent (not-yet-unified, per D-04) implementations, one shared idle/generating/stopping tri-state contract (D-03/D-05):

| Call site | Component | Idle | Generating | Stopping |
|-----------|-----------|------|------------|----------|
| Segment row | `GeneratePlayButton` (`SegmentTable.tsx`) | icon-only Play/Generate button, no Stop button rendered | icon button shows spinning `Loader2`; a second `size="sm" variant="outline"` "Stop" text button appears beside it | Stop button's own label swaps to "Stopping…", `disabled` | 
| Character preview | `CharacterPreviewRow` (`ConfigPanel.tsx`) | "Generate preview" ghost text button (only rendered while `!hasPreview`) | "Generate preview" button's label becomes a spinning `Loader2`; a `size="sm" variant="outline"` "Stop" button appears beside it | Stop button's label swaps to "Stopping…", `disabled` |
| Batch (Generate All) | `ConfigPanel`'s Generation section | Primary "Generate All" / "Resume Generation" button, no Stop row | Primary button becomes "Generating…" (spinner); an `outline` "Stop" button block appears below it with the D-06 caveat line | Stop button's content becomes `Loader2` spinner + "Stopping…" text, `disabled` |

All three: bare-bones/functional per D-04 — no color-state polish, no unified component. All three: the "stopping…" label is never instantaneous — it is held until the backend confirms release (an `await` on `cancelSegmentGeneration`/`cancelCharacterPreview`/`cancelBatchGeneration` that only resolves once the true-kill + lock release completes, per D-03/Pitfall 2), then cleared in a `finally` block covering both success and error paths (the second checkpoint bug fix in `04-04-SUMMARY.md`) — not just on `catch`.

Explicitly out of scope for this contract (per D-04/CONTEXT.md `deferred`): `CharacterCard.tsx`'s Cast Review wizard preview button and `SegmentPreview.tsx`'s panel have no Stop control and are not touched by this phase's diff — captured as backlog for Phase 7, not part of this UI-SPEC.

---

## Copywriting Contract

| Element | Copy | Where |
|---------|------|-------|
| Segment row Stop (idle label under generating state) | "Stop" | `SegmentTable.tsx` `GeneratePlayButton`, `aria-label="Stop generating segment {n}"` |
| Segment row Stopping | "Stopping…" | same button, while `isStopping` |
| Character-preview Stop | "Stop" | `ConfigPanel.tsx` `CharacterPreviewRow`, `aria-label="Stop generating preview for {name}"` |
| Character-preview Stopping | "Stopping…" | same button, while `isStoppingPreview` |
| Character-preview idle-trigger | "Generate preview" | shown only while `!hasPreview` |
| Batch Stop | "Stop" | `ConfigPanel.tsx` batch Generation section |
| Batch Stopping | spinner + "Stopping…" | same button, while `isCancelling` |
| Batch Stop caveat (D-06, corrected) | "Stop interrupts the segment currently generating immediately." | one line, `text-xs text-muted-foreground`, directly under the batch Stop button — replaces the now-false pre-Phase-4 copy ("Stops before the next segment — the segment currently generating may still finish.") |
| Empty state | not applicable — no new empty state introduced by this phase | — |
| Error state | not applicable — this phase did not add a new error-state UI; a stopped generation resets the row to its prior pending/complete status via `onRefresh`, it does not surface a Phase-4-specific error copy | — |
| Destructive confirmation | not applicable — Stop is not modeled as a destructive/confirm-gated action anywhere in this phase; clicking Stop fires immediately, no confirm dialog (matches the project's existing "no confirm on non-destructive edits" convention) | — |

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | `Button` (pre-existing, reused — no new install this phase) | not required |
| third-party | none | not applicable |

No new shadcn blocks/components were installed for this phase. `npx shadcn view`/vetting gate not triggered — nothing new to vet.

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending

---

*Retroactively generated 2026-07-14 — source: `04-CONTEXT.md` D-01–D-06, `04-04-PLAN.md`, `04-04-SUMMARY.md`, and the shipped code in `frontend/src/components/SegmentTable.tsx`, `ConfigPanel.tsx`, `ProjectScreen.tsx`, `frontend/src/hooks/useGenerationStream.ts`, `frontend/src/api/client.ts`.*
