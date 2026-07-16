# Phase 7: Unified Generate/Stop/Play Button & Trimmed Segment Table - Pattern Map

**Mapped:** 2026-07-15
**Files analyzed:** 7 (2 new, 5 modified)
**Analogs found:** 7 / 7

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `frontend/src/components/GenerateStopPlayButton.tsx` (new) | component | request-response | `SegmentTable.tsx`'s `GeneratePlayButton` (lines 99-269) | exact (this IS the extraction target) |
| `frontend/src/hooks/useGenerateStopPlay.ts` (new) | hook | request-response + poll | `ConfigPanel.tsx`'s `CharacterPreviewRow` poll/settle effects (lines 84-141) | exact |
| `frontend/src/components/SegmentTable.tsx` (modified) | component/table | CRUD + request-response | itself (in-place refactor) | exact |
| `frontend/src/components/ConfigPanel.tsx` (modified) | component | CRUD + request-response + SSE | itself (in-place refactor) | exact |
| `frontend/src/components/CharacterCard.tsx` (modified) | component | CRUD + request-response | `ConfigPanel.tsx`'s `CharacterPreviewRow` (the more mature sibling implementation) | role-match, upgrade source |
| `frontend/src/components/CastWizard.tsx` (modified) | component | static layout | itself (one-class edit) | exact |
| `frontend/src/api/client.ts` (modified: add `outputUrl`) | utility | request-response (URL builder) | `downloadUrl` (line ~320) | exact |

## Pattern Assignments

### `frontend/src/components/GenerateStopPlayButton.tsx` (new component)

**Analog:** `frontend/src/components/SegmentTable.tsx`'s `GeneratePlayButton` (lines 99-269), cross-checked against `ConfigPanel.tsx`'s `CharacterPreviewRow` (lines 55-204) for the icon/label mapping.

**Exact prop contract — copy verbatim from 07-UI-SPEC.md Component Contracts §1** (`.planning/phases/07-unified-generate-stop-play-button-trimmed-segment-table/07-UI-SPEC.md:134-170`):
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

**Existing `Button` usage pattern to build on** (`SegmentTable.tsx:220-239`):
```tsx
<Button
  type="button"
  size="icon-sm"
  variant={isPlaying ? "default" : "outline"}
  disabled={isDisabled}
  onClick={() => void handleClick()}
  aria-label={label}
>
  {isRowGenerating ? (
    <Loader2 className="animate-spin" />
  ) : hasAudio ? (
    isPlaying ? <Pause /> : <Play />
  ) : (
    <Play />
  )}
</Button>
```
Replace `variant="outline"`/`variant="default"` toggling with `className={STATE_CLASSES[status]}` passed through `Button`'s existing `className` prop (already `cn()`/`twMerge`-backed per `frontend/src/lib/utils.ts` — no new `Button` variant needed, per UI-SPEC).

**Icon/label dispatch rule (from UI-SPEC §1, line 168):** `idle` → no icon, plain text; `generating`/`stopping` → `<Loader2 className="animate-spin" />`; `ready` → `<Play />`/`<Pause />` via `isPlaying`. `disabled` is forced `true` whenever `status === "stopping"` (no double-cancel) OR the caller's own `disabled` prop.

**Error display pattern** (identical at all 3 existing sites, e.g. `SegmentTable.tsx:262-266`):
```tsx
{error && (
  <p className="text-xs text-destructive" role="alert">
    {error}
  </p>
)}
```
Keep this at each *call site* (not inside the shared button) since `error` state lives in the hook, one per call site.

---

### `frontend/src/hooks/useGenerateStopPlay.ts` (new hook)

**Analog:** `ConfigPanel.tsx`'s `CharacterPreviewRow` (lines 55-204) — the most mature of the 3 poll/settle implementations (has the WR-02 ceiling-timeout error recovery `SegmentTable.tsx`'s version lacks explicit copy for). Also draws from `SegmentTable.tsx:99-269`'s `hasObservedGeneratingRef` guard.

**Poll-until-settled pattern to extract** (`ConfigPanel.tsx:84-101`):
```tsx
useEffect(() => {
  if (!isGeneratingPreview) return undefined
  const interval = setInterval(onRefresh, 1500)
  const timeout = setTimeout(() => {
    clearInterval(interval)
    setIsTriggeringPreview(false)
    setError("Preview generation is taking too long — try again.")
  }, GENERATION_POLL_CEILING_MS)
  return () => {
    clearInterval(interval)
    clearTimeout(timeout)
  }
}, [isGeneratingPreview, onRefresh])
```

**Stale-settle guard pattern to extract** (`SegmentTable.tsx:154-167`):
```tsx
useEffect(() => {
  if (segment.generation_status === "generating") {
    hasObservedGeneratingRef.current = true
    return
  }
  if (hasObservedGeneratingRef.current) {
    hasObservedGeneratingRef.current = false
    setIsGenerating(false)
    setIsStopping(false)
  }
}, [segment.generation_status])
```

