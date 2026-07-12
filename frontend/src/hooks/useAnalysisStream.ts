import { useEffect, useRef, useState } from "react"

import { getProject, type Character, type Segment } from "@/api/client"

export type AnalysisStatus = "analyzing" | "ready" | "error"

export interface AnalysisProgress {
  stage: string
  n?: number
  total?: number
}

export interface AnalysisStreamState {
  status: AnalysisStatus
  progress: AnalysisProgress | null
  cast: Character[]
  segments: Segment[]
  errorDetail: string | null
}

/** WIZ-01: EventSource wrapper over /projects/{id}/analysis-stream (SSE) —
 * updates on "progress", fetches the final project and closes on "done",
 * surfaces the error state on "error" (RESEARCH.md Pattern 2). */
function initialState(): AnalysisStreamState {
  return {
    status: "analyzing",
    progress: null,
    cast: [],
    segments: [],
    errorDetail: null,
  }
}

export function useAnalysisStream(projectId: string | null): AnalysisStreamState {
  const [state, setState] = useState<AnalysisStreamState>(initialState)
  const sourceRef = useRef<EventSource | null>(null)
  // T-03-23/T-03-24: guards a single in-flight confirmation fetch per error
  // burst so a no-data EventSource error probes the project at most once
  // instead of firing on every reconnect attempt.
  const probingRef = useRef(false)

  useEffect(() => {
    if (!projectId) return undefined

    // Reset before opening the new subscription — react.dev's own
    // data-fetching-effect example resets state at the top of the effect
    // body before starting the new fetch/subscription; the stricter
    // set-state-in-effect lint rule flags this canonical pattern anyway.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState(initialState())
    probingRef.current = false

    const source = new EventSource(`/projects/${projectId}/analysis-stream`)
    sourceRef.current = source

    source.addEventListener("progress", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as AnalysisProgress
      setState((prev) => ({ ...prev, progress: payload }))
    })

    source.addEventListener("done", () => {
      getProject(projectId)
        .then((project) => {
          setState((prev) => ({
            ...prev,
            status: "ready",
            cast: project.characters,
            segments: project.segments,
          }))
        })
        .catch((err: Error) => {
          setState((prev) => ({ ...prev, status: "error", errorDetail: err.message }))
        })
        .finally(() => source.close())
    })

    source.addEventListener("error", (event) => {
      const messageEvent = event as MessageEvent
      if (!messageEvent.data) {
        // Native EventSource connection-drop (no server-sent payload) — could
        // be a transient network hiccup (let EventSource reconnect) or a
        // permanent 404 for a stale/deleted projectId (reconnects forever
        // otherwise). Disambiguate with a single guarded confirmation fetch.
        if (probingRef.current) return
        probingRef.current = true
        getProject(projectId)
          .then(() => {
            // Project still exists — genuinely transient, keep reconnecting.
            probingRef.current = false
          })
          .catch(() => {
            // Project is gone — permanent failure, stop retrying and surface
            // the existing error/recover UI (App.tsx's ErrorScreen).
            setState((prev) => ({
              ...prev,
              status: "error",
              errorDetail: "This project no longer exists.",
            }))
            source.close()
          })
        return
      }
      const detail = JSON.parse(messageEvent.data)?.detail ?? "Analysis failed"
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

/** Re-fetch the current cast/segments (e.g. after a PATCH/merge) without
 * reopening the SSE stream — used by the wizard once analysis is "ready". */
export async function refreshProject(
  projectId: string
): Promise<{ cast: Character[]; segments: Segment[] }> {
  const project = await getProject(projectId)
  return { cast: project.characters, segments: project.segments }
}
