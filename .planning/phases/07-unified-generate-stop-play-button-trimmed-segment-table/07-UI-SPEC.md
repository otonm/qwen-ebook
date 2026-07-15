---
phase: 7
slug: unified-generate-stop-play-button-trimmed-segment-table
status: draft
shadcn_initialized: true
preset: style=radix-nova, baseColor=zinc, cssVariables=true, iconLibrary=lucide
created: 2026-07-15
---

# Phase 7 — UI Design Contract

> Visual and interaction contract for the Unified Generate/Stop/Play Button & Trimmed Segment Table (GEN-09, GEN-10, GEN-11, GEN-12, TBL-05). This phase collapses four independently-coded generate/play implementations — `SegmentTable.tsx`'s `GeneratePlayButton`, `ConfigPanel.tsx`'s `CharacterPreviewRow`, `ConfigPanel.tsx`'s batch Generate All/Stop block, and `CharacterCard.tsx`'s wizard preview button — into **one** shared `<GenerateStopPlayButton>` component with exactly 3 color states. It also removes `SegmentTable.tsx`'s separate Status column (TBL-05) and fixes `CastWizard.tsx`'s stretched character-card column (D-05).

**Focal point:** color is the single source of truth for generation state (GEN-12) — no badge, no separate status text survives anywhere near the button. Today's four implementations each render **two** controls side-by-side while generating (an icon play/generate button *plus* a separate text "Stop" button). This phase consolidates every site to **one** button whose background color, icon, and label all change together as state changes: yellow idle → red generating/stopping → green ready. This is a genuinely new visual (yellow and green do not exist anywhere in the current palette — only zinc neutrals, one indigo accent, and one red destructive tone), so the three state colors below are new, but they are scoped entirely to this one shared component, not proposed as new app-wide design tokens.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | shadcn (already initialized — `frontend/components.json`, unchanged from Phase 5/6) |
| Preset | `style: radix-nova`, `baseColor: zinc`, `cssVariables: true`, `prefix: ""` |
| Component library | radix-ui primitives via shadcn — only `Button` (`frontend/src/components/ui/button.tsx`) is used; no new shadcn component needs adding |
| Icon library | lucide-react (already installed) — `Play`, `Pause`, `Loader2` (already imported at every site); no new icons needed |
| Font | `'Inter Variable', sans-serif` (`--font-sans` in `frontend/src/index.css`), unchanged |