**Generate/Stop handler pattern to extract** (`SegmentTable.tsx:169-209`, near-identical to `ConfigPanel.tsx:113-141`):
```tsx
async function handleClick() { /* ...generate branch only, play is caller's onTogglePlay... */
  setIsGenerating(true)
  setError(null)
  try {
    await generateSegment(segment.id)
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
    await cancelSegmentGeneration(segment.id)
  } catch (err) {
    setError(errorMessage(err, "Couldn't stop generation."))
  } finally {
    setIsGenerating(false)
    setIsStopping(false)
    onRefresh()
  }
}
```

**Imports to reuse** (`SegmentTable.tsx:1-29`, `ConfigPanel.tsx:1-18`):
```tsx
import { useEffect, useRef, useState } from "react"
import { errorMessage, GENERATION_POLL_CEILING_MS } from "@/api/client"
```

**Full hook shape (already drafted in RESEARCH.md's Pattern 1, derived directly from the above) — use as the starting point:** see `.planning/phases/07-unified-generate-stop-play-button-trimmed-segment-table/07-RESEARCH.md` lines 156-250 for the complete `useGenerateStopPlay` implementation (`hasAudio`, `isExternallyGenerating`, optional `poll`, `onGenerate`/`onStop`/`onRefresh` params → `{ status, error, handleGenerate, handleStop }`).

**Batch site variant note:** `ConfigPanel.tsx`'s batch block has its own 4-line status derivation already (`isCancelling ? "stopping" : isSelfRunning ? "generating" : hasOutput ? "ready" : "idle"`, mirroring lines 244-266) fed by SSE (`useGenerationStream`), not by this hook's interval poll. Per RESEARCH.md, either call the hook with `poll: false` or leave the batch site's derivation inline — planner's call, but the derivation **order** (`stopping` → `generating` → `ready` → `idle`) is load-bearing (Pitfall 2, `output_path` never clears at batch-start).

---

### `frontend/src/components/SegmentTable.tsx` (modified)

**Analog:** itself — in-place refactor.

**Delete entirely** (TBL-05/D-07): `StatusBadge`/`STATUS_BADGE` (lines 60-86), the `status` columnHelper entry (lines 498-502), and — per RESEARCH.md Pitfall 4 — the now-dead `Badge`, `AlertCircle`, `CheckCircle2`, `Clock` imports (lines 9-11, 30). Keep `Loader2` (still used by the button and `BulkReassignToolbar`).

**Replace** `GeneratePlayButton` function body (lines 99-269) with a thin wrapper: call `useGenerateStopPlay` for state, render `<GenerateStopPlayButton size="sm" ... />`.

**Columns array to trim** (`SegmentTable.tsx:456-516`) from 5 entries (`select`, `narrator`, `text`, `status`, `controls`) to 4 (`select`, `narrator`, `text`, `controls`).

---

### `frontend/src/components/ConfigPanel.tsx` (modified)

**Analog:** itself — in-place refactor, two sites.

**`CharacterPreviewRow`** (lines 55-204): collapse the icon Play/Pause + conditional Generate/Stop buttons (lines 146-186) into one `<GenerateStopPlayButton size="sm" ... />`.

**Batch block** (lines 456-497 and surrounding `hasOutput`/`isSelfRunning`/`isCancelling` derivations at lines 243-266): collapse `Generate All`/`Stop` into `<GenerateStopPlayButton size="default" className="w-full" ... />`. Reuse the existing derivation variables verbatim — `isSelfRunning` (line 254), `isCancelling` (state), `hasOutput` (line 266) — just route them through the `stopping → generating → ready → idle` precedence order into `status` instead of the current three separate `Button`s.

**Existing `hasOutput`/download pattern to mirror for the new Play `<audio>`** (`ConfigPanel.tsx:266-275`, `520-535`):
```tsx
const hasOutput = Boolean(project.output_path)
...
<Button asChild={hasOutput} ... disabled={!hasOutput}>
  {hasOutput ? (
    <a href={downloadUrl(project.id)} download={downloadFilename}>Download</a>
  ) : ("Download")}
</Button>
```
Download button stays completely unchanged (D-04) — sits below the new unified button in the same `gap-3` section.

**New hidden `<audio>` for joined output** — mirror the 3x-repeated pattern already at `SegmentTable.tsx:252-260`, `ConfigPanel.tsx:187-195`, `CharacterCard.tsx:243-251`:
```tsx
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

---

### `frontend/src/components/CharacterCard.tsx` (modified)

**Analog:** `ConfigPanel.tsx`'s `CharacterPreviewRow` (lines 55-204) — the more correct sibling; per RESEARCH.md Pitfall 3, `CharacterCard`'s current logic (no Stop button, hardcoded 60s ceiling) should be **replaced wholesale** by the shared hook, not patched.

**Current button block to replace** (`CharacterCard.tsx:209-239`):
```tsx
{hasPreview ? (
  <Button type="button" size="icon" variant={isPlaying ? "default" : "outline"}
    onClick={togglePlayback} aria-label={...}>
    {isPlaying ? <Pause /> : <Play />}
  </Button>
) : (
  <Button type="button" size="sm" variant="outline"
    disabled={isGenerating || generationLocked}
    onClick={() => void handleGenerate()}
    aria-label={`Generate voice preview for ${character.name}`}>
    {isGenerating ? <Loader2 className="animate-spin" /> : "Generate"}
  </Button>
)}
```
Replace with one `<GenerateStopPlayButton size="sm" ... />` fed by `useGenerateStopPlay`, gaining a working Stop control for the first time (D-01).

**Everything else stays untouched (D-02):** name `Input` (lines 160-166), Preset `Select` (174-194), Voice Instructions `Textarea` (196-207), "Voice assigned" `Badge` (241), merge `Dialog`/button (253-303) — do not reshape row layout.

**Convergence note:** delete the local 60s poll ceiling (`CharacterCard.tsx:80-88`, hardcoded `60000`) in favor of the shared hook's `GENERATION_POLL_CEILING_MS` (already `330_000` in `api/client.ts`).

---

### `frontend/src/components/CastWizard.tsx` (modified)

**Analog:** itself — one-class change, verified current markup at line 108.

**Exact edit** (`CastWizard.tsx:108`, per RESEARCH.md Pattern 3 / UI-SPEC Component Contracts §5):
```tsx
// before:
<div className="flex flex-col gap-8 xl:flex-row xl:gap-8">
// after:
<div className="flex flex-col gap-8 xl:flex-row xl:items-start xl:gap-8">
```
The inner column (`CastWizard.tsx:109`, `xl:w-[420px] xl:flex-none`) is untouched — only the outer flex container's `items-*` behavior changes.

---

### `frontend/src/api/client.ts` (modified: add `outputUrl`)

**Analog:** `downloadUrl` (line 320).

**Read `downloadUrl` first, then add `outputUrl` immediately adjacent, mirroring it verbatim** (per RESEARCH.md Pattern 2):
```typescript
export function outputUrl(projectId: string): string {
  return `/projects/${projectId}/download`
}
```
Same route as `downloadUrl` — no new backend endpoint. Also verify `GENERATION_POLL_CEILING_MS` (line 11) and `errorMessage` (line 17) are already exported (confirmed) for the new hook to import.

---

## Shared Patterns

### Poll-until-settled after a fire-and-forget 202
**Source:** `ConfigPanel.tsx:84-101` (most complete version, has WR-02 ceiling-timeout recovery) and `SegmentTable.tsx:144-167` (has the `hasObservedGeneratingRef` stale-guard)
**Apply to:** `useGenerateStopPlay` hook, consumed by `SegmentTable.tsx`, `ConfigPanel.tsx`'s `CharacterPreviewRow`, `CharacterCard.tsx`. NOT the batch site (SSE-driven instead, see `useGenerationStream`).

### Hidden `<audio>` + isPlaying toggle
**Source:** `CharacterCard.tsx:243-251` (pattern's origin, per code comments in the other 2 sites), `SegmentTable.tsx:252-260`, `ConfigPanel.tsx:187-195`
**Apply to:** All 4 sites' `ready`-state playback, including the new batch-site joined-output `<audio>`.

### Error text below control
**Source:** identical at all 3 existing sites, e.g. `SegmentTable.tsx:262-266`
```tsx
{error && (
  <p className="text-xs text-destructive" role="alert">{error}</p>
)}
```
**Apply to:** All 4 call sites, unchanged copy strings per UI-SPEC Copywriting Contract.

### `generationLocked` prop threading (do NOT re-derive)
**Source:** `useGenerationLock()` hook (`frontend/src/hooks/useGenerationLock.ts`), consumed once in `ProjectScreen.tsx` and threaded down as a prop
**Apply to:** `<GenerateStopPlayButton>` and `useGenerateStopPlay` must accept `generationLocked`/`disabled` as a prop, never call `useGenerationLock()` themselves (RESEARCH.md Anti-Pattern: avoids N redundant 1.5s polls).

## No Analog Found

None — all 7 files have a direct or near-direct analog already in the codebase; this phase is a pure consolidation refactor with zero green-field logic (confirmed by RESEARCH.md's "Don't Hand-Roll" section).

## Metadata

**Analog search scope:** `frontend/src/components/`, `frontend/src/hooks/`, `frontend/src/api/client.ts` (full reads of `SegmentTable.tsx`, `ConfigPanel.tsx`, `CharacterCard.tsx`, `CastWizard.tsx`, `api/client.ts` this session; `07-UI-SPEC.md` and `07-RESEARCH.md` read for the exact prop contract and hook draft)
**Files scanned:** 5 component files + client.ts + UI-SPEC + RESEARCH (all already fully read by researcher this phase; no new grep-based analog search needed since this phase's "closest analog" for every new/modified file is another file in this same phase's own scope)
**Pattern extraction date:** 2026-07-15
