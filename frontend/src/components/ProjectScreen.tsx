import { useCallback, useEffect, useMemo, useState } from "react"

import { getProject, type Project, type Segment } from "@/api/client"
import { ConfigPanel } from "@/components/ConfigPanel"
import { SegmentTable } from "@/components/SegmentTable"
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
  const generation = useGenerationStream(projectId)

  const refetch = useCallback(() => {
    getProject(projectId).then(setProject).catch(() => setProject(null))
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
    if (Object.keys(generation.segmentStatuses).length === 0) return project.segments
    return project.segments.map((segment) => {
      const liveStatus = generation.segmentStatuses[segment.id]
      return liveStatus && liveStatus !== segment.generation_status
        ? { ...segment, generation_status: liveStatus }
        : segment
    })
  }, [project, generation.segmentStatuses])

  if (!project) {
    return (
      <div className="mx-auto flex min-h-svh max-w-2xl items-center justify-center p-6">
        <p className="text-sm text-muted-foreground">Loading project…</p>
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">{project.filename}</h1>
      <div className="flex flex-col gap-8 xl:flex-row">
        <div className="xl:w-[70%]">
          <SegmentTable
            segments={liveSegments}
            characters={project.characters}
            onSegmentChange={handleSegmentChange}
          />
        </div>
        <div className="xl:w-[30%]">
          <ConfigPanel
            project={project}
            segments={liveSegments}
            generation={generation}
            onRefresh={refetch}
          />
        </div>
      </div>
    </div>
  )
}
