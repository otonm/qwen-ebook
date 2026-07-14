import { Loader2, Pause, Play } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import {
  cancelBatchGeneration,
  cancelCharacterPreview,
  previewUrl,
  runBatchGeneration,
  triggerCharacterPreview,
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

/** CFG-02/CFG-03: reuses CharacterCard's play/pause preview pattern (a
 * hidden <audio> + isPlaying toggle) for a compact, read-only row — this
 * panel only previews voices, editing/merging stays the wizard's job. A
 * character whose voice was never (re)saved via PATCH has a permanently
 * null preview_audio_path — show why the Play button is disabled and offer
 * an on-demand "Generate preview" trigger. */
function CharacterPreviewRow({
  character,
  onRefresh,
  generationLocked,
}: {
  character: Character
  onRefresh: () => void
  generationLocked: boolean
}) {
  const [isPlaying, setIsPlaying] = useState(false)
  const [isTriggeringPreview, setIsTriggeringPreview] = useState(false)
  const [isStoppingPreview, setIsStoppingPreview] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)
  const hasPreview = Boolean(character.preview_audio_path)
  // A parent refresh landing the new preview_audio_path is what ends the
  // "generating" state — hasPreview flipping true unmounts the trigger
  // button below, so isTriggeringPreview never needs an explicit reset.
  const isGeneratingPreview = isTriggeringPreview && !hasPreview

  // Preview generation is a background task (no SSE for it) — poll
  // steadily after triggering so Play enables once it lands, without the
  // user needing to manually refresh. 60s ceiling (not a short burst):
  // real GPU synthesis can run well past a few seconds on a cold/idle-GPU
  // downclock-recovery spike (tts_service/model.py's keepalive_matmul; a
  // fresh TTS container's very first request measured ~38s in
  // production), so a failed generation is the only thing this ceiling
  // needs to guard against, not a normal slow one.
  useEffect(() => {
    if (!isGeneratingPreview) return undefined
    const interval = setInterval(onRefresh, 1500)
    const timeout = setTimeout(() => clearInterval(interval), 60000)
    return () => {
      clearInterval(interval)
      clearTimeout(timeout)
    }
  }, [isGeneratingPreview, onRefresh])

  function togglePlayback() {
    const audio = audioRef.current
    if (!audio) return
    if (isPlaying) {
      audio.pause()
    } else {
      void audio.play()
    }
  }

  async function handleGeneratePreview() {
    setIsTriggeringPreview(true)
    try {
      await triggerCharacterPreview(character.id)
      onRefresh()
    } catch {
      setIsTriggeringPreview(false)
    }
  }

  async function handleStopPreview() {
    setIsStoppingPreview(true)
    try {
      // cancelCharacterPreview's await only resolves once the backend has
      // genuinely finished the underlying call and released the lock
      // (04-03) — that confirmed-stopped signal is what lets us clear
      // local state honestly (D-03/D-05), not an optimistic guess.
      await cancelCharacterPreview(character.id)
    } finally {
      setIsTriggeringPreview(false)
      setIsStoppingPreview(false)
      onRefresh()
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
        title={hasPreview ? undefined : "No preview generated yet"}
        aria-label={
          isPlaying ? `Pause preview for ${character.name}` : `Play preview for ${character.name}`
        }
      >
        {isPlaying ? <Pause /> : <Play />}
      </Button>
      <span className="flex-1 truncate text-sm">{character.name}</span>
      {!hasPreview && (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={isGeneratingPreview || isStoppingPreview || generationLocked}
          onClick={() => void handleGeneratePreview()}
        >
          {isGeneratingPreview ? (
            <Loader2 className="size-3 animate-spin" />
          ) : (
            "Generate preview"
          )}
        </Button>
      )}
      {isGeneratingPreview && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={isStoppingPreview}
          onClick={() => void handleStopPreview()}
          aria-label={`Stop generating preview for ${character.name}`}
        >
          {isStoppingPreview ? "Stopping…" : "Stop"}
        </Button>
      )}
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
  onRefresh: () => void
  generationLocked: boolean
}

/** CFG-01/02/03: the right-side (~30% width) config panel — input file/
 * model/output format/output file, the character list with preview
 * controls, and the Generate All/Resume Generation CTA + live batch
 * progress (UI-SPEC Layout, Copywriting Contract). */
export function ConfigPanel({
  project,
  segments,
  generation,
  onRefresh,
  generationLocked,
}: ConfigPanelProps) {
  const [isStarting, setIsStarting] = useState(false)
  const [isCancelling, setIsCancelling] = useState(false)

  const hasAnyComplete = segments.some((segment) => segment.generation_status === "complete")
  const hasAnyIncomplete = segments.some((segment) => segment.generation_status !== "complete")
  // UI-SPEC Copywriting Contract: relabel to "Resume Generation" only for a
  // mix of complete/pending/error rows, not a fresh (all-pending) project.
  const isResuming = hasAnyComplete && hasAnyIncomplete
  const isBatchRunning = generation.status === "running" || isStarting
  // T-03-29: Generate All must also stay disabled while a per-row generate
  // is in flight, not only during a batch SSE stream — otherwise a
  // per-row-triggered "generating" segment can still be raced by Generate
  // All firing a second batch over the same rows.
  const anyGenerating = segments.some((segment) => segment.generation_status === "generating")
  const isSelfRunning = isBatchRunning || anyGenerating
  // generationLocked extends the disabled (not the "Generating…" label)
  // state to the app-wide backend lock, covering a character preview or a
  // batch running in a different project too (segment status alone can't
  // see those) — this button isn't itself running, so it shouldn't claim
  // to be.
  const isRunning = isSelfRunning || generationLocked
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
      // generation-stream is request-scoped and self-closes after each
      // run's terminal event — a second Generate All click needs a fresh
      // SSE connection or generation.status can never report "running"
      // again, and the Stop button (gated on isBatchRunning) never
      // reappears even though the backend is genuinely generating.
      generation.restart()
    } finally {
      setIsStarting(false)
    }
  }

  async function handleStop() {
    setIsCancelling(true)
    try {
      await cancelBatchGeneration(project.id)
      onRefresh()
    } finally {
      setIsCancelling(false)
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
            <CharacterPreviewRow
              key={character.id}
              character={character}
              onRefresh={onRefresh}
              generationLocked={generationLocked}
            />
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
          {isSelfRunning ? (
            <>
              <Loader2 className="animate-spin" /> Generating…
            </>
          ) : generationLocked ? (
            "Generation in progress…"
          ) : isResuming ? (
            "Resume Generation"
          ) : (
            "Generate All"
          )}
        </Button>
        {isBatchRunning && (
          <div className="flex flex-col gap-1">
            <Button
              type="button"
              variant="outline"
              className="w-full"
              disabled={isCancelling}
              onClick={() => void handleStop()}
            >
              {isCancelling ? (
                <>
                  <Loader2 className="animate-spin" /> Stopping…
                </>
              ) : (
                "Stop"
              )}
            </Button>
            <p className="text-xs text-muted-foreground">
              Stop interrupts the segment currently generating immediately.
            </p>
          </div>
        )}
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
