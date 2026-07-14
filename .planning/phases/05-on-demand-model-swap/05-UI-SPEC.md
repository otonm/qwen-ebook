---
phase: 5
slug: on-demand-model-swap
status: draft
shadcn_initialized: true
preset: style=radix-nova, baseColor=zinc, cssVariables=true, iconLibrary=lucide
created: 2026-07-14
---

# Phase 5 — UI Design Contract

> Visual and interaction contract for On-Demand Model Swap (CFG-04, CFG-05). This phase adds exactly two new interactive surfaces to an already-built app: (1) a Model dropdown in `ConfigPanel.tsx` replacing the hardcoded `TTS_MODEL_DISPLAY_NAME` display, and (2) a disabled-cell treatment for the Voice Instructions column in `SegmentTable.tsx` while 0.6B is active. Every token, component, and copy convention below is inherited from the existing codebase — no new colors, spacing values, or component primitives are introduced.

**Focal point:** the Model `Select` trigger is the primary visual anchor of the Config Panel whenever a swap-decision is in play — it sits above and drives the state of everything else this phase touches (the D-03 warning note directly beneath it, and the disabled Voice Instructions cells in the table below). Nothing else in `ConfigPanel.tsx` competes for attention during a swap: the spinner/`"Switching model…"` state and the `swapError` message both render inline at that same anchor point, not elsewhere on the page.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | shadcn (already initialized — `frontend/components.json`) |
| Preset | `style: radix-nova`, `baseColor: zinc`, `cssVariables: true`, `prefix: ""` |
| Component library | radix-ui primitives via shadcn (`Select`, `Textarea`, `Button`, `Badge` — all already present in `frontend/src/components/ui/`, none need adding) |
| Icon library | lucide-react `^1.24.0` |
| Font | `'Inter Variable', sans-serif` (`--font-sans` / `--font-heading` in `frontend/src/index.css`) |

