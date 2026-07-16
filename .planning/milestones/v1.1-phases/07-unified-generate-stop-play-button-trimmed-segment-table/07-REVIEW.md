---
phase: 07-unified-generate-stop-play-button-trimmed-segment-table
reviewed: 2026-07-15T21:41:52Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - frontend/src/api/client.ts
  - frontend/src/components/CastWizard.tsx
  - frontend/src/components/CharacterCard.tsx
  - frontend/src/components/ConfigPanel.tsx
  - frontend/src/components/GenerateStopPlayButton.tsx
  - frontend/src/components/SegmentTable.tsx
  - frontend/src/hooks/useGenerateStopPlay.ts
  - frontend/vite.config.ts
findings:
  critical: 3
  warning: 5
  info: 4
  total: 12
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-07-15T21:41:52Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Reviewed the unified generate/stop/play control (`GenerateStopPlayButton` +
`useGenerateStopPlay`) and its three consumer sites (`CharacterCard`,
`ConfigPanel`, `SegmentTable`), plus `CastWizard.tsx`, `client.ts`, and
`vite.config.ts`. The shared hook's core "stopping > generating > ready >
idle" precedence and the WR-02 poll-ceiling recovery are sound, and I traced
the previously-hypothesized "regenerate gets stuck on red spinner forever"
scenario to be unreachable in practice — `GenerateStopPlayButton.handleClick`
only calls `onGenerate` while `status === "idle"`, which by construction
means `hasAudio` was false at that moment, so the settle effect's "hasAudio
never starts true" assumption always holds *today*. That said, the
assumption is enforced only by a different component's click-gating, not by
the hook itself — see WARNING WR-01 below.

Three real correctness gaps did turn up: the Model-swap control is the only
generation-adjacent action in `ConfigPanel` that isn't gated behind
`generationLocked`, `useGenerateStopPlay.handleStop` optimistically clears
local "generating" state even when the stop request itself failed (an
honesty violation of the very invariant its own comment describes), and
`ConfigPanel` has no rendering path at all for a batch failure that isn't
tied to a per-segment failure count. Several unhandled-promise-rejection
gaps in `CastWizard`/`CharacterCard` mean some user actions fail completely
silently, inconsistent with the `role="alert"` error pattern used
everywhere else in this phase.

## Critical Issues

### CR-01: Model swap isn't blocked while a generation is in flight

