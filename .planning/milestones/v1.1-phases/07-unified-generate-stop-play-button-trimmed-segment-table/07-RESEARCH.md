# Phase 7: Unified Generate/Stop/Play Button & Trimmed Segment Table - Research

**Researched:** 2026-07-15
**Domain:** React frontend component consolidation (no new external dependencies, no backend changes)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** The unified button replaces **four** existing implementations: `SegmentTable.tsx`'s `GeneratePlayButton` (segment row), `ConfigPanel.tsx`'s `CharacterPreviewRow` (character preview), `ConfigPanel.tsx`'s Generate All/Stop batch control, and `CharacterCard.tsx`'s wizard-side preview button (folded in from the pending todo).
- **D-02:** For `CharacterCard.tsx`, only the generate/stop/play control itself is replaced. Everything else (name input, preset select, voice instructions textarea, merge dialog/button) stays exactly as-is — do not reshape the surrounding row layout.
- **D-03:** `SegmentPreview.tsx` (Cast Review wizard's read-only right-panel segment table) stays exactly as it is today — no per-row controls, no aggregate Generate All/Stop, no audio, text-only preview. User's own words: "no segment generation or editing in the character generation/wizard view. serves only as a preview."
- **D-04:** The batch "Generate All" button IS the yellow/red/green control — same single button, same 3-state pattern as every other site. Once the joined output file exists, that same button becomes the green "Play" state and toggles in-browser playback of the joined file. Download stays a separate, distinct blue button, unchanged from Phase 6 (CFG-08).
- **D-05:** Fix the character-card column (left side of `CastWizard.tsx`) so it sizes to its own content instead of stretching to full window/viewport height, while `SegmentPreview` (right side) continues to render at its own natural height. Rejected alternative: independent scroll panes.
- **D-06:** All unified buttons use the exact same 3 labels everywhere: "Generate Preview" → "Stop Generation" → "Play". This replaces the batch button's current "Generate All"/"Resume Generation"/"Stop" copy, `CharacterCard`'s current "Generate", and `ConfigPanel`'s current "Generate preview"/"Stop".
- **D-07:** `SegmentTable.tsx`'s separate "Status" column (`StatusBadge`/`STATUS_BADGE` map, `status` columnHelper entry) is removed entirely. No status text or icon renders anywhere near the button beyond what the button's own color/label already conveys.
- **D-08:** Confirmed via code read: both segment edits (`generation_status` reverts to "pending" server-side) and character edits (`preview_audio_path` cleared server-side on PATCH, bumping `voice_version`) already invalidate correctly today. The unified button only needs to keep reading `hasAudio`/`generation_status`/`preview_audio_path` reactively off props — no new invalidation logic expected.

### Claude's Discretion
- Exact shared-component/hook shape for the unified button — a single `<GenerateStopPlayButton>` component parametrized by label-set/status/handlers, reused across all 4 sites, is the natural fit. Researcher/planner should confirm the cleanest extraction point given the 4 sites' differing data shapes (segment vs. character vs. project-level batch).
- Exact colors/icons for yellow/red/green — resolved by the approved UI-SPEC.md (see below), not re-litigated here.
- Whether "Stop Generation" needs its own transient "Stopping…" sub-state visually distinct from "Stop Generation" — resolved by UI-SPEC (same red background + `disabled`, no second color).

### Deferred Ideas (OUT OF SCOPE)
- `SegmentPreview.tsx` generate-all/stop capability — explicitly rejected for this phase per D-03. Candidate for a dedicated future phase if ever wanted.
- `CharacterCard.tsx` row-layout reshaping to match `ConfigPanel`'s more compact styling — rejected per D-02.
- Independent scroll panes for `CastWizard.tsx`'s two columns — rejected per D-05 in favor of the simpler shrink-to-content fix.
- Process-level force-kill beyond Phase 4's `StoppingCriteria` mechanism — out of scope per REQUIREMENTS.md.
- A 4th "queued" button state — milestone explicitly scopes to 3 states; queued folds into yellow.
- A configurable output-format fallback strategy — out of scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GEN-09 | Per-row segment audio control is a single yellow/red/green generate/stop/play button | Confirmed existing `GeneratePlayButton` (`SegmentTable.tsx`) is the most complete of the 4 implementations and the template for the shared component's internal state machine — see Architecture Patterns |
| GEN-10 | Character preview control follows the same pattern | `CharacterPreviewRow` (`ConfigPanel.tsx`) and `CharacterCard.tsx`'s button both collapse into the shared component; `CharacterCard` gains a real Stop control for the first time (currently has none — verified by code read) |
| GEN-11 | Generate All control follows the same pattern; shows green Play once joined output exists | Verified backend serves `audio/flac`, `audio/mpeg`, `audio/ogg` (opus) via `FileResponse` at the existing `/projects/{id}/download` route — same route works for both the `<a download>` (Phase 6) and a new hidden `<audio>` element (this phase), no new backend route needed. All 3 formats have broad native `<audio>` element support (see Sources). Also verified `project.output_path` persists unchanged across an entire re-run (only overwritten on join success, `generation_worker.py:219-243`) — the client-side status precedence order (Pitfall 2) is load-bearing, not decorative. |
| GEN-12 | Any edit reverts control to yellow, single visual source of truth | Verified server-side invalidation already correct for both segments (`backend/app/main.py:454`) and characters (`:471`, `:695`) — no backend work needed, confirmed D-08 |
| TBL-05 | Segment table shows exactly 3 editable columns, Status column removed | Verified exact `columns` array location and the `StatusBadge`/`STATUS_BADGE` code to delete (`SegmentTable.tsx:60-86`, `:498-502`) |
</phase_requirements>

## Summary

This phase is a pure frontend consolidation refactor — no new npm packages, no new backend endpoints, no new database fields. All four existing "generate/stop/play" implementations (`SegmentTable.tsx`'s `GeneratePlayButton`, `ConfigPanel.tsx`'s `CharacterPreviewRow`, `ConfigPanel.tsx`'s batch Generate All/Stop block, `CharacterCard.tsx`'s wizard preview button) were read in full and confirmed to share the *exact same shape* of local state machine: `isGenerating`/`isTriggeringPreview`, `isStopping`/`isStoppingPreview`, an `error` string, a `hasObservedGeneratingRef`-style guard against stale-read false settles, and a `setInterval(onRefresh, 1500)` poll bounded by `GENERATION_POLL_CEILING_MS` (330s, already exported from `api/client.ts`). Only `CharacterCard.tsx` deviates — it has no Stop button at all and hardcodes its own 60s poll ceiling instead of the shared constant.

The 07-UI-SPEC.md (already approved) fully specifies the presentational contract: a new `<GenerateStopPlayButton>` component with a `GspStatus = "idle" | "generating" | "stopping" | "ready"` prop, fixed Tailwind classes per state (`bg-amber-400`/`bg-red-600`/`bg-green-600`), and the exact label set. What UI-SPEC does **not** specify — and what CONTEXT.md explicitly defers to research/planning — is the *stateful* extraction point: the poll/settle/error logic duplicated across all 4 sites. This research recommends extracting that into one shared hook (`useGenerateStopPlay`, see Architecture Patterns) consumed by all 4 call sites, so the shared `<GenerateStopPlayButton>` stays a pure presentational component (matching UI-SPEC's `status`/`onGenerate`/`onStop`/`onTogglePlay` prop contract) while the duplicated polling/race-guard logic collapses into one place instead of four.

**Primary recommendation:** Extract a `useGenerateStopPlay` hook (new file, e.g. `frontend/src/hooks/useGenerateStopPlay.ts`) that owns the `isGenerating`/`isStopping`/`error`/poll-and-settle state machine common to all 4 sites, parametrized by `hasAudio`, `isExternallyGenerating`, `onGenerate`/`onStop` async callbacks, and an optional poll toggle (the batch site doesn't need interval polling — it already has SSE via `useGenerationStream` — so the hook's poll behavior must be an opt-in, not baked in). Pair it with UI-SPEC's presentational `<GenerateStopPlayButton>`. This turns 4 near-duplicate ~150-line blocks into 1 hook + 1 component + 4 thin call sites.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Generate/Stop/Play button visual state (color/label/icon) | Browser / Client | — | Pure presentational — the 3-color state machine is entirely a client-side rendering concern (`<GenerateStopPlayButton>`), already fully specified in UI-SPEC.md |
| Generation trigger/poll/settle state machine | Browser / Client | API / Backend | Client owns the local `isGenerating`/`isStopping`/poll-until-settled loop; backend owns the actual async job (already built in Phase 4) and the authoritative `generation_status`/`preview_audio_path` fields the poll reads back |
| Segment/character edit → cache invalidation (GEN-12) | API / Backend | — | Already implemented server-side (`generation_status = "pending"` on segment PATCH, `preview_audio_path = None` + `voice_version` bump on character PATCH) — client only needs to render off these fields reactively, no new invalidation logic |
| Joined-output playback (GEN-11) | Browser / Client | API / Backend | Client adds a hidden `<audio>` element pointed at the existing `/projects/{id}/download` route; backend needs zero changes — the route already serves the correct `content_type` per format and (via Starlette's `FileResponse`) supports HTTP Range for seeking |
| Segment table column removal (TBL-05) | Browser / Client | — | Pure client-side `columns` array edit in `SegmentTable.tsx`, no data-shape change |
| CastWizard column-stretch layout fix (D-05) | Browser / Client | — | One Tailwind class (`xl:items-start`) on a flex container — no component logic change |

## Standard Stack

### Core

No new packages. This phase's entire dependency surface is already installed and in use at the 4 sites it touches.

| Library | Version (verified installed) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| react / react-dom | ^19.2.6 | Component/hook model | Already the project's framework |
| lucide-react | ^1.24.0 | `Play`, `Pause`, `Loader2` icons | Already imported at every one of the 4 existing sites — no new icons needed per UI-SPEC |
| class-variance-authority | ^0.7.1 | `Button`'s `buttonVariants` cva | Already backs `frontend/src/components/ui/button.tsx` — no new variant added, per UI-SPEC's decision to use `className` overrides instead |
| tailwind-merge | ^3.6.0 | Resolves conflicting `bg-*`/`text-*` utility classes when `<GenerateStopPlayButton>` passes state classes through `Button`'s `className` prop | Already wired into `cn()` (`frontend/src/lib/utils.ts`) — `Button`'s own `cn(buttonVariants({...className}))` puts the caller's `className` last, so `tailwind-merge` correctly lets state-color classes win over the `default` variant's `bg-primary` |
| @tanstack/react-table | ^8.21.3 | `SegmentTable.tsx`'s `columns` array | Already in use — TBL-05's column removal is a one-entry edit, no API change |

### Supporting

None — no additional libraries needed for this phase.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| A new local `useGenerateStopPlay` hook | A generic state-machine library (XState, Zustand slice) | Rejected: the state machine has exactly 4 states with no branching complexity beyond what's already hand-rolled 4x in the codebase today; a library adds a new dependency and a new mental model for a problem this codebase already solves inline. Follows the project's existing style (no state-management library anywhere in `frontend/`) |
| `<GenerateStopPlayButton>` reading server state directly via a data-fetching hook | Caller computes `status` and passes it down as a prop (per UI-SPEC's contract) | UI-SPEC already locks this in — the component takes `status: GspStatus` as a prop, not raw segment/character/project objects, keeping it a pure presentational unit reusable across 3 very different data shapes |

**Installation:** None required — zero new packages for this phase.

**Version verification:** All 5 packages above were confirmed installed via `frontend/package.json` (grep) — no registry lookup needed since nothing new is being added. [VERIFIED: package.json]

## Package Legitimacy Audit

**Not applicable.** This phase adds zero new npm/pip/cargo packages — it is a pure refactor consolidating 4 existing, already-installed-dependency implementations into 1 shared component + hook. No `npm install` step exists in this phase's plan. Skip the Package Legitimacy Gate entirely; if a future phase revisits this decision and a library is proposed, run the gate then.

## Architecture Patterns

### System Architecture Diagram

```
                    ┌─────────────────────────────────────────┐
                    │         useGenerateStopPlay (hook)        │
                    │  owns: isGenerating, isStopping, error,   │
                    │  hasObservedGeneratingRef, poll interval  │
                    └───────────────┬───────────────────────────┘
                                    │ returns { status, error, handleGenerate, handleStop }
                                    ▼
   ┌───────────────┐   status ┌──────────────────────────┐  onClick   ┌──────────────────┐
   │ 4 call sites   │─────────▶│ <GenerateStopPlayButton> │───────────▶│ dispatches to     │
   │ (below)        │  props   │ (presentational, UI-SPEC) │            │ onGenerate/onStop/│
   └───────┬───────┘          └──────────────────────────┘            │ onTogglePlay      │
           │                                                           └────────┬──────────┘
           │ each site's own onGenerate/onStop callback wraps:                  │
           ▼                                                                    ▼
  ┌────────────────────┐  ┌───────────────────────┐  ┌─────────────────┐  ┌──────────────┐
  │ generateSegment()   │  │ triggerCharacterPreview│  │ runBatchGeneration│ │ cancel*()     │
  │ cancelSegmentGen()  │  │ cancelCharacterPreview │  │ cancelBatchGen    │ │ (all 4 sites) │
  └──────────┬──────────┘  └──────────┬─────────────┘  └────────┬─────────┘  └──────┬───────┘
             │                        │                          │                    │
             ▼                        ▼                          ▼                    ▼
        POST /segments/{id}/generate[/cancel]        POST /projects/{id}/generate[/cancel]
        POST /characters/{id}/preview[/cancel]                    │
             │                        │                          │ SSE: /projects/{id}/generation-stream
             ▼                        ▼                          ▼ (already wired via useGenerationStream)
        segment.generation_status / character.preview_audio_path / project.output_path
        (server-authoritative; read back via onRefresh poll OR SSE, whichever the site already uses)
```

### Recommended Project Structure

```
frontend/src/
├── components/
│   ├── GenerateStopPlayButton.tsx   # NEW — presentational, per UI-SPEC contract
│   ├── SegmentTable.tsx             # MODIFIED — GeneratePlayButton deleted, StatusBadge/STATUS_BADGE deleted, status column removed
│   ├── ConfigPanel.tsx              # MODIFIED — CharacterPreviewRow's two-button JSX + batch block both swap in shared component
│   ├── CharacterCard.tsx            # MODIFIED — button block swaps in shared component, gains real Stop for the first time
│   └── CastWizard.tsx               # MODIFIED — one class added (xl:items-start)
├── hooks/
│   ├── useGenerateStopPlay.ts       # NEW — shared state-machine hook (poll/settle/error), planner's call whether to split segment/character vs batch variants
│   ├── useGenerationLock.ts         # UNCHANGED — already consumed as a prop by all 4 sites
│   └── useGenerationStream.ts       # UNCHANGED — batch site's SSE source, feeds isExternallyGenerating into the hook/status derivation
└── api/
    └── client.ts                   # MODIFIED — add outputUrl(projectId) helper (mirrors downloadUrl), no other changes
```

### Pattern 1: Presentational button + stateful hook split

**What:** `<GenerateStopPlayButton>` (per UI-SPEC) takes `status: GspStatus` and callback props only — it never fetches, polls, or owns generation-in-flight state itself. A separate `useGenerateStopPlay` hook owns that state and is called once per site, producing the `status` value passed down.

**When to use:** All 4 consumer sites (segment row, `ConfigPanel` character row, `CharacterCard` wizard row, batch/Generate All).

**Example (hook shape, derived from the 3 existing near-identical implementations read in full):**
```typescript
// Source: extracted from SegmentTable.tsx's GeneratePlayButton (lines 99-269),
// ConfigPanel.tsx's CharacterPreviewRow (lines 55-204), and CharacterCard.tsx's
// generate toggle (lines 46-140) — all three duplicate this shape today.
import { useEffect, useRef, useState } from "react"
import { GENERATION_POLL_CEILING_MS, errorMessage } from "@/api/client"

type GspStatus = "idle" | "generating" | "stopping" | "ready"

interface UseGenerateStopPlayOptions {
  hasAudio: boolean
  /** True while a batch run or another trigger already has this row/preview
   * generating — e.g. segment.generation_status === "generating". */
  isExternallyGenerating: boolean
  /** Set false for the batch site, which already has SSE (useGenerationStream)
   * driving isExternallyGenerating — no interval poll needed there. */
  poll?: boolean
  onGenerate: () => Promise<unknown>
  onStop: () => Promise<unknown>
  onRefresh: () => void
}

export function useGenerateStopPlay({
  hasAudio,
  isExternallyGenerating,
  poll = true,
  onGenerate,
  onStop,
  onRefresh,
}: UseGenerateStopPlayOptions) {
  const [isGenerating, setIsGenerating] = useState(false)
  const [isStopping, setIsStopping] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const hasObservedGeneratingRef = useRef(false)
  const isRowGenerating = isGenerating || isExternallyGenerating

  useEffect(() => {
    if (!poll || !isGenerating) return undefined
    const interval = setInterval(onRefresh, 1500)
    const timeout = setTimeout(() => clearInterval(interval), GENERATION_POLL_CEILING_MS)
    return () => {
      clearInterval(interval)
      clearTimeout(timeout)
    }
  }, [poll, isGenerating, onRefresh])

  useEffect(() => {
    if (isExternallyGenerating) {
      hasObservedGeneratingRef.current = true
      return
    }
    if (hasObservedGeneratingRef.current) {
      hasObservedGeneratingRef.current = false
      setIsGenerating(false)
      setIsStopping(false)
    }
  }, [isExternallyGenerating])

  async function handleGenerate() {
    setIsGenerating(true)
    setError(null)
    try {
      await onGenerate()
      onRefresh()
    } catch (err) {
      setIsGenerating(false)
      setError(errorMessage(err, "Couldn't start generation."))
    }
  }

  async function handleStop() {
    setIsStopping(true)
    setError(null)
    try {
      await onStop()
    } catch (err) {
      setError(errorMessage(err, "Couldn't stop generation."))
    } finally {
      setIsGenerating(false)
      setIsStopping(false)
      onRefresh()
    }
  }

  const status: GspStatus = isStopping
    ? "stopping"
    : isRowGenerating
      ? "generating"
      : hasAudio
        ? "ready"
        : "idle"

  return { status, error, handleGenerate, handleStop }
}
```

**Planner's call:** whether the batch site (which has `hasOutput`/`isCancelling`/SSE-driven `isSelfRunning` rather than a poll-and-settle loop) reuses this same hook with `poll: false`, or gets its own thin inline derivation (its status logic is already only ~4 lines: `isCancelling ? "stopping" : isSelfRunning ? "generating" : hasOutput ? "ready" : "idle"`, per UI-SPEC's Component Contracts §3 precedence order). Either is reasonable; the hook exists primarily to de-duplicate the segment/character-preview polling logic, which is the actual repeated code (3 of the 4 sites, not 4 of 4).

### Pattern 2: `outputUrl` helper for the batch Play state (GEN-11)

**What:** A thin URL-builder function mirroring the existing `downloadUrl`/`previewUrl`/`segmentAudioUrl` pattern, pointed at the *same* `/projects/{id}/download` route Phase 6 already built.

**When to use:** `ConfigPanel.tsx`'s batch site, for the hidden `<audio>` element that backs the green "Play" state once `hasOutput` is true.

**Example:**
```typescript
// Source: mirrors downloadUrl (api/client.ts:320-322) verbatim — same route,
// same backend endpoint, no new server code. FileResponse (Starlette) already
// sets the correct media_type per CODEC_TABLE (audio/flac, audio/mpeg,
// audio/ogg) and supports HTTP Range requests for seeking, so a plain
// <audio src={outputUrl(id)}> works exactly like the existing segment/
// character preview <audio> elements.
export function outputUrl(projectId: string): string {
  return `/projects/${projectId}/download`
}
```

```tsx
// ConfigPanel.tsx batch site — mirrors the existing hidden-<audio> pattern
// already used 3x in this codebase (SegmentTable, CharacterPreviewRow,
// CharacterCard).
{hasOutput && (
  <audio
    ref={outputAudioRef}
    src={outputUrl(project.id)}
    onPlay={() => setIsOutputPlaying(true)}
    onPause={() => setIsOutputPlaying(false)}
    onEnded={() => setIsOutputPlaying(false)}
  />
)}
```

### Pattern 3: CastWizard layout fix (D-05)

**What:** Add `xl:items-start` to the two-column flex container so the character-card column sizes to its own content instead of the default `items-stretch` behavior.

**Example:**
```tsx
// Source: CastWizard.tsx:108 — verified current markup via direct read.
// before:
<div className="flex flex-col gap-8 xl:flex-row xl:gap-8">
// after:
<div className="flex flex-col gap-8 xl:flex-row xl:items-start xl:gap-8">
```

### Anti-Patterns to Avoid

- **Re-deriving `generationLocked` inside `<GenerateStopPlayButton>`:** The app already has one `useGenerationLock()` poll (`ProjectScreen.tsx`) whose result is threaded down as a `generationLocked` prop through `SegmentTable`/`ConfigPanel`/`CharacterCard`/`CastWizard`. The shared button must keep taking this as a prop (per CONTEXT.md's Established Patterns note), not call the hook itself — calling it again per-button would spawn N redundant 1.5s polls.
- **Baking the interval-poll into `<GenerateStopPlayButton>` itself:** The batch site doesn't need interval polling — it has SSE (`useGenerationStream`) already pushing status. If the poll logic lives inside the presentational button component, the batch site would need to fight it off (e.g. passing a no-op `onRefresh`), rather than simply not opting in. Keep polling in the stateful hook, used only where SSE isn't already available.
- **Adding a new `--warning`/`--success` CSS custom property:** UI-SPEC is explicit that the amber/red/green classes are scoped to this one component's Tailwind utility classes only, not promoted to app-wide design tokens. Don't "clean this up" into `index.css` during implementation — that's an explicitly rejected scope expansion.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Poll-until-settled after a fire-and-forget 202 | A new bespoke poll loop per site (the current anti-pattern, done 3x already) | The shared `useGenerateStopPlay` hook (Pattern 1) | Same 1500ms-interval / `GENERATION_POLL_CEILING_MS`-bounded / `hasObservedGeneratingRef`-guarded shape already proven correct at 3 sites — consolidating removes ~300 duplicated lines without changing behavior |
| Audio format compatibility check for the joined-output Play button | A codec-sniffing/`canPlayType()` guard before rendering the audio element | Nothing — just render `<audio src={outputUrl(id)}>` unconditionally once `hasOutput` | All 3 possible output formats (FLAC, MP3, Opus-in-Ogg) already have broad native `<audio>` element support in evergreen browsers (Chrome 56+/33+, Firefox 51+/15+, Safari 11+/18.4+) — no fallback/transcode logic needed for a Tailscale-only, single-user, presumably-modern-browser deployment |
| Range-request/seek support for a potentially long joined audio file | Custom streaming/chunking logic in the download endpoint | Nothing — Starlette's `FileResponse` (already used by `/projects/{id}/download`) sets `Accept-Ranges`/handles `Range` headers automatically | This route already exists for Phase 6's Download button; reusing it for a hidden `<audio>` element gets seeking for free |

**Key insight:** every piece of "new" behavior this phase needs (poll-until-settled, hidden-`<audio>` playback, disabled-state gating on the app-wide lock) is a direct copy of a pattern already proven correct at 1-3 other sites in this exact codebase. The only genuinely new code is the presentational button (fully specified by UI-SPEC) and the extraction of the shared hook — there is no green-field logic to invent here.

## Common Pitfalls

### Pitfall 1: Widening the segment table's `controls` column breaks existing layout
**What goes wrong:** Today's `GeneratePlayButton` renders an `icon-sm` (28px square) button for idle/ready states, only widening to accommodate a separate "Stop" text button while generating. The unified button always shows a text label ("Generate Preview" / "Stop Generation" / "Play") even at rest, so the `controls` column becomes permanently wider than today across all rows, not just generating ones.
**Why it happens:** `SegmentTable.tsx`'s `columns` array has no explicit width constraints — TanStack Table lets each column size to its content, and the table's other 3 columns (`select`, `narrator`, `text`) already compete for horizontal space in what's roughly a ~70%-width panel (`ConfigPanel` takes the other ~30%, per its own doc comment).
**How to avoid:** Use `size="sm"` (per UI-SPEC's Component Contracts §2) consistently, and manually check the table's rendered width at a typical viewport (this app is a single-user Tailscale service, so a fixed dev-machine viewport check is sufficient — no responsive breakpoint matrix needed). "Stop Generation" (14 characters) is the longest label and the one to check specifically doesn't force `text`/`narrator` columns to wrap awkwardly.
**Warning signs:** The `text` column's `Textarea` visually shrinking below a usable width, or the table developing a horizontal scrollbar it didn't have before.

### Pitfall 2: Status precedence order must match UI-SPEC's Component Contracts §3 exactly for the batch button
**What goes wrong:** The batch site's `status` derivation has 4 inputs (`isCancelling`, `isSelfRunning`, `hasOutput`, default idle) that must be checked in the exact order UI-SPEC specifies (`stopping` → `generating` → `ready` → `idle`), because `hasOutput` is `true` for the *entire duration* of a re-run — not just before it starts. Checking `hasOutput` before `isSelfRunning` would incorrectly show green "Play" (and let the user start scrubbing the *stale* previous joined file) while a regeneration is actively running.
**Why it happens:** [VERIFIED: codebase read, `backend/app/generation_worker.py:219-243`] `project.output_path` is a durable DB field that is **only ever overwritten at the join step's success** — it is never cleared to `null` at batch-start. A re-run of "Generate All" on a project that already has a completed output leaves `output_path` pointing at the *old* file for the run's entire duration (the old file itself isn't even deleted from disk until the *new* join commits, per the `old_output_path`/WR-02 comment at line 232-236). This means `hasOutput` is `true` before, during, and after a re-run — the client-side status precedence order is the **only** thing preventing the button from showing green "Play" (backed by a now-stale `<audio src>`) while a regeneration is actively in flight.
**How to avoid:** Implement the derivation as an explicit if/else chain in the exact order UI-SPEC's Component Contracts §3 lists (`isCancelling` → `isSelfRunning` → `hasOutput` → default idle), and confirm via a real click-through (regenerate a project that already has `output_path` set) that the button correctly shows red "Stop Generation", not green "Play", while the second run is active. Since the old file physically still exists on disk until the new join commits, a stray green-then-audio-play during this window would actually play back the *previous* run's audio, not a broken link — making this a silent correctness bug (wrong file plays), not an obvious loud one.
**Warning signs:** Clicking "Generate Preview" on a project that already has a joined output shows green "Play" (not red) while the batch is actively running, and clicking it plays the previous, now-outdated joined audio.

### Pitfall 3: `CharacterCard.tsx`'s new Stop control needs the same `generationLocked`-vs-`isStopping` disabled logic the other 3 sites already have, not a naive port
**What goes wrong:** `CharacterCard.tsx` currently has *no* Stop button — D-01 requires adding one for the first time. A naive "copy `ConfigPanel`'s `CharacterPreviewRow` Stop button" port can miss that `CharacterCard`'s existing `isGenerating` state doesn't yet track "we successfully started, awaiting settle" vs. "still waiting for the initial POST to resolve" the way `CharacterPreviewRow`'s `isTriggeringPreview`/`hasPreview` split does — `CharacterCard`'s `handleGenerate` sets `isGenerating` synchronously but has no equivalent of `isGeneratingPreview = isTriggeringPreview && !hasPreview` gate.
**Why it happens:** `CharacterCard.tsx` was clearly written before `ConfigPanel.tsx`'s more careful version (confirmed by its missing Stop control and its hardcoded 60s ceiling vs. the shared `GENERATION_POLL_CEILING_MS`) — it's the least mature of the 3 preview implementations, code-quality-wise.
**How to avoid:** If extracting the shared `useGenerateStopPlay` hook (Pattern 1), `CharacterCard.tsx` gets the fix for free — the hook's logic (ported from `CharacterPreviewRow`, the more correct sibling) replaces `CharacterCard`'s weaker local state entirely rather than being bolted onto it.
**Warning signs:** A double-click on `CharacterCard`'s Generate button firing two `POST /characters/{id}/preview` calls, or the button getting stuck showing "Stopping…" after a cancel that raced a settle.

### Pitfall 4: Deleting the Status column's `STATUS_BADGE`/`StatusBadge` leaves an unused `Badge` import and `AlertCircle`/`CheckCircle2`/`Clock` icon imports
**What goes wrong:** `SegmentTable.tsx` imports `Badge` (used only by `StatusBadge`) and 3 lucide icons (`AlertCircle`, `CheckCircle2`, `Clock`) used only by the `STATUS_BADGE` map being deleted per D-07/TBL-05. A partial deletion (just removing the `columns` array entry) leaves dead imports that `ruff`/eslint won't catch (frontend lint isn't mentioned as required in CLAUDE.md, but dead imports are still a lint-check candidate if the frontend has one).
**How to avoid:** When deleting `StatusBadge`/`STATUS_BADGE` (lines 60-86) and the `status` column entry (lines 498-502), also remove the now-unused `Badge`, `AlertCircle`, `CheckCircle2`, `Clock` imports from the top of the file. `Loader2` stays (used by both the deleted badge logic and the surviving button/bulk-toolbar spinners) — verify it's still referenced elsewhere before removing.
**Warning signs:** A TypeScript build warning (`noUnusedLocals`, if enabled) or an eslint `no-unused-vars` failure on the modified `SegmentTable.tsx`.

## Code Examples

See Architecture Patterns above for the 3 concrete code examples (`useGenerateStopPlay` hook, `outputUrl` helper, CastWizard layout fix) — all derived directly from reading the existing 4 implementations in full, not invented.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| 4 independently-coded generate/stop/play implementations, each with its own local state machine and 2-button layout (icon play/generate + separate text Stop) | 1 shared `<GenerateStopPlayButton>` + 1 shared `useGenerateStopPlay` hook, 1 button per site | This phase | Removes ~300 duplicated lines, gives `CharacterCard.tsx` a working Stop control for the first time, makes color/label changes a 1-file edit going forward instead of 4 |
| Separate Status badge column conveying generation state independently from the button | Button color/label is the single visual source of truth (GEN-12) | This phase | Removes a column, removes a class of bugs where the badge and button could theoretically disagree (they can't today either, per D-08's confirmed-correct invalidation, but the redundancy itself is the thing being removed) |

**Deprecated/outdated:** `STATUS_BADGE`/`StatusBadge` (`SegmentTable.tsx:60-86`) and the batch button's "Resume Generation" context-sensitive copy — both retired by D-06/D-07 in favor of the unified label set and button-only state.

## Assumptions Log

None — the one open question this research initially flagged (whether `output_path` is cleared at batch-start) was resolved by reading `backend/app/generation_worker.py` directly (see Pitfall 2): it is confirmed **not** cleared at batch-start, only overwritten on join success. No unverified claims remain in this document.

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.

## Open Questions

None — the only open question this research surfaced (`output_path` clearing behavior during batch re-runs) was resolved via direct code read; see Pitfall 2 for the verified answer and its implications for the batch button's status-derivation order. Add a UAT check for "regenerate a project that already has a joined output" to the plan's verification steps, given this is now a confirmed silent-correctness-bug risk, not a hypothetical.

## Environment Availability

Skipped — this phase has no external tool/service/runtime dependencies beyond what's already running (existing ffmpeg-based `/download` route, existing SQLite/FastAPI backend, all already verified in Phases 4-6). No new environment probing needed.

## Security Domain

`security_enforcement` is not set to `false` in `.planning/config.json` (key absent), so this section is included per protocol — but this phase has no new attack surface. It adds zero new API endpoints, zero new input fields, and zero new auth/session logic; it only changes how already-existing, already-validated data (`generation_status`, `preview_audio_path`, `output_path`) is rendered and which already-existing endpoints (`generateSegment`, `cancelSegmentGeneration`, `triggerCharacterPreview`, `cancelCharacterPreview`, `runBatchGeneration`, `cancelBatchGeneration`, `/projects/{id}/download`) get called from a consolidated set of buttons instead of 4 separate ones.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Unchanged — Tailscale is the access boundary (per CLAUDE.md), no auth layer in this app |
| V3 Session Management | No | No session concept in this single-user app |
| V4 Access Control | No | No new authorization surface — same endpoints, same lack of per-resource ACLs as today (single-user by design) |
| V5 Input Validation | No | No new user input fields — button clicks dispatch to already-validated existing API calls; the `outputUrl`/`downloadUrl` helpers are pure string templates over a server-issued `project.id`, not user-supplied text |
| V6 Cryptography | No | Not applicable — no crypto in this phase |

### Known Threat Patterns for this stack

None applicable — this phase's entire surface is reading already-server-validated enum/boolean fields (`generation_status`, `preview_audio_path`, `output_path`) and re-dispatching to already-existing, already-reviewed API calls. No new STRIDE-relevant surface is introduced.

## Sources

### Primary (HIGH confidence)
- Direct reads of `frontend/src/components/SegmentTable.tsx`, `ConfigPanel.tsx`, `CharacterCard.tsx`, `CastWizard.tsx`, `frontend/src/api/client.ts`, `frontend/src/hooks/useGenerationLock.ts`, `useGenerationStream.ts`, `frontend/src/components/ui/button.tsx` — full-file reads this session, all code claims in this document are `[VERIFIED: codebase read]` unless otherwise marked
- `backend/app/main.py` — grepped for `generation_status =`, `preview_audio_path =`, `voice_version`, `CODEC_TABLE`, `download_project` to confirm D-08's invalidation claim and GEN-11's format/content-type behavior `[VERIFIED: codebase grep]`
- `backend/app/audio_join.py` — `CODEC_TABLE` read in full to confirm `content_type` values (`audio/flac`, `audio/mpeg`, `audio/ogg`) `[VERIFIED: codebase read]`
- `frontend/package.json` — grepped to confirm no new dependencies are needed and existing versions (`react ^19.2.6`, `lucide-react ^1.24.0`, `class-variance-authority ^0.7.1`, `tailwind-merge ^3.6.0`, `@tanstack/react-table ^8.21.3`) `[VERIFIED: package.json]`
- `fastapi==0.139.0` / `starlette==1.3.1` confirmed installed via `uv run python -c "import fastapi, starlette"` `[VERIFIED: installed environment]`

### Secondary (MEDIUM confidence)
- [FLAC Browser Support — TestMu AI](https://www.testmuai.com/learning-hub/flac-browser-support/) — FLAC plays in Chrome 56+, Edge 16+, Firefox 51+, Safari 11+ (iOS)/13+ (macOS), used to confirm GEN-11's hidden `<audio>` element works for the FLAC output format `[CITED]`
- [Opus Audio Codec Browser Support — TestMu AI](https://www.testmuai.com/learning-hub/opus-audio-codec-browser-support/) — Opus-in-Ogg plays in Chrome 33+, Edge 14+, Firefox 15+, Safari 18.4+ (macOS/iOS), used to confirm GEN-11 works for the Opus output format (the backend's ffmpeg opus encoder always muxes into Ogg, per `audio_join.py`'s own comment) `[CITED]`

### Tertiary (LOW confidence)
- None — no unverified claims beyond A1 in the Assumptions Log, which is itself flagged as an open question rather than presented as fact.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies, all versions confirmed directly from `package.json` and the installed Python environment
- Architecture: HIGH — the shared hook/component split is derived directly from reading all 4 existing implementations in full and diffing their shapes, not inferred from documentation
- Pitfalls: HIGH for all 4 (Pitfall 2's `output_path`-persists-across-reruns behavior was verified by reading `generation_worker.py` directly this session, resolving what was initially an open question)

**Research date:** 2026-07-15
**Valid until:** No expiry driver — this is an internal refactor of code already in this repository, not tied to an external library's release cadence. Re-verify only if Phase 4-6 code changes between now and Phase 7 execution.