**No new shadcn components required.** `Select`, `SelectTrigger`, `SelectContent`, `SelectItem`, `SelectValue` (used today for `NarratorCell`'s character reassignment) and `Textarea` (used today for `EditableTextCell`, already ships a `disabled:` variant) cover everything this phase needs.

---

## Spacing Scale

This is the phase-specific spacing contract — a strict 4-point subset (all declared values are multiples of 4). Two non-4-multiple tokens exist elsewhere in the already-shipped codebase (`gap-0.5` / 2px, `gap-1.5` / 6px, e.g. `CharacterPreviewRow` row padding) but neither is used by any new markup in this phase, so they are intentionally excluded from this table rather than carried forward as an "exception" — the phase's own new elements (Model field, warning note) use `gap-1` (4px), not `gap-0.5`, precisely to stay on-scale. Do not introduce `gap-0.5`/`gap-1.5` in new code touched by this phase.

| Token | Value | Usage (existing precedent) |
|-------|-------|------|
| xs | 4px | `gap-1` — icon-to-label gaps, error message stack, Model field's label/value stack (this phase) |
| sm | 8px | `gap-2` / `p-2` — row/section internal gaps |
| md | 12px | `gap-3` — `Generation` section stack |
| md+ | 16px | `p-4` — `ConfigPanel` outer container padding |
| lg | 24px | `gap-6` — spacing between `ConfigPanel` sections (Config / Characters / Generation) |

Exceptions for this phase: none. The new Model field and its warning note slot into a `flex flex-col gap-1` wrapper (4px, on-scale) inside the existing `gap-6`-spaced Config section; the disabled-cell treatment adds zero new spacing (it reuses `Textarea`'s existing `min-h-16 bg-background text-sm` cell, only toggling the `disabled` prop).

---

## Typography

| Role | Size | Weight | Line Height | Existing precedent |
|------|------|--------|-------------|------|
| Section heading | 18px (`text-lg`) | 600 (`font-semibold`) | 1.2 | `<h2 className="text-lg font-semibold">Config</h2>` |
| Field label | 12px (`text-xs`) | 600 (`font-semibold`) | 1.4, `text-muted-foreground` | `ConfigField`'s label span |
| Body / control text | 14px (`text-sm`) | 400 | 1.5 | Select trigger text, character name |
| Micro / helper text | 12px (`text-xs`) | 400 | 1.4 | Error paragraphs, "Stop interrupts…" helper line |

No new sizes or weights needed — the Model field label uses the existing Field-label style, the dropdown options use Body style, the warning note and error message both use Micro style (matching `text-xs text-muted-foreground` / `text-xs text-destructive` already used everywhere else in `ConfigPanel.tsx`/`SegmentTable.tsx`).

---

## Color

Inherited from `frontend/src/index.css` (zinc base, oklch tokens, light+dark via `.dark` class) — do not add new colors for this phase.

| Role | Token | Usage |
|------|-------|-------|
| Dominant (60%) | `--background` / `--card` (white / near-black in dark) | Page and panel background |
| Secondary (30%) | `--secondary` (`bg-secondary` — `ConfigPanel`'s own container) | `ConfigPanel` container, table cell backgrounds |
| Accent (10%) | `--primary` (blue, `oklch(51.1% 0.262 276.966)`) | **Reserved for**: the Generate All primary button, focus rings on the Model `Select` trigger. NOT used for the warning note (see below) — the note is informational, not a call to action. |
| Destructive | `--destructive` (red) | **Reserved for**: D-02's swap-failure error message only (`text-destructive`, matches every other inline error in this codebase — `batchError`, `CharacterPreviewRow`'s error, `EditableTextCell`'s error). The D-03 steering-limitation warning is deliberately NOT destructive-red — see below. |

**D-03 warning-note color decision:** the persistent 0.6B steering note is a permanent fact about the current selection, not a failure state — using `--destructive` (red) for something that's true 100% of the time 0.6B is selected would read as a standing error and desensitize the user to actual errors elsewhere in the same panel. Render it in `text-muted-foreground` (the same tone as the existing "Stop interrupts the segment currently generating immediately." helper line in the Generation section) with a `TriangleAlert` icon (lucide, `size-3`, same tone) prepended for scannability. This reuses an existing tone rather than inventing a new "warning/amber" token — see Registry Safety / Accent note above for why no new color is introduced.

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Model dropdown options | `"Higher quality (1.7B)"` and `"Faster (0.6B)"` — verbatim from ROADMAP.md Phase 5 success criterion 1; do not paraphrase |
| Loading/swap-in-progress state | Select trigger's chevron icon is replaced by a spinning `Loader2` (`size-4 animate-spin`, matches `Generate All`'s own loading icon); trigger `disabled`; `SelectValue` text becomes `"Switching model…"` |
| D-03 persistent warning note (0.6B only) | `"Faster (0.6B) doesn't support custom voice instructions — segments use each character's base preset voice only."` — always visible directly under the dropdown whenever 0.6B is the resident model; no dismiss control |
| D-02 swap-failure error | `"Couldn't switch to {attemptedLabel}. Still using {residentLabel}."` — e.g. `"Couldn't switch to Faster (0.6B). Still using Higher quality (1.7B)."` Rendered as `<p className="text-xs text-destructive" role="alert">`, same pattern as every other inline error in this file. Clears on next swap attempt. |
| Disabled Voice Instructions cell (0.6B only) | `title` attribute (tooltip) on each disabled `Textarea`: `"Voice instructions have no effect while Faster (0.6B) is active."` |
| Primary CTA (unchanged, no new CTA this phase) | `"Generate All"` / `"Resume Generation"` — already shipped, not modified by this phase |
| Empty state | Not applicable — the Model dropdown always has exactly 2 fixed options (`MODEL_CHOICES`, no arbitrary list per Out of Scope), nothing to be empty |
| Destructive confirmation | Not applicable — D-05/D-06 segment invalidation on swap is silent and reuses GEN-03's existing confirm-free per-row-edit precedent (no dialog exists there today, so none is introduced here either) |

---

## Component Contracts (phase-specific)

### 1. Model field (`ConfigPanel.tsx`, replaces the hardcoded `ConfigField label="Model"` row)

```
<div className="flex flex-col gap-1">
  <span className="text-xs font-semibold text-muted-foreground">Model</span>
  <Select value={project.tts_model} onValueChange={handleModelChange} disabled={isSwapping}>
    <SelectTrigger size="sm" aria-label="TTS model" className="w-full">
      {isSwapping ? (
        <span className="flex items-center gap-1.5">
          <Loader2 className="size-4 animate-spin" /> Switching model…
        </span>
      ) : (
        <SelectValue />
      )}
    </SelectTrigger>
    <SelectContent>
      <SelectItem value="1.7b">Higher quality (1.7B)</SelectItem>
      <SelectItem value="0.6b">Faster (0.6B)</SelectItem>
    </SelectContent>
  </Select>
  {project.tts_model === "0.6b" && (
    <p className="flex items-center gap-1 text-xs text-muted-foreground">
      <TriangleAlert className="size-3 shrink-0" />
      Faster (0.6B) doesn't support custom voice instructions — segments use each
      character's base preset voice only.
    </p>
  )}
  {swapError && (
    <p className="text-xs text-destructive" role="alert">{swapError}</p>
  )}
</div>
```

- **D-01 trigger behavior:** `onValueChange` fires the explicit `POST /projects/{id}/model` load immediately (not deferred to next Generate). Trigger goes `disabled` and shows the spinner label for the swap's duration (tens of seconds — STACK.md's swap-latency estimate).
- **D-02 failure behavior:** on error, `project.tts_model` is refetched/re-rendered from the backend's actual resident model (never optimistically left on the failed target) — the Select naturally reverts because its `value` prop is server state, not local state. `swapError` is set and rendered until the next swap attempt clears it.
- **Config Panel scope during swap:** only this Select is disabled directly. Generate All / per-row generate / character preview controls are disabled via the **existing** `generationLocked` prop (from `useGenerationLock()`), because the model-load claims the same single-flight backend lock under its own label (`"model-load:{model_id}"`, per canonical refs) — `generationLocked` already flips `true` for the swap's duration with zero new frontend state. Do not add a second `isModelSwapping` prop thread through `ConfigPanel`/`SegmentTable` — this would duplicate state the lock already provides. The Input File / Output Format / Output File display fields stay untouched (inert, no GPU/lock dependency).

### 2. Disabled Voice Instructions cells (`SegmentTable.tsx`'s `EditableTextCell`, `field="voice_instructions"` only)

```
<Textarea
  aria-label={`${label} for segment ${segment.order + 1}`}
  value={value}
  onChange={(e) => setValue(e.target.value)}
  onBlur={handleBlur}
  disabled={field === "voice_instructions" && project.tts_model === "0.6b"}
  title={
    field === "voice_instructions" && project.tts_model === "0.6b"
      ? "Voice instructions have no effect while Faster (0.6B) is active."
      : undefined
  }
  className="min-h-16 bg-background text-sm"
/>
```

- **D-04 visual treatment:** zero new CSS. `Textarea`'s `disabled:` variant already exists in `frontend/src/components/ui/textarea.tsx` (`disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50`, dark-mode counterpart included) — passing `disabled` is the entire implementation. The Text and Narrator columns are unaffected (only `field === "voice_instructions"` is gated).
- `EditableTextCell` needs `project.tts_model` threaded down as a prop (or read from context/parent) to evaluate the condition — smallest-diff addition, no new component.

### 3. Segment invalidation on swap (D-05/D-06 — no new visual component)

A successful model swap loops over every segment in the project and calls the exact same invalidation path GEN-03 already uses for a single edited row (clear `audio_path`, revert `generation_status` to `"pending"`). This means:
- `StatusBadge` already renders `"Pending"` (outline variant, `Clock` icon) for these rows — no new status value.
- `GeneratePlayButton` already reverts to its "Generate Preview" state once `hasAudio` is false — no new button state.
- No toast, banner, or confirmation dialog is introduced for the invalidation itself — it's a silent, expected consequence of D-05, surfaced entirely through the existing per-row status/button state the user already reads today.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|--------------|
| shadcn official | none new — `Select`, `SelectTrigger`, `SelectContent`, `SelectItem`, `SelectValue`, `Textarea`, `Button`, `Badge` already installed in `frontend/src/components/ui/` | not required (already vetted, already in use elsewhere in the app) |
| Third-party | none | not applicable — no third-party registry declared for this phase |

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
