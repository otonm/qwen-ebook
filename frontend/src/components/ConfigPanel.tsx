import { Loader2, TriangleAlert } from "lucide-react"
import { useRef, useState } from "react"

import {
  cancelBatchGeneration,
  cancelCharacterPreview,
  downloadUrl,
  errorMessage,
  outputUrl,
  patchProjectConfig,
  previewUrl,
  runBatchGeneration,
  setProjectModel,
  triggerCharacterPreview,
  type Character,
  type Project,
  type Segment,
} from "@/api/client"
import { Button } from "@/components/ui/button"
import { GenerateStopPlayButton } from "@/components/GenerateStopPlayButton"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useGenerateStopPlay, type GspStatus } from "@/hooks/useGenerateStopPlay"
import type { GenerationStreamState } from "@/hooks/useGenerationStream"

// CFG-04: verbatim dropdown option labels (UI-SPEC Copywriting Contract) —
// also used to build the D-02 human-readable failure message.
const MODEL_LABELS: Record<string, string> = {
  "1.7b": "Higher quality (1.7B)",
  "0.6b": "Faster (0.6B)",
}

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
  const audioRef = useRef<HTMLAudioElement>(null)
  const hasPreview = Boolean(character.preview_audio_path)

  const { status, error, handleGenerate, handleStop } = useGenerateStopPlay({
    hasAudio: hasPreview,
    isExternallyGenerating: false,
    poll: true,
    onGenerate: () => triggerCharacterPreview(character.id),
    onStop: () => cancelCharacterPreview(character.id),
    onRefresh,
  })

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
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2 rounded-md bg-background px-2 py-1.5">
        <span className="flex-1 truncate text-sm">{character.name}</span>
        <GenerateStopPlayButton
          size="sm"
          status={status}
          isPlaying={isPlaying}
          disabled={generationLocked && status === "idle"}
          disabledReason="Another generation is already running."
          subjectLabel={`preview for ${character.name}`}
          onGenerate={() => void handleGenerate()}
          onStop={() => void handleStop()}
          onTogglePlay={togglePlayback}
        />
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
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
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
 * controls, and the unified Generate/Stop/Play batch button (GEN-11) +
 * live batch progress (UI-SPEC Layout, Copywriting Contract). */