**File:** `frontend/src/components/ConfigPanel.tsx:306-325` (specifically the `disabled` prop on line 310)
**Issue:** `setProjectModel` (per its own docstring in `client.ts:277-291`) is
"an explicit-load model swap trigger... fires the swap immediately
(blocking for the request's duration, tens of seconds)... every
segment/character preview invalidated". This is a heavyweight, disruptive,
GPU-state-mutating operation. Every other generation-triggering control in
this panel (`CharacterPreviewRow`'s button, the batch `GenerateStopPlayButton`)
is disabled via the `generationLocked` prop while any generation is active.
The Model `<Select>` is not:
```tsx
<Select
  value={project.tts_model}
  onValueChange={(value) => void handleModelChange(value)}
  disabled={isSwapping}
>
```
`generationLocked`/`isSelfRunning` is never consulted here. A user can start
"Generate All" (or even just a single character preview) and, while it is
running, swap the resident TTS checkpoint out from under it — reloading the
GPU model mid-inference and invalidating every preview the still-running
batch may depend on. This is a race with real data-corruption/crash
potential on the one shared GPU (RX 9070 XT, no task queue — see CLAUDE.md
constraints), not just a UI nicety.
**Fix:**
```tsx
<Select
  value={project.tts_model}
  onValueChange={(value) => void handleModelChange(value)}
  disabled={isSwapping || generationLocked}
>
```
(and surface a `title`/disabled-reason similar to `disabledReason` on
`GenerateStopPlayButton`, e.g. "Can't switch models while a generation is
running.")

### CR-02: `handleStop` optimistically clears "generating" state even when the stop request fails

**File:** `frontend/src/hooks/useGenerateStopPlay.ts:116-132`
**Issue:**
```ts
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
```
The `finally` block unconditionally clears `isGenerating`/`isStopping`,
including on the `catch` path. The comment directly above the `await
onStop()` call states the design intent explicitly: "onStop's await only
resolves once the backend has genuinely finished the underlying call and
released the lock... that's the confirmed-stopped signal itself, not an
optimistic guess, so clearing local state here is honest." That's true only
for the success path. When `onStop()` itself fails (network error, 5xx,
etc.), nothing has been confirmed — the backend generation may still be
running — yet the UI still reverts to `idle`/`ready`. For character/segment
previews with no external signal, this both (a) misrepresents state to the
user (a still-running generation now looks stopped) and (b) opens the door
to the user clicking Generate again, racing the single-flight lock the rest
of the app relies on (`generationLocked`).
**Fix:**
```ts
async function handleStop() {
  setIsStopping(true)
  setError(null)
  try {
    await onStop()
    setIsGenerating(false)
    setIsStopping(false)
    onRefresh()
  } catch (err) {
    // Unconfirmed — we don't know if the backend actually stopped, so
    // don't optimistically clear isGenerating. Only clear isStopping and
    // let the next poll/refresh reconcile the real state.
    setIsStopping(false)
    setError(errorMessage(err, "Couldn't stop generation."))
  }
}
```

### CR-03: A batch failure with zero failed segments is completely silent

**File:** `frontend/src/components/ConfigPanel.tsx:172-176, 292-298, 419-440`
**Issue:** The only surfaced error state tied to `generation.status ===
"error"` is `joinBlocked`:
```ts
const joinBlocked = generation.status === "error" && failedCount > 0
```
and its rendering, gated on `joinBlocked` (lines 427-435). If the SSE stream
ever reports `status: "error"` for a reason that isn't "N segments
individually failed" (e.g. the batch process crashed, GPU OOM, an
unhandled backend exception before any segment was marked `error`), then
`failedCount` is 0, `joinBlocked` is false, and `batchStatus` falls through
to `hasOutput ? "ready" : "idle"` (lines 292-298) — the button silently
reverts to yellow "Generate All" as if nothing happened, with **no** error
text anywhere in the panel. `batchError` (used for the `handleGenerateAll`/
`handleStop` try/catch paths) is never set by the SSE-driven `generation`
state, only by this component's own fetch calls succeeding-or-failing at
*starting* the run — it has no visibility into a later async failure.
**Fix:** Add a general-purpose error branch alongside `joinBlocked` that
fires whenever `generation.status === "error"` regardless of `failedCount`:
```tsx
{generation.status === "error" && failedCount === 0 && (
  <p className="text-xs text-destructive" role="alert">
    Generation failed unexpectedly. Try Generate All again.
  </p>
)}
```
(Check whether `GenerationStreamState` — `useGenerationStream.ts`, not in
this review's scope — already carries a message field; if so, render it
instead of a generic string.)

## Warnings

### WR-01: Settle logic in `useGenerateStopPlay` depends on an invariant enforced only by a different component

**File:** `frontend/src/hooks/useGenerateStopPlay.ts:92-102`, `frontend/src/components/GenerateStopPlayButton.tsx:63-72`
**Issue:** The hook's "settle" effect only ever sets
`hasObservedGeneratingRef.current = true` when `isGenerating && !hasAudio`
(for the no-external-signal case, i.e. character/preview rows). If
`handleGenerate` were ever invoked while `hasAudio` is already `true`, this
ref never gets set, and the later clearing branch (`if
(hasObservedGeneratingRef.current) { ...settle... }`) never fires —
`isGenerating` would stay `true` forever, wedging the button on the red
spinner. Today this can't happen only because
`GenerateStopPlayButton.handleClick` gates `onGenerate` behind `status ===
"idle"`, and `status` is itself derived from `hasAudio` — so by the time
`onGenerate` fires, `hasAudio` is guaranteed false. That's an invariant
enforced entirely by the presentational component, invisible to the hook
that calls itself "the shared poll/settle state machine." Any future call
site that invokes `handleGenerate` directly (bypassing the button's
gating — e.g. a keyboard shortcut, a "regenerate" affordance added later)
reintroduces a stuck-forever bug with no compiler or runtime guard against
it.
**Fix:** Make the hook self-sufficient — set the "observed generating"
signal directly inside `handleGenerate` (where the precondition is locally
known) instead of inferring it from a render effect:
```ts
async function handleGenerate() {
  setIsGenerating(true)
  hasObservedGeneratingRef.current = true
  setError(null)
  ...
}
```
and drop the `isGenerating && !hasAudio` half of the effect's condition.

### WR-02: Poll-ceiling effect keyed on `onRefresh` identity can indefinitely reset the WR-02 stuck-forever safety net

**File:** `frontend/src/hooks/useGenerateStopPlay.ts:58-74`
**Issue:**
```ts
useEffect(() => {
  if (!poll || !isGenerating) return undefined
  const interval = setInterval(onRefresh, 1500)
  const timeout = setTimeout(() => {
    clearInterval(interval)
    setIsGenerating(false)
    setError("Generation is taking too long — try again.")
  }, GENERATION_POLL_CEILING_MS)
  return () => {
    clearInterval(interval)
    clearTimeout(timeout)
  }
}, [poll, isGenerating, onRefresh])
```
`onRefresh` is in the dependency array. `CastWizard` passes a stable,
`useCallback`-wrapped `handleCastRefresh`, so it's safe there — but
`ConfigPanel.CharacterPreviewRow` and `SegmentTable.GeneratePlayButton`
receive `onRefresh` straight through as a prop from their parents
(`ConfigPanel`'s and `SegmentTable`'s own `onRefresh` prop, ultimately
supplied by the screen that isn't in this review's file list). If that
prop is a fresh closure on every render of the parent screen (common when
not explicitly `useCallback`-wrapped), this effect tears down and
re-creates its `interval`/`timeout` on every parent re-render while
`isGenerating` is true — which resets the `GENERATION_POLL_CEILING_MS`
countdown every time, defeating the exact "stuck forever" recovery this
effect exists to guarantee (per its own WR-02 comment).
**Fix:** Decouple the timer lifecycle from `onRefresh`'s identity via a ref:
```ts
const onRefreshRef = useRef(onRefresh)
useEffect(() => {
  onRefreshRef.current = onRefresh
}, [onRefresh])

useEffect(() => {
  if (!poll || !isGenerating) return undefined
  const interval = setInterval(() => onRefreshRef.current(), 1500)
  const timeout = setTimeout(() => {
    clearInterval(interval)
    setIsGenerating(false)
    setError("Generation is taking too long — try again.")
  }, GENERATION_POLL_CEILING_MS)
  return () => {
    clearInterval(interval)
    clearTimeout(timeout)
  }
}, [poll, isGenerating])
```

### WR-03: Several async handlers in `CastWizard`/`CharacterCard` have no error handling — failures are silently swallowed

**File:** `frontend/src/components/CastWizard.tsx:60-65, 82-88`; `frontend/src/components/CharacterCard.tsx:100-103, 130-136`
**Issue:** Four call sites await/chain a network call with no `.catch`/
`try-catch`, unlike essentially every other mutation in this phase (which
follows the `errorMessage`/`role="alert"` pattern documented in
`client.ts:13-19`):
- `CastWizard.refetch` (60-65): `refreshProject(...).then(...)` — no `.catch`. A failed refetch after any cast edit/merge just does nothing, with an unhandled promise rejection in the console.
- `CastWizard.handleUndoMerge` (82-88): `void undoMergeCharacter(pendingUndo).then(...)` — no `.catch`. If undo fails, `pendingUndo` is never cleared and the user gets zero feedback that Undo didn't work.
- `CharacterCard.saveField` (100-103): `await patchCharacter(...); onCastRefresh()` with no try/catch, called from `handleNameBlur`/`handleVoiceInstructionsBlur`/`handlePresetChange` via `void saveField(...)`. If the PATCH fails (e.g. validation error), the user's edit silently fails to persist with no indication — they may believe the name/voice change was saved when it wasn't.
- `CharacterCard.confirmMerge` (130-136): `const { undo } = await mergeCharacter(...)` with no try/catch. If the merge fails, the dialog just... does nothing on click, with no error shown.
**Fix:** Add the same `errorMessage`/`role="alert"` pattern used elsewhere
in these two files (e.g. `previewError` in `CharacterCard`) to each of
these four call sites, e.g.:
```ts
async function saveField(patch: Parameters<typeof patchCharacter>[1]) {
  try {
    await patchCharacter(character.id, patch)
    onCastRefresh()
  } catch (err) {
    setSaveError(errorMessage(err, "Couldn't save changes."))
  }
}
```

### WR-04: Preview/segment/output audio URLs are fixed per-id with no cache-busting, risking stale playback after regeneration

**File:** `frontend/src/api/client.ts:207-209, 246-248, 328-330`; consumers `frontend/src/components/CharacterCard.tsx:216`, `frontend/src/components/ConfigPanel.tsx:107, 408`, `frontend/src/components/SegmentTable.tsx:121`
**Issue:** `previewUrl(characterId)`, `segmentAudioUrl(id)`, and
`outputUrl(projectId)` all return a fixed URL per id
(`/characters/{id}/preview.wav`, `/segments/{id}/audio.wav`,
`/projects/{id}/download`) with no version/cache-busting query parameter.
Every `<audio src={...}>` in these three components reuses that same fixed
URL across regenerations (e.g. edit voice instructions → regenerate
preview; edit segment text → regenerate its audio). Browsers are free to
serve a cached response for an unchanged URL; nothing in the frontend
forces a refetch of the new bytes after a regeneration completes — the
`<audio>` element's `src` attribute string doesn't change, so React won't
even force a re-mount/reload. Unless the backend is emitting strict
no-cache headers for these routes (not visible from these files), a user
who edits a voice/segment and regenerates could hear the *previous* take.
**Fix:** Append a cache-busting/version query param that only changes when
the underlying audio actually changes, e.g. using the segment's
`generation_status` transition count or a server-supplied version field
(the `voice_version` field already exists on the merge-undo snapshot in
`client.ts:114` — consider surfacing it on `Character` too):
```ts
export function previewUrl(characterId: string, version?: number): string {
  return `/characters/${characterId}/preview.wav${version != null ? `?v=${version}` : ""}`
}
```
At minimum, verify the backend sends `Cache-Control: no-store` on these
three routes if no client-side version param is added.

### WR-05: `autoplayRef` stays `true` after a failed generate, causing an unrelated future autoplay

**File:** `frontend/src/components/SegmentTable.tsx:71, 83-93`
**Issue:**
```ts
const autoplayRef = useRef(false)
...
useEffect(() => {
  if (autoplayRef.current && hasAudio && audioRef.current) {
    autoplayRef.current = false
    void audioRef.current.play()
  }
}, [hasAudio, segment.audio_path])

function handleGenerateClick() {
  autoplayRef.current = true
  void handleGenerate()
}
```
`autoplayRef.current` is only ever reset to `false` inside the effect,
which only runs once `hasAudio` becomes `true`. If the triggered generation
fails (network error, backend error, poll-ceiling timeout), `hasAudio`
never becomes true, `autoplayRef.current` is left `true` indefinitely. If
this same row's audio later becomes available through an unrelated path
(e.g. a batch "Generate All" run picks up this segment and it succeeds
later, or the parent refetches and the row happens to now have
`audio_path` from a different trigger), the effect fires and
unexpectedly autoplays audio the user never asked to hear right now.
**Fix:** Reset the ref on the error path too:
```ts
useEffect(() => {
  if (error) autoplayRef.current = false
}, [error])
```

## Info

### IN-01: `handleGenerateAll` restarts the SSE connection even when the batch didn't actually start

**File:** `frontend/src/components/ConfigPanel.tsx:193-218`
**Issue:** `generation.restart()` (line 203) is called unconditionally,
before checking `result.status`. When the response is `"busy"` (a
different project/generation holds the single global slot) nothing
actually started for *this* project, yet the SSE stream is torn down and
reopened anyway, which can briefly desync `isBatchRunning`/`batchStatus`
from reality.
**Fix:** Only call `generation.restart()` when `result.status` indicates
this project's run actually (re)started, e.g. skip it for `"busy"`.

### IN-02: URL builder helpers interpolate ids without `encodeURIComponent`

**File:** `frontend/src/api/client.ts:207-209, 246-248, 320-330` (and the various `fetch(\`/segments/${id}...\`)` calls throughout the file)
**Issue:** IDs are always trusted server-generated UUIDs today, so this is
low-risk, but none of the template-interpolated URL paths encode the id.
**Fix:** Wrap with `encodeURIComponent(id)` as defensive practice, e.g.
`` `/characters/${encodeURIComponent(characterId)}/preview.wav` ``.

### IN-03: Poll interval `1500` is an inline magic number

**File:** `frontend/src/hooks/useGenerateStopPlay.ts:60`
**Issue:** `setInterval(onRefresh, 1500)` — unlike `GENERATION_POLL_CEILING_MS`
(a named, documented export), the 1500ms poll cadence is an inline literal.
**Fix:** Extract to a named constant (e.g. `GENERATION_POLL_INTERVAL_MS`)
next to `GENERATION_POLL_CEILING_MS` in `client.ts` for consistency and
discoverability.

### IN-04: Inconsistent `onGenerate` wrapping style across call sites

**File:** `frontend/src/components/CharacterCard.tsx:206`, `frontend/src/components/ConfigPanel.tsx:100`, `frontend/src/components/SegmentTable.tsx:114`
**Issue:** `CharacterCard` passes the hook's `handleGenerate` directly as
`onGenerate={handleGeneratePreview}`, while `ConfigPanel.CharacterPreviewRow`
and `SegmentTable.GeneratePlayButton` wrap it as `onGenerate={() => void
handleGenerate()}` / `onGenerate={handleGenerateClick}`. Functionally
equivalent (TS allows a `Promise`-returning function where `() => void` is
expected), but the inconsistency makes the three near-identical call sites
harder to diff against each other.
**Fix:** Pick one convention (prefer the explicit `() => void handleGenerate()`
form, since it makes the fire-and-forget intent visible at the call site)
and apply it uniformly.

---

_Reviewed: 2026-07-15T21:41:52Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
