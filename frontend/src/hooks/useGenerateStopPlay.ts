// GEN-12: shared poll/settle/error state machine for the unified
// generate/stop/play control, extracted from the near-identical
// implementations duplicated across SegmentTable.tsx's GeneratePlayButton
// and ConfigPanel.tsx's CharacterPreviewRow (07-RESEARCH.md Pattern 1).
//
// This hook owns only the *stateful* half of the control — the
// presentational half is <GenerateStopPlayButton>, which takes the
// `status` this hook derives as a plain prop.
import { useEffect, useRef, useState } from "react"

import { errorMessage, GENERATION_POLL_CEILING_MS } from "@/api/client"

export type GspStatus = "idle" | "generating" | "stopping" | "ready"

export interface UseGenerateStopPlayOptions {
  /** True once audio/preview/output exists for this row — drives the
   * "ready" (green Play) state once nothing is in flight. */
  hasAudio: boolean
  /** True while a batch run or another trigger already has this
   * row/preview generating — e.g. segment.generation_status ===
   * "generating", or the batch site's own SSE-driven isSelfRunning. */
  isExternallyGenerating: boolean
  /** Set false for sites that already have another live signal (e.g. SSE)
   * driving isExternallyGenerating — no interval poll needed there.
   * Defaults to true (segment/character preview sites, which have no SSE). */
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
  // Tracks whether we've actually seen this row hit "generating" (from
  // either our own trigger or an external one, e.g. a batch run) since the
  // last settle — the signal a poll/refetch uses to know the row has since
  // left "generating" for real, rather than reading a stale pre-click
  // status as "already settled". Ported verbatim from
  // SegmentTable.tsx's GeneratePlayButton / ConfigPanel.tsx's
  // CharacterPreviewRow.
  const hasObservedGeneratingRef = useRef(false)
  const isRowGenerating = isGenerating || isExternallyGenerating

  // Poll for the 202+background-task result while we're the one waiting on
  // a generation we triggered — WR-04 fix: ceiling is GENERATION_POLL_CEILING_MS
  // (well above the backend's own 300s synth timeout) so a legitimately slow
  // call isn't abandoned mid-poll, only a genuinely failed/hung one is.
  // Gated on `poll` too — the batch site has SSE already and opts out.
  useEffect(() => {
    if (!poll || !isGenerating) return undefined
    const interval = setInterval(onRefresh, 1500)
    // WR-02: hitting the ceiling used to only stop the poll, leaving
    // isGenerating stuck true forever (spinner with no recovery path)
    // whenever the backend silently swallowed a failure. Reset generating
    // state and surface an error so the user can retry instead of reloading.
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

  // The row settles (leaves "generating") once a refetch/SSE update lands —
  // clear both the generating and stopping flags only once we've genuinely
  // observed the transition, never on the first stale render. A transition
  // is observed either via a genuine external signal (isExternallyGenerating,
  // e.g. segment.generation_status) OR, for sites with no such signal —
  // character previews (CharacterPreviewRow/CharacterCard) always pass
  // isExternallyGenerating: false — via this hook's own isGenerating still
  // being true while hasAudio hasn't caught up yet. Bug fix (07-05
  // checkpoint): before this, character-preview sites never observed any
  // transition at all, so isGenerating was never cleared once the poll's
  // onRefresh picked up the finished preview — the button stayed stuck on
  // the red spinner forever even though hasAudio had gone true. Folding
  // the self-triggered case into this ref-guarded branch (rather than a
  // second effect keyed directly off hasAudio) keeps the "settle" write
  // gated on a genuinely-observed prior generating state, not a bare
  // prop-derived setState.
  useEffect(() => {
    if (isExternallyGenerating || (isGenerating && !hasAudio)) {
      hasObservedGeneratingRef.current = true
      return
    }
    if (hasObservedGeneratingRef.current) {
      hasObservedGeneratingRef.current = false
      setIsGenerating(false)
      setIsStopping(false)
    }
  }, [isExternallyGenerating, isGenerating, hasAudio])

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
      // onStop's await only resolves once the backend has genuinely
      // finished the underlying call and released the lock (04-03) —
      // that's the confirmed-stopped signal itself, not an optimistic
      // guess, so clearing local state here is honest per D-03/D-05.
      await onStop()
    } catch (err) {
      setError(errorMessage(err, "Couldn't stop generation."))
    } finally {
      setIsGenerating(false)
      setIsStopping(false)
      onRefresh()
    }
  }

  // Load-bearing precedence order (D-08/GEN-12): stopping > generating >
  // ready > idle. A row that is both generating and already has stale
  // audio must render generating, never ready.
  const status: GspStatus = isStopping
    ? "stopping"
    : isRowGenerating
      ? "generating"
      : hasAudio
        ? "ready"
        : "idle"

  return { status, error, handleGenerate, handleStop }
}
