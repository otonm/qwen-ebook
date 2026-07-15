---
phase: 6
slug: config-panel-output-format-filename-download
status: draft
shadcn_initialized: true
preset: style=radix-nova, baseColor=zinc, cssVariables=true, iconLibrary=lucide
created: 2026-07-15
---

# Phase 6 — UI Design Contract

> Visual and interaction contract for Config Panel — Output Format, Filename & Download (CFG-06, CFG-07, CFG-08). This phase turns two existing **read-only** `ConfigField` rows in `ConfigPanel.tsx` (`Output Format`, `Output File`) into **editable** controls (a `Select` and an `Input`), and adds one new blue `Download` action next to `Generate All`. Every token, component, and copy convention below is inherited from the existing codebase and from Phase 5's precedent — no new colors, spacing values, or component primitives are introduced.

**Focal point:** none of this phase's controls compete with the Generate All CTA for attention. The Format `Select` and Filename `Input` are inert configuration (no swap/lock semantics like Phase 5's Model dropdown — RESEARCH.md Pattern 4 confirms no generation lock is needed here), so they read as quiet, low-ceremony form fields. The one new state that *does* need visual weight is the Download button appearing once output exists — it uses the same primary/blue `Button` variant as Generate All so the user's eye finds it immediately after a batch finishes, without introducing a second competing color.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | shadcn (already initialized — `frontend/components.json`) |
| Preset | `style: radix-nova`, `baseColor: zinc`, `cssVariables: true`, `prefix: ""` |
| Component library | radix-ui primitives via shadcn (`Select`, `Input`, `Button` — all already present in `frontend/src/components/ui/`, none need adding) |
| Icon library | lucide-react `^1.24.0` |
| Font | `'Inter Variable', sans-serif` (`--font-sans` / `--font-heading` in `frontend/src/index.css`) |

**No new shadcn components required.** `Select`/`SelectTrigger`/`SelectContent`/`SelectItem`/`SelectValue` (used today for the Model dropdown and `NarratorCell`) and `Input` (already shipped in `frontend/src/components/ui/input.tsx`, currently unused elsewhere in `ConfigPanel.tsx` but already used in the app) cover everything this phase needs. `Button`'s existing `asChild` support (`radix-ui`'s `Slot`) lets the Download control render as a native `<a href=... download>` styled as a `Button` — no JS blob-fetch/`window.location` hack, the browser's own download mechanism does the work.

---

## Spacing Scale

Identical to Phase 5's contract — this phase introduces no new spacing values, only new controls slotted into the existing `gap-6`-spaced Config/Generation sections.

| Token | Value | Usage (existing precedent) |
|-------|-------|------|
| xs | 4px | `gap-1` — label/control stacks (Format field, Filename field, extension-suffix row) |
| sm | 8px | `gap-2` — row/section internal gaps |
| md | 12px | `gap-3` — `Generation` section stack (Download button slots here) |
| md+ | 16px | `p-4` — `ConfigPanel` outer container padding |
| lg | 24px | `gap-6` — spacing between `ConfigPanel` sections |

Exceptions for this phase: none. The Filename field's inline extension suffix (`.mp3` etc.) sits in a `flex items-center gap-1` row (4px) next to the `Input` — same token, no new value.

---

## Typography

Identical to Phase 5's contract — no new sizes or weights needed.

| Role | Size | Weight | Line Height | Existing precedent |
|------|------|--------|-------------|------|
| Section heading | 18px (`text-lg`) | 600 (`font-semibold`) | 1.2 | `<h2 className="text-lg font-semibold">Config</h2>` / `Generation` |
| Field label | 12px (`text-xs`) | 600 (`font-semibold`) | 1.4, `text-muted-foreground` | `ConfigField`'s label span; Format/Filename field labels reuse this exactly |
| Body / control text | 14px (`text-sm`) | 400 | 1.5 | Select trigger text, Input text |
| Micro / helper text | 12px (`text-xs`) | 400 | 1.4 | Extension suffix (`.mp3`), error paragraphs |

