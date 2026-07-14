import { useCallback, useEffect, useMemo, useState } from "react"

import { errorMessage, getProject, type Project, type Segment } from "@/api/client"
import { ConfigPanel } from "@/components/ConfigPanel"
import { SegmentTable } from "@/components/SegmentTable"
import { Button } from "@/components/ui/button"
import { useGenerationLock } from "@/hooks/useGenerationLock"
import { useGenerationStream } from "@/hooks/useGenerationStream"

interface ProjectScreenProps {
  projectId: string
}

/** CFG-01/02/03, TBL-01..04: the main editing screen — 70% editable
 * segment table / 30% config panel split (UI-SPEC Layout). Live per-segment
 * status from useGenerationStream is merged into the segments handed to
 * SegmentTable so a batch run's progress shows up in the table's status
 * badges without SegmentTable needing to know about the SSE stream. */
export function ProjectScreen({ projectId }: ProjectScreenProps) {
  const [project, setProject] = useState<Project | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)
  const generation = useGenerationStream(projectId)
  // Global (app-wide, not just this project) single-flight signal — only
  // one generation of any kind may be in flight at a time, so both the
  // table's per-row buttons and the config panel's controls disable
  // whenever ANY generation elsewhere holds it.
  const generationLocked = useGenerationLock()

  const refetch = useCallback(() => {
    // WR-07 fix: a transient failure (network blip, backend restart
    // mid-request) must not discard an already-loaded project — refetch()
    // runs after every generate/cancel/reassign action, so nulling project
    // here would throw the user back to the full-page "Loading…" state
    // for no reason the next successful poll wouldn't have recovered from
    // on its own. Keep the last-known project and surface a transient
    // error banner instead.
    getProject(projectId)
      .then((p) => {
        setProject(p)
        setFetchError(null)
      })
      .catch((err: unknown) => setFetchError(errorMessage(err, "Couldn't refresh the project.")))
  }, [projectId])

  useEffect(() => {
    refetch()
  }, [refetch])

  // The SSE payload only carries {segment_id, n, total, status} — once a
  // run reaches a terminal state, re-fetch so audio_path/output_path (not
  // pushed over the stream) land in `project`.
  useEffect(() => {
    if (generation.status === "ready" || generation.status === "error") {
      refetch()
    }
  }, [generation.status, refetch])

  function handleSegmentChange(updated: Segment) {
    setProject((prev) =>
      prev
        ? {
            ...prev,
            segments: prev.segments.map((segment) =>
              segment.id === updated.id ? updated : segment
            ),
          }
        : prev
    )
  }

  const liveSegments = useMemo(() => {
    if (!project) return []
    // WR-05 fix: segmentStatuses is only reset when a NEW SSE connection
    // opens (restart(), i.e. a fresh Generate All click) — it is never
    // cleared when a run's terminal event arrives, nor when a segment is
    // locally patched. Trusting it once a batch is no longer "running"
    // let a stale "complete" overlay override a segment that was since
    // edited (patchSegment correctly flipped it back to "pending" in
    // project.segments, but the badge kept showing the old live status).
    // The freshly-fetched project.segments is always the source of truth
    // once nothing is actively streaming.
    if (generation.status !== "running") return project.segments
    return project.segments.map((segment) => {
      const liveStatus = generation.segmentStatuses[segment.id]
      return liveStatus && liveStatus !== segment.generation_status
        ? { ...segment, generation_status: liveStatus }
        : segment
    })
  }, [project, generation.status, generation.segmentStatuses])

  if (!project) {
    return (
      <div className="mx-auto flex min-h-svh max-w-2xl flex-col items-center justify-center gap-2 p-6 text-center">
        <p className="text-sm text-muted-foreground">
          {fetchError ? "Couldn't load this project." : "Loading project…"}
        </p>
        {fetchError && (
          <>
            <p className="text-sm text-destructive" role="alert">
              {fetchError}
            </p>
            <Button type="button" size="sm" variant="outline" onClick={refetch}>
              Retry
            </Button>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">{project.filename}</h1>
      {fetchError && (
        <p className="text-sm text-destructive" role="alert">
          {fetchError} (showing last-loaded data)
        </p>
      )}
      <div className="flex flex-col gap-8 xl:flex-row">
        <div className="xl:w-[70%]">
          <SegmentTable
            segments={liveSegments}
            characters={project.characters}
            onSegmentChange={handleSegmentChange}
            generationLocked={generationLocked}
            onRefresh={refetch}
          />
        </div>
        <div className="xl:w-[30%]">
          <ConfigPanel
            project={project}
            segments={liveSegments}
            generation={generation}
            onRefresh={refetch}
            generationLocked={generationLocked}
          />
        </div>
      </div>
    </div>
  )
}