**No new shadcn components required.** The unified control is a **new local component** (`frontend/src/components/GenerateStopPlayButton.tsx`, or co-located — planner's call) built on the existing `Button` primitive with state-driven `className` overrides — not a new cva `variant` added to the shared `button.tsx` (these 3 colors are single-consumer, not a general-purpose Button variant every other call site should be tempted to reach for).

---

## Spacing Scale

Identical to Phase 5/6 — this phase introduces no new spacing values, only removes a column and consolidates two buttons into one within existing spaced containers.

| Token | Value | Usage (existing precedent) |
|-------|-------|------|
| xs | 4px | `gap-1` — button-internal icon/label gap (Button's own `gap-1`/`gap-1.5` per size), error-text stacks |
| sm | 8px | `gap-2` — `CharacterPreviewRow`'s row `flex items-center gap-2`, `CastWizard`'s inline undo-toast buttons |
| md | 12px | `gap-3` — `ConfigPanel`'s `Generation` section stack (unified batch button slots here, unchanged) |
| md+ | 16px | `p-4` — `ConfigPanel`/`CharacterCard` container padding, unchanged |
| lg | 24px | `gap-6` — `CastWizard`'s `gap-6` character-card grid, `ConfigPanel` section gaps |
| xl | 32px | `gap-8` — `CastWizard`'s two-column `xl:flex-row xl:gap-8` split |

Exceptions for this phase: none. Removing the Status column and collapsing two buttons into one both *reduce* the elements in already-spaced containers — no new gap values are introduced.

---

## Typography

Identical to Phase 5/6 — no new sizes or weights needed.

| Role | Size | Weight | Line Height | Existing precedent |
|------|------|--------|-------------|------|
| Section heading | 18px (`text-lg`) | 600 (`font-semibold`) | 1.2 | `<h2 className="text-lg font-semibold">Segments</h2>` / `Characters` / `Generation` — unchanged |
| Button label | 14px (`text-sm`, `default`/`sm` size) or 12.8px (`text-[0.8rem]`, `sm` size per Button's cva table) | 500 (`font-medium`, Button's base) | 1 (single-line button text) | Reused verbatim from `Button`'s existing cva `text-sm font-medium` base — no override |
| Micro / helper text | 12px (`text-xs`) | 400 | 1.4 | Error paragraphs (`text-xs text-destructive`), disabled-state `title` tooltips — unchanged pattern |

---

## Color

Inherited base palette from `frontend/src/index.css` (zinc neutrals + one indigo `--primary` accent + one red `--destructive`) — **unchanged**. This phase adds exactly 3 new state colors, scoped only to `<GenerateStopPlayButton>`.

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `--background` / `--card` (unchanged) | Page and panel background |
| Secondary (30%) | `--secondary` (unchanged) | `ConfigPanel`/`CharacterCard` container backgrounds, `SegmentTable`'s alternating row |
| Accent (10%) | `--primary` (indigo, unchanged) | **Reserved for** (unchanged from prior phases): focus rings, `Select`/`Input` focus states, the Download button (Phase 6, untouched by this phase) |
| Destructive | `--destructive` (red, unchanged) | **Reserved for**: inline error text only (`text-xs text-destructive`) — unchanged. **Not** reused for the new "Stop Generation" button color below; that is a distinct, brighter solid red chosen for button-background legibility, not the existing soft `--destructive` token which is tuned for text/soft-fill use, not a solid CTA background. |

### New: `<GenerateStopPlayButton>` state colors (scoped to this one component only)

| State | Tailwind classes | Usage |
|-------|-------------------|-------|
| Idle / stale (yellow) — GEN-09/10/11 "Generate Preview" | `bg-amber-400 text-amber-950 hover:bg-amber-500` | Default state: no audio exists yet, or the segment/character was edited since its last audio was generated (GEN-12 — both cases render identically, no visual distinction between "never generated" and "stale") |
| Generating / stopping (red) — "Stop Generation" / "Stopping…" | `bg-red-600 text-white hover:bg-red-700` | While a GPU call for this row/preview/batch is in flight. The transient "Stopping…" sub-state (Phase 4's D-03/D-05 requirement, carried forward per CONTEXT.md) reuses the **same** red background + `disabled` (Button's own `disabled:opacity-50` supplies the visual dimming — no second color needed) |
| Ready (green) — "Play" / "Pause" | `bg-green-600 text-white hover:bg-green-700` | Audio exists for this row/preview, or (batch site only) the joined output file exists — clicking toggles playback of the associated `<audio>` element |

**Reserved-for list (exhaustive):** these 3 colors are used **only** inside `<GenerateStopPlayButton>`, at its 4 consumer sites (segment row, `ConfigPanel` character row, `CharacterCard` wizard row, batch/Generate All). They are not introduced as `--warning`/`--success` CSS custom properties in `index.css` and must not be reused elsewhere in the app without a new design decision — this keeps the addition scoped to exactly what GEN-09/10/11 asked for.

No warning/amber usage exists elsewhere in the app today (Phase 5's `TriangleAlert` model-steering note uses `text-muted-foreground`, not a color token) — this phase's amber is the first, and stays confined to this one component.

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Idle state label (all 4 sites) | `"Generate Preview"` — D-06: replaces `CharacterCard`'s current `"Generate"`, `ConfigPanel`'s current `"Generate preview"`, and the batch button's current `"Generate All"` **and** `"Resume Generation"` (D-06 mandates one literal label set everywhere — the batch button's context-sensitive resume wording is dropped in favor of full consistency, per CONTEXT.md's explicit statement that the "keep 'Generate All' for the batch button" alternative was presented and rejected) |
| Generating state label | `"Stop Generation"` — D-06: replaces every site's current `"Stop"` |
| Stopping (transient) sub-state label | `"Stopping…"` — same red background, `disabled`, `Loader2` spin icon; carried forward from Phase 4's `GeneratePlayButton`/`CharacterPreviewRow` precedent (`isStopping ? "Stopping…" : "Stop"` pattern), now applied uniformly to all 4 sites including `CharacterCard` (which has no Stop control today at all — D-01) |
| Ready state label (not playing) | `"Play"` |
| Ready state label (playing) | `"Pause"` — mirrors existing `isPlaying` toggle copy at every current site, unchanged |
| `aria-label` template | `"{Generate/Stop generating/Play/Pause} {subject}"` where `{subject}` is `"audio for segment {N}"` / `"preview for {character.name}"` / `"the joined output"` — reuses each site's existing aria-label wording verbatim (e.g. `Generate audio for segment ${segment.order + 1}`, `Stop generating preview for ${character.name}`), just routed through the one shared component instead of four hand-written strings |
| Disabled + `generationLocked` tooltip (new, all 4 sites) | `"Another generation is already running."` — new `title` attribute shown only when the idle button is disabled specifically because the app-wide lock is held by something else (not because this row/preview itself lacks a prerequisite); reuses the exact visible-but-disabled + `title` pattern already established by Phase 6's Download button and `CharacterPreviewRow`'s Play button (`"No preview generated yet"`) |
| Per-site error copy (unchanged) | `"Couldn't start generation."` / `"Couldn't stop generation."` / `"Couldn't start the preview."` / `"Couldn't stop the preview."` — existing strings, reused verbatim; rendered `<p className="text-xs text-destructive" role="alert">` below the button exactly as today |
| Status column removal (TBL-05) | No replacement copy anywhere — GEN-12 mandates the button's own color/label is the single visual source of truth; no icon, no badge, no text renders near the button beyond what today's error paragraph already does |
| CastWizard layout fix (D-05) | No copy change — purely a class change on the outer flex container (see Component Contracts) |
| Destructive confirmation | Not applicable — Stop is not a destructive/irreversible action (already-established no-dialog precedent, confirmed again in Phase 5's UI-SPEC) |
| Empty state | Not applicable — the button always renders (idle is itself the "nothing generated yet" state, not a separate empty-state message) |

---

## UI Considerations

Applicable state considerations resolved: 3 covered, 0 backstop, 0 unresolved.

| Category | Element(s) | Status | Resolution / Reason |
|----------|------------|--------|---------------------|
| long-text | `<GenerateStopPlayButton>` labels (segment row, `ConfigPanel` character row, `CharacterCard` row, batch/Generate All — `interactive-control`) | ✅ covered | Copy is a fixed, short, hardcoded set (`"Generate Preview"` / `"Stop Generation"` / `"Stopping…"` / `"Play"` / `"Pause"`) — never user-generated or dynamic in length, so no truncation/wrap/ellipsis handling is needed; the button auto-sizes to its label via `Button`'s existing intrinsic width (no fixed-width constraint is imposed by this spec) |
| overflow | `CastWizard.tsx`'s character-card column (`static-content`, D-05 layout fix) | ✅ covered | Adding `items-start` to the outer `flex flex-col gap-8 xl:flex-row xl:gap-8` container (see Component Contracts §4) stops the column stretching to the segment-preview column's height at zero, one, or many characters — each column now sizes to its own content independently, confirmed by inspection of the flex model (default `items-stretch` is what causes today's bug) |
| error | Joined-output `<audio>` playback (batch site's Ready/Play sub-state, GEN-11 — `media`) | ✅ covered | Reuses the exact hidden-`<audio>` + `isPlaying` toggle + `onPlay`/`onPause`/`onEnded` pattern already proven at the segment and character-preview sites (`GeneratePlayButton`, `CharacterPreviewRow`) — no new playback-failure handling is introduced, same zero-JS-error-path native `<audio>` behavior |

`SegmentTable.tsx`'s list-collection state coverage (empty/loading/error/populated/partial/zero-one-many) is unchanged by this phase — TBL-05 only removes the Status column; no new list-collection state is introduced, so it is not re-probed here (already resolved in Phase 3's UI-SPEC).

---

## Component Contracts (phase-specific)

### 1. Shared `<GenerateStopPlayButton>` component (new file)

```tsx
type GspStatus = "idle" | "generating" | "stopping" | "ready"

interface GenerateStopPlayButtonProps {
  status: GspStatus
  isPlaying?: boolean        // only meaningful when status === "ready"
  disabled?: boolean         // e.g. generationLocked while status === "idle"
  disabledReason?: string    // → title attribute, e.g. "Another generation is already running."
  size?: "sm" | "default"
  className?: string         // e.g. "w-full" for the batch site
  subjectLabel: string       // e.g. "audio for segment 3", "preview for Elena", "the joined output"
  onGenerate: () => void
  onStop: () => void
  onTogglePlay: () => void
}

const STATE_CLASSES: Record<GspStatus, string> = {
  idle: "bg-amber-400 text-amber-950 hover:bg-amber-500",
  generating: "bg-red-600 text-white hover:bg-red-700",
  stopping: "bg-red-600 text-white hover:bg-red-700", // disabled prop supplies the dimming
  ready: "bg-green-600 text-white hover:bg-green-700",
}

const STATE_LABEL: Record<GspStatus, string> = {
  idle: "Generate Preview",
  generating: "Stop Generation",
  stopping: "Stopping…",
  ready: "Play", // caller flips to "Pause" via isPlaying when status === "ready"
}
```

- One `<Button>` per site, ever — no adjacent second button. `onClick` dispatches to `onGenerate`/`onStop`/`onTogglePlay` based on `status`.
- Icon: `idle` → none (plain text, matches `ConfigPanel`'s existing plain-text `"Generate preview"` precedent); `generating`/`stopping` → `<Loader2 className="animate-spin" />`; `ready` → `<Play />` (not playing) / `<Pause />` (playing).
- `disabled` is `true` while `status === "stopping"` always (no double-cancel), plus the caller's own `disabled` prop (e.g. `generationLocked` gating `idle`, or `!hasAudio` — though `ready` never renders without audio by construction).
- `className` merges via the existing `cn()`/`twMerge` utility (`frontend/src/lib/utils.ts`) — passing a `bg-*`/`text-*` override on top of `Button`'s `variant="default"` base correctly wins because `twMerge` resolves the conflicting utility, not string concatenation. No new `Button` variant is added to `button.tsx`.

### 2. `SegmentTable.tsx` integration (segment row, GEN-09)

- The `controls` column's cell renders one `<GenerateStopPlayButton size="sm" status={...} ... />` computed from `segment.generation_status`/`segment.audio_path`, replacing the current `GeneratePlayButton` function's two-button JSX (lines ~217-261) with the shared component.
- The `status` display column (`columnHelper.display({ id: "status", ... })`, line ~498-502) is **deleted entirely**, along with the now-unused `STATUS_BADGE` map and `StatusBadge` function (lines ~60-86) — TBL-05/D-07.
- `columns` array shrinks from 5 entries to 4: `select`, `narrator`, `text`, `controls` — matching the requirement's "exactly 3 editable columns" (Narrator, Voice Instructions/Text — note: this table currently has no separate "Voice Instructions" column; only `narrator`/`text` are editable columns today, `controls` is the 4th non-editable column carrying the button. TBL-05's "3 editable columns" language refers to Narrator/Voice Instructions/Text as the *content* columns once Status is gone — the button's own `controls` column is not counted as "editable" since it triggers generation, not data edits.)

### 3. `ConfigPanel.tsx` integration (character rows + batch, GEN-10/GEN-11)

- `CharacterPreviewRow`'s two-button JSX (lines ~146-186: icon Play/Pause button + conditional `"Generate preview"`/`"Stop"` buttons) collapses to one `<GenerateStopPlayButton size="sm" ... />` per character.
- The batch block (lines ~458-497) collapses `Generate All`/`Stop` into one `<GenerateStopPlayButton size="default" className="w-full" ... />`. Status derivation order: `stopping` (cancel in flight) → `generating` (`isSelfRunning`) → `ready` (`hasOutput`, GEN-11 — the same `hasOutput` boolean already computed at line 266) → `idle` (default). The `Progress`/`joinBlocked`/`batchError` blocks below stay exactly as-is — this phase changes only the button itself, not the progress/error surfaces around it.
- When `status === "ready"`, `onTogglePlay` toggles a new hidden `<audio src={outputUrl(project.id)} .../>` for the joined file (mirrors the existing `previewUrl`/`segmentAudioUrl` hidden-`<audio>` pattern — an `outputUrl` helper following the same shape as `downloadUrl` in `api/client.ts` is the natural addition, planner's call).
- The separate blue **Download** button (lines ~520-535) is **unchanged** — stays a distinct `<Button variant="default">`, per D-04. It sits below the unified button in the same `gap-3` `Generation` section, exactly as today.

### 4. `CharacterCard.tsx` integration (wizard row, D-01/D-02)

- The current `hasPreview ? <icon button> : <text "Generate" button>` branch (lines ~209-239) is replaced by **one** `<GenerateStopPlayButton size="sm" ... />` that now also gets a working Stop control for the first time (this component currently has none — D-01's core fix).
- Everything else in the component — the name `Input`, the Preset `Select`, the Voice Instructions `Textarea`, the "Voice assigned" `Badge`, the merge `Dialog`/button — is untouched, per D-02. Do not reshape the surrounding row layout.
- `isWaitingForPreview`'s local 60s poll ceiling (`window.setTimeout(() => setIsGenerating(false), 60000)`, line ~83) should converge on the shared `GENERATION_POLL_CEILING_MS` constant (`frontend/src/api/client.ts`, already `330_000`ms) instead of its own hardcoded value — same ceiling every other site already uses, per CONTEXT.md's Reusable Assets note.

### 5. `CastWizard.tsx` layout fix (D-05)

```tsx
// before:
<div className="flex flex-col gap-8 xl:flex-row xl:gap-8">
// after:
<div className="flex flex-col gap-8 xl:flex-row xl:items-start xl:gap-8">
```

- Adding `xl:items-start` overrides the flex row's default `items-stretch`, so the `xl:w-[420px] xl:flex-none` character-card column (line 109) sizes to its own content height instead of stretching to match `SegmentPreview`'s (line 124, `flex-1`) height. No changes to either column's own classes — `SegmentPreview` continues to render at its own natural height, per D-05 ("continues to render at its own natural height alongside it").
- No independent scroll panes are added (rejected alternative, D-05) — this one-class change is the entire fix.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|--------------|
| shadcn official | none new — `Button` (`frontend/src/components/ui/button.tsx`) already installed and in use at every one of the 4 sites this phase touches | not required (already vetted, already in use elsewhere in the app) |
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
