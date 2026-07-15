import { useCallback, useEffect, useRef, useState } from "react"

import {
  errorMessage,
  getVoices,
  undoMergeCharacter,
  type Character,
  type MergeUndoSnapshot,
  type Segment,
  type VoicePreset,
} from "@/api/client"
import { Button } from "@/components/ui/button"
import { CharacterCard } from "@/components/CharacterCard"
import { SegmentPreview } from "@/components/SegmentPreview"
import { refreshProject } from "@/hooks/useAnalysisStream"
import { useGenerationLock } from "@/hooks/useGenerationLock"

interface CastWizardProps {
  projectId: string
  initialCast: Character[]
  initialSegments: Segment[]
}

// A handful of short-interval refetches after any edit/merge/voice-assign
// catch the async preview WAV landing (server generates it in the
// background) without building a second SSE channel for it.
const REFRESH_DELAYS_MS = [800, 1800, 3500]

/** WIZ-01..05, D-14/D-15: the screen's focal point — the single-page cast
 * list (all cards visible at once) alongside the read-only segment
 * preview (Task 3's SegmentPreview). */
export function CastWizard({ projectId, initialCast, initialSegments }: CastWizardProps) {
  const [cast, setCast] = useState(initialCast)
  const [segments, setSegments] = useState(initialSegments)
  const [voices, setVoices] = useState<VoicePreset[]>([])
  // Global (app-wide) single-flight signal — only one generation may be in
  // flight at a time, so every card's Generate button disables while any
  // one of them (or a segment/batch elsewhere) is active.
  const generationLocked = useGenerationLock()
  // Only the most recent merge can be undone — a new merge (or an
  // explicit dismiss) replaces/clears this, see undo-merge's ponytail note.
  const [pendingUndo, setPendingUndo] = useState<MergeUndoSnapshot | null>(null)
  // WR-03: refetch()/handleUndoMerge() used to have no .catch — a failed
  // request silently did nothing beyond an unhandled promise rejection in
  // the console, inconsistent with the role="alert" pattern used elsewhere
  // in this phase.
  const [castError, setCastError] = useState<string | null>(null)
  // WR-06: track pending REFRESH_DELAYS_MS timeout ids so they can be
  // cleared on unmount — otherwise a scheduled refetch() still fires and
  // calls setCast/setSegments after the component (e.g. user navigated
  // away or re-uploaded mid-window) is gone.
  const timeoutsRef = useRef<number[]>([])

  useEffect(() => {
    getVoices().then(setVoices).catch(() => setVoices([]))
  }, [])

  useEffect(() => {
    return () => {
      for (const id of timeoutsRef.current) {
        clearTimeout(id)
      }
    }
  }, [])

  const refetch = useCallback(() => {
    refreshProject(projectId)
      .then(({ cast: nextCast, segments: nextSegments }) => {
        setCast(nextCast)
        setSegments(nextSegments)
      })
      .catch((err: unknown) => setCastError(errorMessage(err, "Couldn't refresh cast.")))
  }, [projectId])

  const handleCastRefresh = useCallback(() => {
    refetch()
    for (const delay of REFRESH_DELAYS_MS) {
      timeoutsRef.current.push(window.setTimeout(refetch, delay))
    }
  }, [refetch])

  const handleMerged = useCallback(
    (undo: MergeUndoSnapshot) => {
      setPendingUndo(undo)
      handleCastRefresh()
    },
    [handleCastRefresh]
  )

  function handleUndoMerge() {
    if (!pendingUndo) return
    setCastError(null)
    void undoMergeCharacter(pendingUndo)
      .then(() => {
        setPendingUndo(null)
        handleCastRefresh()
      })
      .catch((err: unknown) => setCastError(errorMessage(err, "Couldn't undo merge.")))
  }

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-12 p-6">
      <h1 className="text-2xl font-semibold">Review Cast</h1>

      {castError && (
        <p className="text-xs text-destructive" role="alert">
          {castError}
        </p>
      )}

      {pendingUndo && (
        <div className="flex items-center justify-between gap-4 rounded-lg bg-secondary p-3 text-sm">
          <span>Merged &quot;{pendingUndo.character.name}&quot; away.</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setPendingUndo(null)}>
              Dismiss
            </Button>
            <Button size="sm" onClick={handleUndoMerge}>
              Undo
            </Button>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-8 xl:flex-row xl:items-start xl:gap-8">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:w-[420px] xl:flex-none xl:grid-cols-1">
          {cast.map((character) => (
            <CharacterCard
              key={character.id}
              character={character}
              otherCharacters={cast.filter((c) => c.id !== character.id)}
              voices={voices}
              onCastRefresh={handleCastRefresh}
              onMerged={handleMerged}
              generationLocked={generationLocked}
            />
          ))}
        </div>

        <div className="flex-1">
          <SegmentPreview segments={segments} />
        </div>
      </div>
    </div>
  )
}
