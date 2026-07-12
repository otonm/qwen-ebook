import { useEffect, useRef, useState } from "react"

import {
  getProject,
  type GenerationProgress,
  type GenerationStatus,
  type Segment,
} from "@/api/client"

export type GenerationStreamStatus = "idle" | "running" | "ready" | "error"

export interface GenerationStreamState {
  status: GenerationStreamStatus
  progress: GenerationProgress | null
  /** overall n/total from the latest progress event — every event in a run
   * carries the same total, so this is the batch's overall position. */
  overall: { n: number; total: number } | null
  /** Live per-segment status, keyed by segment_id, accumulated across every
   * "progress" event seen so far this run. */
  segmentStatuses: Record<string, GenerationStatus>
  errorDetail: string | null
}

function initialState(): GenerationStreamState {
  return { status: "idle", progress: null, overall: null, segmentStatuses: {}, errorDetail: null }
}

/** CFG-03: EventSource wrapper over /projects/{id}/generation-stream (SSE)
 * — mirrors useAnalysisStream's lifecycle (RESEARCH.md Pattern 5's event
 * schema: {segment_id, n, total, status} instead of analysis's
 * {stage, n, total}). */
export function useGenerationStream(projectId: string | null): GenerationStreamState {
  const [state, setState] = useState<GenerationStreamState>(initialState)
  const sourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!projectId) return undefined

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState(initialState())

    const source = new EventSource(`/projects/${projectId}/generation-stream`)
    sourceRef.current = source

    source.addEventListener("progress", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as GenerationProgress
      setState((prev) => ({
        ...prev,
        status: "running",
        progress: payload,
        overall: { n: payload.n, total: payload.total },
        segmentStatuses: { ...prev.segmentStatuses, [payload.segment_id]: payload.status },
      }))
    })

    source.addEventListener("done", (event) => {
      const messageEvent = event as MessageEvent
      const payload = messageEvent.data
        ? (JSON.parse(messageEvent.data) as { status: string })
        : { status: "idle" }
      setState((prev) => ({ ...prev, status: payload.status === "ready" ? "ready" : "idle" }))
      source.close()
    })

    source.addEventListener("error", (event) => {
      const messageEvent = event as MessageEvent
      if (!messageEvent.data) {
        // Native EventSource connection-drop (no server-sent payload) — a
        // transient network hiccup, not a real generation failure.
        return
      }
      const detail = JSON.parse(messageEvent.data)?.detail ?? "Generation failed"
      setState((prev) => ({ ...prev, status: "error", errorDetail: detail }))
      source.close()
    })

    return () => {
      source.close()
      sourceRef.current = null
    }
  }, [projectId])

  return state
}

/** Re-fetch the current segments (e.g. to pick up final audio_path/
 * output_path once a run reaches "ready"/"error") without reopening the SSE
 * subscription — same shape as useAnalysisStream's refreshProject. */
export async function refreshSegments(projectId: string): Promise<Segment[]> {
  const project = await getProject(projectId)
  return project.segments
}