export function ConfigPanel({
  project,
  segments,
  generation,
  onRefresh,
  generationLocked,
}: ConfigPanelProps) {
  const [isStarting, setIsStarting] = useState(false)
  const [isCancelling, setIsCancelling] = useState(false)
  const [batchError, setBatchError] = useState<string | null>(null)
  // GEN-11/D-04: the joined-output hidden <audio> backing the batch
  // button's green "Play" state, mirroring CharacterPreviewRow's
  // isPlaying/audioRef pattern.
  const [isOutputPlaying, setIsOutputPlaying] = useState(false)
  const outputAudioRef = useRef<HTMLAudioElement>(null)
  const [isSwapping, setIsSwapping] = useState(false)
  const [swapError, setSwapError] = useState<string | null>(null)
  const [filenameDraft, setFilenameDraft] = useState(project.output_filename ?? "")
  const [configError, setConfigError] = useState<string | null>(null)
  // D-04 echo: filenameDraft trusts server state, same discipline as the
  // Model Select reverting off project.tts_model — re-seeds during render
  // (React's "adjusting state on prop change" pattern, not a setState-in-
  // effect) after every successful PATCH's onRefresh (sanitization result)
  // and on project swap.
  const [lastSyncedFilename, setLastSyncedFilename] = useState(project.output_filename)
  if (project.output_filename !== lastSyncedFilename) {
    setLastSyncedFilename(project.output_filename)
    setFilenameDraft(project.output_filename ?? "")
  }

  const isBatchRunning = generation.status === "running" || isStarting
  // T-03-29: Generate All must also stay disabled while a per-row generate
  // is in flight, not only during a batch SSE stream — otherwise a
  // per-row-triggered "generating" segment can still be raced by Generate
  // All firing a second batch over the same rows.
  const anyGenerating = segments.some((segment) => segment.generation_status === "generating")
  const isSelfRunning = isBatchRunning || anyGenerating
  const failedCount = segments.filter((segment) => segment.generation_status === "error").length
  // Open Question 1's resolution: the join blocks (surfaces an error)
  // rather than silently skipping failed segments — no "last good"
  // fallback in v1.
  const joinBlocked = generation.status === "error" && failedCount > 0
  const hasOutput = Boolean(project.output_path)
  // D-05/WR-03: the anchor's download attribute must mirror the server's
  // full fallback chain exactly — sanitized output_filename, else the
  // source filename's stem, else "output" — since same-origin browsers
  // honor this attribute over Content-Disposition. `||` (not `??`) is
  // required: the server normalizes a fully-sanitized-away name to NULL,
  // but stays defensive here in case output_filename is ever "".
  const downloadStem =
    project.output_filename || project.filename.replace(/\.[^.]+$/, "") || "output"
  const downloadFilename = `${downloadStem}.${project.output_format}`

  const progressPercent =
    generation.overall && generation.overall.total > 0
      ? Math.round((generation.overall.n / generation.overall.total) * 100)
      : undefined

  async function handleGenerateAll() {
    setIsStarting(true)
    setBatchError(null)
    try {
      const result = await runBatchGeneration(project.id)
      // generation-stream is request-scoped and self-closes after each
      // run's terminal event — a second Generate All click needs a fresh
      // SSE connection or generation.status can never report "running"
      // again, and the button never flips back to red "Stop Generation"
      // even though the backend is genuinely generating.
      generation.restart()
      // IN-03 fix: "busy"/"already_running" means the batch did NOT
      // actually start (something else holds the single global slot) —
      // tell the user why the button spun and reverted instead of leaving
      // them to guess.
      if (result.status === "busy") {
        setBatchError("Another generation is already running — try again shortly.")
      } else if (result.status === "already_running") {
        setBatchError("This project's generation is already running.")
      }
    } catch (err) {
      setBatchError(errorMessage(err, "Couldn't start generation."))
    } finally {
      setIsStarting(false)
    }
  }

  // D-01: fires the explicit load immediately (not deferred to next
  // Generate). D-02: on failure, `project.tts_model` is never touched
  // optimistically — the Select's `value` is server state, so it reverts
  // to whichever model is still actually resident purely by re-rendering
  // off the unchanged `project` prop once `onRefresh` (or just this
  // catch) leaves it alone.
  async function handleModelChange(nextModelId: string) {
    setIsSwapping(true)
    setSwapError(null)
    try {
      await setProjectModel(project.id, nextModelId)
      onRefresh()
    } catch (err) {
      const attemptedLabel = MODEL_LABELS[nextModelId] ?? nextModelId
      const residentLabel = MODEL_LABELS[project.tts_model] ?? project.tts_model
      setSwapError(
        errorMessage(err, `Couldn't switch to ${attemptedLabel}. Still using ${residentLabel}.`)
      )
    } finally {
      setIsSwapping(false)
    }
  }

  // CFG-06/CFG-07: no generation lock claimed here — format/filename are
  // inert config (RESEARCH.md Pattern 4), so this PATCH commits immediately
  // regardless of whether a generation is running.
  async function handleConfigChange(patch: { output_format?: string; output_filename?: string }) {
    setConfigError(null)
    try {
      await patchProjectConfig(project.id, patch)
      onRefresh()
    } catch (err) {
      setConfigError(errorMessage(err, "Couldn't save output settings."))
    }
  }

  // Commits on blur, not per-keystroke, and only when the trimmed draft
  // actually differs from the last-saved value.
  async function handleFilenameBlur() {
    const trimmed = filenameDraft.trim()
    if (trimmed === (project.output_filename ?? "")) return
    await handleConfigChange({ output_filename: trimmed })
  }

  async function handleStop() {
    setIsCancelling(true)
    setBatchError(null)
    try {
      await cancelBatchGeneration(project.id)
      onRefresh()
    } catch (err) {
      setBatchError(errorMessage(err, "Couldn't stop generation."))
    } finally {
      setIsCancelling(false)
    }
  }

  function toggleOutputPlayback() {
    const audio = outputAudioRef.current
    if (!audio) return
    if (isOutputPlaying) {
      audio.pause()
    } else {
      void audio.play()
    }
  }

  // GEN-11/D-04, Pitfall 2 (load-bearing): the batch status derivation must
  // check isSelfRunning BEFORE hasOutput — output_path is never cleared at
  // batch-start (only overwritten on join success), so a re-run of a
  // project that already has output would otherwise show a stale green
  // "Play" while regeneration is actively in flight.
  const batchStatus: GspStatus = isCancelling
    ? "stopping"
    : isSelfRunning
      ? "generating"
      : hasOutput
        ? "ready"
        : "idle"

  return (
    <div className="flex flex-col gap-6 rounded-lg bg-secondary p-4">
      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">Config</h2>
        <ConfigField label="Input File" value={project.filename} />
        <div className="flex flex-col gap-1">
          <span className="text-xs font-semibold text-muted-foreground">Model</span>
          <Select
            value={project.tts_model}
            onValueChange={(value) => void handleModelChange(value)}
            disabled={isSwapping || generationLocked}
          >
            <SelectTrigger
              size="sm"
              aria-label="TTS model"
              className="w-full"
              title={
                generationLocked && !isSwapping
                  ? "Can't switch models while a generation is running."
                  : undefined
              }
            >
              {isSwapping ? (
                <span className="flex items-center gap-1.5">
                  <Loader2 className="size-4 animate-spin" /> Switching model…
                </span>
              ) : (
                <SelectValue />
              )}
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1.7b">Higher quality (1.7B)</SelectItem>
              <SelectItem value="0.6b">Faster (0.6B)</SelectItem>
            </SelectContent>
          </Select>
          {project.tts_model === "0.6b" && (
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <TriangleAlert className="size-3 shrink-0" />
              Faster (0.6B) doesn&apos;t support custom voice instructions — segments use each
              character&apos;s base preset voice only.
            </p>
          )}
          {swapError && (
            <p className="text-xs text-destructive" role="alert">
              {swapError}
            </p>
          )}
        </div>
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
        <div className="flex flex-col gap-1">
          <span className="text-xs font-semibold text-muted-foreground">Output Filename</span>
          <div className="flex items-center gap-1">
            <Input
              aria-label="Output filename"
              value={filenameDraft}
              onChange={(e) => setFilenameDraft(e.target.value)}
              onBlur={() => void handleFilenameBlur()}
              placeholder={project.filename.replace(/\.[^.]+$/, "")}
              className="flex-1"
            />
            <span className="text-sm text-muted-foreground">.{project.output_format}</span>
          </div>
          {configError && (
            <p className="text-xs text-destructive" role="alert">
              {configError}
            </p>
          )}
        </div>
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
        <GenerateStopPlayButton
          size="default"
          className="w-full"
          status={batchStatus}
          isPlaying={isOutputPlaying}
          disabled={generationLocked && batchStatus === "idle"}
          disabledReason="Another generation is already running."
          subjectLabel="the joined output"
          idleLabel="Generate All"
          onGenerate={() => void handleGenerateAll()}
          onStop={() => void handleStop()}
          onTogglePlay={toggleOutputPlayback}
        />
        {hasOutput && (
          <audio
            ref={outputAudioRef}
            src={outputUrl(project.id)}
            onPlay={() => setIsOutputPlaying(true)}
            onPause={() => setIsOutputPlaying(false)}
            onEnded={() => setIsOutputPlaying(false)}
          />
        )}
        {isBatchRunning && (
          <p className="text-xs text-muted-foreground">
            Stop interrupts the segment currently generating immediately.
          </p>
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
        {batchError && (
          <p className="text-xs text-destructive" role="alert">
            {batchError}
          </p>
        )}
        <Button
          asChild={hasOutput}
          type="button"
          variant="default"
          className="w-full"
          disabled={!hasOutput}
          title={hasOutput ? undefined : "Generate All first — nothing to download yet."}
        >
          {hasOutput ? (
            <a href={downloadUrl(project.id)} download={downloadFilename}>
              Download
            </a>
          ) : (
            "Download"
          )}
        </Button>
      </section>
    </div>
  )
}
