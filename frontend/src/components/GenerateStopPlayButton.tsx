// GEN-09/GEN-10/GEN-11/GEN-12: the single shared generate/stop/play
// control, per 07-UI-SPEC.md Component Contracts §1. Pure presentational —
// it never fetches, polls, or owns generation-in-flight state itself; that
// lives in useGenerateStopPlay, one call per consumer site.
import { Loader2, Pause, Play } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { GspStatus } from "@/hooks/useGenerateStopPlay"

export interface GenerateStopPlayButtonProps {
  status: GspStatus
  /** Only meaningful when status === "ready". */
  isPlaying?: boolean
  /** e.g. generationLocked while status === "idle". */
  disabled?: boolean
  /** → title attribute, e.g. "Another generation is already running." */
  disabledReason?: string
  size?: "sm" | "default"
  className?: string
  /** e.g. "audio for segment 3", "preview for Elena", "the joined output" */
  subjectLabel: string
  onGenerate: () => void
  onStop: () => void
  onTogglePlay: () => void
}

const STATE_CLASSES: Record<GspStatus, string> = {
  idle: "bg-amber-400 text-amber-950 hover:bg-amber-500",
  generating: "bg-red-600 text-white hover:bg-red-700",
  // disabled prop supplies the dimming for "stopping" — same red as generating.
  stopping: "bg-red-600 text-white hover:bg-red-700",
  ready: "bg-green-600 text-white hover:bg-green-700",
}

const STATE_LABEL: Record<GspStatus, string> = {
  idle: "Generate Preview",
  generating: "Stop Generation",
  stopping: "Stopping…",
  // caller flips to "Pause" via isPlaying when status === "ready"
  ready: "Play",
}

export function GenerateStopPlayButton({
  status,
  isPlaying = false,
  disabled = false,
  disabledReason,
  size = "default",
  className,
  subjectLabel,
  onGenerate,
  onStop,
  onTogglePlay,
}: GenerateStopPlayButtonProps) {
  const isDisabled = status === "stopping" || disabled

  function handleClick() {
    if (status === "stopping") return
    if (status === "idle") {
      onGenerate()
    } else if (status === "generating") {
      onStop()
    } else if (status === "ready") {
      onTogglePlay()
    }
  }

  const label =
    status === "ready" && isPlaying ? "Pause" : STATE_LABEL[status]

  const actionWord =
    status === "idle"
      ? "Generate"
      : status === "generating" || status === "stopping"
        ? "Stop generating"
        : isPlaying
          ? "Pause"
          : "Play"

  return (
    <Button
      type="button"
      size={size}
      disabled={isDisabled}
      title={disabledReason}
      onClick={handleClick}
      aria-label={`${actionWord} ${subjectLabel}`}
      className={cn(STATE_CLASSES[status], className)}
    >
      {status === "generating" || status === "stopping" ? (
        <Loader2 className="animate-spin" />
      ) : status === "ready" ? (
        isPlaying ? (
          <Pause />
        ) : (
          <Play />
        )
      ) : null}
      {label}
    </Button>
  )
}
