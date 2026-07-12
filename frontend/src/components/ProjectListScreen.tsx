import { AlertCircle, CheckCircle2, Clock } from "lucide-react"
import { useEffect, useState } from "react"

import { deleteProject, listProjects, type ProjectSummary } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

interface ProjectListScreenProps {
  onOpen: (projectId: string) => void
  onNewProject: () => void
}

// Mirrors SegmentTable's STATUS_BADGE prescriptive icon/color vocabulary
// (UI-SPEC "Generation Status Indicators") at project granularity — no new
// semantic colors invented, only "error" gets destructive red.
const PROJECT_STATUS_BADGE: Record<
  ProjectSummary["status"],
  { label: string; icon: typeof Clock; variant: "outline" | "secondary" | "destructive" }
> = {
  analyzing: { label: "Analyzing…", icon: Clock, variant: "outline" },
  ready: { label: "Ready", icon: CheckCircle2, variant: "secondary" },
  error: { label: "Error", icon: AlertCircle, variant: "destructive" },
}

function ProjectStatusBadge({ status }: { status: ProjectSummary["status"] }) {
  const { label, icon: Icon, variant } = PROJECT_STATUS_BADGE[status]
  return (
    <Badge variant={variant} className="gap-1 whitespace-nowrap">
      <Icon className="size-3" />
      {label}
    </Badge>
  )
}

function formatDate(isoDate: string): string {
  const date = new Date(isoDate)
  if (Number.isNaN(date.getTime())) return isoDate
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

/** PERS-02: the app's landing screen — lists saved projects (filename,
 * date, status badge) with an Open action, plus a persistent New Project
 * CTA (UI-SPEC "Project List" screen). */
export function ProjectListScreen({ onOpen, onNewProject }: ProjectListScreenProps) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null)
  const [error, setError] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(false)
    listProjects()
      .then((result) => {
        if (!cancelled) setProjects(result)
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleDelete(project: ProjectSummary) {
    if (!window.confirm(`Delete "${project.filename}"? This can't be undone.`)) return
    setDeletingId(project.id)
    try {
      await deleteProject(project.id)
      setProjects((current) => current?.filter((p) => p.id !== project.id) ?? current)
    } catch {
      window.alert("Couldn't delete the project. Check the connection and try again.")
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Projects</h1>
        <Button onClick={onNewProject}>New Project</Button>
      </div>

      {error && (
        <p className="text-sm text-destructive" role="alert">
          Couldn&apos;t load your projects. Check the connection and try
          again.
        </p>
      )}

      {!error && projects === null && (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      )}

      {!error && projects !== null && projects.length === 0 && (
        <div className="flex flex-col items-center gap-4 py-12 text-center">
          <h2 className="text-lg font-semibold">No projects yet</h2>
          <p className="text-sm text-muted-foreground">
            Upload a book to create your first project.
          </p>
          <Button onClick={onNewProject}>New Project</Button>
        </div>
      )}

      {!error && projects !== null && projects.length > 0 && (
        <div className="flex flex-col gap-4">
          {projects.map((project) => (
            <Card key={project.id} className="flex-row items-center justify-between px-4">
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-sm font-medium" title={project.filename}>
                  {project.filename}
                </span>
                <span className="text-xs text-muted-foreground">
                  {formatDate(project.created_at)}
                </span>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <ProjectStatusBadge status={project.status} />
                <Button variant="outline" size="sm" onClick={() => onOpen(project.id)}>
                  Open
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  disabled={deletingId === project.id}
                  onClick={() => handleDelete(project)}
                >
                  {deletingId === project.id ? "Deleting…" : "Delete"}
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