---

## Color

Inherited from `frontend/src/index.css` (zinc base, oklch tokens, light+dark via `.dark` class) — do not add new colors for this phase.

| Role | Token | Usage |
|------|-------|-------|
| Dominant (60%) | `--background` / `--card` | Page and panel background |
| Secondary (30%) | `--secondary` (`bg-secondary`) | `ConfigPanel` container |
| Accent (10%) | `--primary` (blue, `oklch(51.1% 0.262 276.966)`) | **Reserved for**: the Generate All button (existing), focus rings on Format `Select`/Filename `Input` (existing component defaults), and — new this phase — the **Download** button (`Button` `default` variant, D-06's "blue Download button" requirement satisfied by the existing `bg-primary` variant, no new color). |
| Destructive | `--destructive` (red) | **Reserved for**: PATCH-failure inline error (format/filename save) and download-failure inline error only — same `text-xs text-destructive` pattern as every other inline error in this file. Not used for anything else in this phase. |

No warning/amber color is introduced — this phase has no persistent-caveat state analogous to Phase 5's D-03 note (format and filename are freely reversible, inert config).

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Format field label | `"Output Format"` |
| Format dropdown options | `"FLAC"`, `"MP3"`, `"Opus"` (values `flac`/`mp3`/`opus`) — plain codec names, no parenthetical qualifier needed (unlike the Model dropdown, these three are peers with no quality/speed trade-off framing required by CONTEXT.md) |
| Filename field label | `"Output Filename"` |
| Filename input placeholder | The D-05 derived default (`Path(project.filename).stem`, e.g. `"book"`) — shown as placeholder text only when `project.output_filename` is empty/unset, matching native input placeholder semantics |
| Filename extension suffix | `.{project.output_format}` rendered as static muted text immediately after the `Input` (e.g. `.mp3`) — makes the D-04/Pitfall-8 "extension always matches format, never trust what the user typed" rule visible at a glance, no hidden surprise at download time |
| Primary CTA (new this phase) | `"Download"` — the blue button that appears once `project.output_path` exists; label is a single verb+noun, no ambiguity with `"Generate All"` |
| Primary CTA (unchanged) | `"Generate All"` / `"Resume Generation"` — already shipped, not modified by this phase |
| Download button disabled state (no output yet) | Visible but `disabled`, `title="Generate All first — nothing to download yet."` — same visible-but-disabled + `title` tooltip pattern as `CharacterPreviewRow`'s Play button (`hasPreview` gate), not a hidden/unmounted control |
| Format/filename save error | `"Couldn't save output settings."` — rendered `<p className="text-xs text-destructive" role="alert">`, same pattern as `swapError`/`batchError` |
| Download failure | `"Couldn't download the file — try again."` — same inline error pattern, shown only if the download `<a>` click somehow needs a JS-level guard (e.g. output_path went stale between render and click); native `<a download>` otherwise needs no JS error path |
| Empty state | Not applicable — Format always has exactly 3 fixed options (no arbitrary list); Filename always has a derived placeholder (D-05), never truly empty from the user's point of view |
| Destructive confirmation | Not applicable — no destructive action is user-facing in this phase. D-07's delete-old-file-on-regenerate is silent/automatic (same "no dialog" precedent as GEN-03's segment invalidation, confirmed in `05-UI-SPEC.md`'s "Segment invalidation on swap" section) |

---

## Component Contracts (phase-specific)

### 1. Output Format field (`ConfigPanel.tsx`, replaces the read-only `ConfigField label="Output Format"` row)

```tsx
<div className="flex flex-col gap-1">
  <span className="text-xs font-semibold text-muted-foreground">Output Format</span>
  <Select
    value={project.output_format}
    onValueChange={(value) => void handleConfigChange({ output_format: value })}
  >
    <SelectTrigger size="sm" aria-label="Output format" className="w-full">
      <SelectValue />
    </SelectTrigger>
    <SelectContent>
      <SelectItem value="flac">FLAC</SelectItem>
      <SelectItem value="mp3">MP3</SelectItem>
      <SelectItem value="opus">Opus</SelectItem>
    </SelectContent>
  </Select>
</div>
```

- No `disabled`/loading state — per RESEARCH.md Pattern 4, this PATCH doesn't touch the GPU/generation lock, so there's nothing to wait on. The Select commits `onValueChange` immediately (same interaction shape as the Model dropdown, minus the swap-spinner state).
- No warning note beneath it (contrast with the Model dropdown's D-03 note) — changing format has no functional caveat to surface.

### 2. Output Filename field (`ConfigPanel.tsx`, replaces the read-only `ConfigField label="Output File"` row)

```tsx
<div className="flex flex-col gap-1">
  <span className="text-xs font-semibold text-muted-foreground">Output Filename</span>
  <div className="flex items-center gap-1">
    <Input
      aria-label="Output filename"
      value={filenameDraft}
      onChange={(e) => setFilenameDraft(e.target.value)}
      onBlur={() => void handleFilenameBlur()}
      placeholder={defaultFilenameStem}
      className="flex-1"
    />
    <span className="text-sm text-muted-foreground">.{project.output_format}</span>
  </div>
  {configError && (
    <p className="text-xs text-destructive" role="alert">{configError}</p>
  )}
</div>
```

- **Commit timing:** `onBlur`, not per-keystroke — avoids a PATCH request per character, matches native text-field UX expectations. `filenameDraft` is local state seeded from `project.output_filename ?? ""`; `handleFilenameBlur` PATCHes only if the trimmed value differs from the last-saved one.
- **D-04 sanitization echo:** the PATCH response returns the server-sanitized filename (RESEARCH.md Pattern 4's `sanitize_filename`); on success, re-seed `filenameDraft` from the response so any stripped character is visible immediately — same "server state wins" discipline as the Model Select reverting on `project.tts_model`.
- **Extension suffix is always derived from `project.output_format`, never from what the user types** — if the user types `"my-book.mp3"` while Opus is selected, the input still shows exactly what they typed (no client-side stripping-as-you-type, that would fight the user's cursor); the suffix badge `.opus` next to it makes clear which extension actually lands on disk, and the backend strips/re-appends per Open Question 2's resolution regardless of what's echoed in the input.

### 3. Download button (`ConfigPanel.tsx`, Generation section, alongside Generate All / Stop)

```tsx
<Button
  asChild={hasOutput}
  type="button"
  variant="default"
  className="w-full"
  disabled={!hasOutput}
  title={hasOutput ? undefined : "Generate All first — nothing to download yet."}
>
  {hasOutput ? (
    <a href={downloadUrl(project.id)} download={`${project.output_filename}.${project.output_format}`}>
      Download
    </a>
  ) : (
    "Download"
  )}
</Button>
```

- `hasOutput = Boolean(project.output_path)` — same truthiness check the existing `ConfigField label="Output File"` display already uses (`project.output_path ? ... : "Not generated yet"`).
- Renders as a real `<a download>` anchor (via `asChild`) when enabled — the browser's native download flow, no `fetch`+blob JS needed; `GET /projects/{id}/download` (RESEARCH.md's new route) already sets the correct `Content-Disposition`/`Content-Type`, so the anchor's `download` attribute is just a UX hint, not load-bearing.
- Placement: directly below the `Generate All`/`Stop`/progress stack in the existing `gap-3` Generation section — not a new section, keeps the button visually attached to "the thing that produced this file."
- Uses `variant="default"` (the same `bg-primary` blue as Generate All) — satisfies D-06's "blue Download button" with zero new variant.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|--------------|
| shadcn official | none new — `Select`, `SelectTrigger`, `SelectContent`, `SelectItem`, `SelectValue`, `Input`, `Button` already installed in `frontend/src/components/ui/` | not required (already vetted, already in use elsewhere in the app) |
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
