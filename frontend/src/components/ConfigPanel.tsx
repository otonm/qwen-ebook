import { Loader2, Pause, Play } from "lucide-react"
import { useRef, useState } from "react"

import {
  previewUrl,
  runBatchGeneration,
  type Character,
  type Project,
  type Segment,
} from "@/api/client"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import type { GenerationStreamState } from "@/hooks/useGenerationStream"

// CFG-01: only one TTS model is in scope for v1 (D-17) — a fixed display
// value, not a dropdown (RESEARCH.md "Claude's Discretion").
const TTS_MODEL_DISPLAY_NAME = "Qwen3-TTS-12Hz-1.7B-CustomVoice"

function ConfigField({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-semibold text-muted-foreground">{label}</span>
      <span className="truncate text-sm" title={value}>
        {value}
      </span>
    </div>
  )
}

/** CFG-02: reuses CharacterCard's play/pause preview pattern (a hidden
 * <audio> + isPlaying toggle) for a compact, read-only row — this panel
 * only previews voices, editing/merging stays the wizard's job. */
function CharacterPreviewRow({ character }: { character: Character }) {
  const [isPlaying, setIsPlaying] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)
  const hasPreview = Boolean(character.preview_audio_path)

  function togglePlayback() {
    const audio = audioRef.current
    if (!audio) return
    if (isPlaying) {
      audio.pause()
    } else {
      void audio.play()
    }
  }

  return (
    <div className="flex items-center gap-2 rounded-md bg-background px-2 py-1.5">
      <Button
        type="button"
        size="icon-sm"
        variant={isPlaying ? "default" : "outline"}
        disabled={!hasPreview}
        onClick={togglePlayback}
        aria-label={
          isPlaying ? `Pause preview for ${character.name}` : `Play preview for ${character.name}`
        }
      >
        {isPlaying ? <Pause /> : <Play />}
      </Button>
      <span className="truncate text-sm">{character.name}</span>
      {hasPreview && (
        <audio
          ref={audioRef}
          src={previewUrl(character.id)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={() => setIsPlaying(false)}
        />
      )}
    </div>
  )
}

interface ConfigPanelProps {
  project: Project
  segments: Segment[]
  generation: GenerationStreamState
}

/** CFG-01/02/03: the right-side (~30% width) config panel — input file/
 * model/output format/output file, the character list with preview
 * controls, and the Generate All/Resume Generation CTA + live batch
 * progress (UI-SPEC Layout, Copywriting Contract). */
export function ConfigPanel({ project, segments, generation }: ConfigPanelProps) {
  const [isStarting, setIsStarting] = useState(false)

  const hasAnyComplete = segments.some((segment) => segment.generation_status === "complete")
  const hasAnyIncomplete = segments.some((segment) => segment.generation_status !== "complete")
  // UI-SPEC Copywriting Contract: relabel to "Resume Generation" only for a
  // mix of complete/pending/error rows, not a fresh (all-pending) project.
  const isResuming = hasAnyComplete && hasAnyIncomplete
  const isRunning = generation.status === "running" || isStarting
  const failedCount = segments.filter((segment) => segment.generation_status === "error").length
  // Open Question 1's resolution: the join blocks (surfaces an error)
  // rather than silently skipping failed segments — no "last good"
  // fallback in v1.
  const joinBlocked = generation.status === "error" && failedCount > 0

  const progressPercent =
    generation.overall && generation.overall.total > 0
      ? Math.round((generation.overall.n / generation.overall.total) * 100)
      : undefined

  async function handleGenerateAll() {
    setIsStarting(true)
    try {
      await runBatchGeneration(project.id)
    } finally {
      setIsStarting(false)
    }
  }

  return (
    <div className="flex flex-col gap-6 rounded-lg bg-secondary p-4">
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">Config</h2>
        <ConfigField label="Input File" value={project.filename} />
        <ConfigField label="Model" value={TTS_MODEL_DISPLAY_NAME} />
        <ConfigField label="Output Format" value={project.output_format.toUpperCase()} />
        <ConfigField
          label="Output File"
          value={
            project.output_path ? (project.output_path.split("/").pop() ?? "") : "Not generated yet"
          }
        />
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">Characters</h2>
        <div className="flex flex-col gap-1">
          {project.characters.map((character) => (
            <CharacterPreviewRow key={character.id} character={character} />
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">Generation</h2>
        <Button
          type="button"
          className="w-full"
          onClick={() => void handleGenerateAll()}
          disabled={isRunning}
        >
          {isRunning ? (
            <>
              <Loader2 className="animate-spin" /> Generating…
            </>
          ) : isResuming ? (
            "Resume Generation"
          ) : (
            "Generate All"
          )}
        </Button>
        {generation.overall && (
          <>
            <Progress value={progressPercent} aria-label="Batch generation progress" />
            <p className="text-xs font-semibold text-muted-foreground">
              {generation.overall.n} of {generation.overall.total} segments
            </p>
          </>
        )}
        {joinBlocked && (
          <div className="rounded-md bg-destructive/10 p-2 text-xs text-destructive">
            <p className="font-semibold">Can&apos;t create the final file yet.</p>
            <p>
              {failedCount} segment{failedCount === 1 ? "" : "s"} failed to generate. Fix or
              regenerate them, then try again.
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
