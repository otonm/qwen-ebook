import { useCallback, useEffect, useState } from "react"

import { getVoices, type Character, type Segment, type VoicePreset } from "@/api/client"
import { CharacterCard } from "@/components/CharacterCard"
import { SegmentPreview } from "@/components/SegmentPreview"
import { refreshProject } from "@/hooks/useAnalysisStream"

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

  useEffect(() => {
    getVoices().then(setVoices).catch(() => setVoices([]))
  }, [])

  const refetch = useCallback(() => {
    refreshProject(projectId).then(({ cast: nextCast, segments: nextSegments }) => {
      setCast(nextCast)
      setSegments(nextSegments)
    })
  }, [projectId])

  const handleCastRefresh = useCallback(() => {
    refetch()
    for (const delay of REFRESH_DELAYS_MS) {
      setTimeout(refetch, delay)
    }
  }, [refetch])

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-12 p-6">
      <h1 className="text-2xl font-semibold">Review Cast</h1>

      <div className="flex flex-col gap-8 xl:flex-row xl:gap-8">
        <div className="grid flex-1 grid-cols-1 gap-6 sm:grid-cols-2">
          {cast.map((character) => (
            <CharacterCard
              key={character.id}
              character={character}
              otherCharacters={cast.filter((c) => c.id !== character.id)}
              voices={voices}
              onCastRefresh={handleCastRefresh}
            />
          ))}
        </div>

        <div className="flex-1 xl:max-w-md">
          <SegmentPreview segments={segments} />
        </div>
      </div>
    </div>
  )
}
