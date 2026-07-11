import { useCallback, useEffect, useState } from "react"

import { getProject, type Project, type Segment } from "@/api/client"
import { SegmentTable } from "@/components/SegmentTable"

interface ProjectScreenProps {
  projectId: string
}

/** CFG-01/02/03, TBL-01..04: the main editing screen — 70% editable
 * segment table / 30% config panel split (UI-SPEC Layout). The config
 * panel (input file/model/output format, character list, live progress)
 * is plan 03-03's scope; this plan only reserves and labels the region so
 * the split is visible from 03-01 onward. */
export function ProjectScreen({ projectId }: ProjectScreenProps) {
  const [project, setProject] = useState<Project | null>(null)

  const refetch = useCallback(() => {
    getProject(projectId).then(setProject).catch(() => setProject(null))
  }, [projectId])

  useEffect(() => {
    refetch()
  }, [refetch])

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
            segments={project.segments}
            characters={project.characters}
            onSegmentChange={handleSegmentChange}
          />
        </div>
        <div className="rounded-lg bg-secondary p-4 xl:w-[30%]">
          <p className="text-xs font-semibold text-muted-foreground">
            Config panel — coming in a later plan.
          </p>
        </div>
      </div>
    </div>
  )
}
