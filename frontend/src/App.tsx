import { useState } from "react"

import { CastWizard } from "@/components/CastWizard"
import { ProjectListScreen } from "@/components/ProjectListScreen"
import { ProjectScreen } from "@/components/ProjectScreen"
import { UploadScreen } from "@/components/UploadScreen"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { useAnalysisStream } from "@/hooks/useAnalysisStream"

function progressLabel(progress: { stage: string; n?: number; total?: number } | null) {
  if (!progress) return "Starting analysis…"
  if (progress.stage === "chunk" && progress.n && progress.total) {
    return `Analyzing chunk ${progress.n} of ${progress.total}`
  }
  if (progress.stage === "estimating") return "Estimating text length…"
  return "Analyzing…"
}

function progressPercent(progress: { n?: number; total?: number } | null) {
  if (!progress?.n || !progress.total) return undefined
  return Math.round((progress.n / progress.total) * 100)
}

function AnalyzingScreen({
  progress,
}: {
  progress: { stage: string; n?: number; total?: number } | null
}) {
  return (
    <div className="mx-auto flex min-h-svh max-w-2xl flex-col justify-center gap-6 p-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold">Analyzing your book…</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Detecting characters and splitting text into segments. This can
          take a minute for longer books.
        </p>
      </div>
      <Progress value={progressPercent(progress)} aria-label={progressLabel(progress)} />
      <p className="text-center text-xs font-semibold text-muted-foreground">
        {progressLabel(progress)}
      </p>
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    </div>
  )
}

function ErrorScreen({
  detail,
  onRetry,
}: {
  detail: string | null
  onRetry: () => void
}) {
  return (
    <div className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center gap-4 p-6 text-center">
      <h1 className="text-2xl font-semibold">Couldn&apos;t analyze this file.</h1>
      <p className="text-sm text-muted-foreground">
        {detail || "The analysis service didn't respond — try again."}
      </p>
      <p className="text-sm text-muted-foreground">Fix the file and upload again.</p>
      <button
        type="button"
        onClick={onRetry}
        className="text-sm font-semibold text-primary underline-offset-4 hover:underline"
      >
        Upload another file
      </button>
    </div>
  )
}

// Single-slot persistence for "the project you're currently working on" —
// this app has no project list/switcher UI, just one wizard in flight at a
// time, so a single localStorage key is enough to survive a page refresh.
const PROJECT_ID_STORAGE_KEY = "qwen-ebook:projectId"

// Post-analysis view toggle: the segment table (default landing spot once
// a project is "ready") vs. the cast-review wizard, reachable via a
// persistent header link either way (CONTEXT.md D-04 — exact navigation is
// Claude's discretion).
type ReadyView = "table" | "wizard"

// PERS-02 (UI-SPEC "Screens"): with no active project, the landing area is
// either the project list (root/default) or the upload flow (reached via
// the list's "New Project" CTA) — a separate, purely-in-memory toggle from
// `projectId`/localStorage, since neither state should persist across a
// refresh (refreshing mid-upload should land back on the list, not resume
// the upload form).
type LandingView = "list" | "upload"

export function App() {
  const [projectId, setProjectIdState] = useState<string | null>(() =>
    localStorage.getItem(PROJECT_ID_STORAGE_KEY)
  )
  const [readyView, setReadyView] = useState<ReadyView>("table")
  const [landingView, setLandingView] = useState<LandingView>("list")

  function setProjectId(id: string | null) {
    if (id) {
      localStorage.setItem(PROJECT_ID_STORAGE_KEY, id)
    } else {
      localStorage.removeItem(PROJECT_ID_STORAGE_KEY)
    }
    setReadyView("table")
    setLandingView("list")
    setProjectIdState(id)
  }

  const stream = useAnalysisStream(projectId)

  // PERS-01: every edit already commits immediately via PATCH endpoints
  // (patchCharacter/patchSegment/bulkReassignSegments) the moment a field
  // blurs or an action fires — there is no separate save mechanism to add,
  // autosave already holds by construction.
  if (!projectId) {
    if (landingView === "upload") {
      return <UploadScreen onUploaded={setProjectId} />
    }
    return (
      <ProjectListScreen
        onOpen={setProjectId}
        onNewProject={() => setLandingView("upload")}
      />
    )
  }

  if (stream.status === "error") {
    return (
      <ErrorScreen detail={stream.errorDetail} onRetry={() => setProjectId(null)} />
    )
  }

  if (stream.status === "analyzing") {
    return <AnalyzingScreen progress={stream.progress} />
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="mx-auto flex w-full max-w-[1600px] items-center justify-between px-6 pt-6">
        <button
          type="button"
          onClick={() => setProjectId(null)}
          className="text-sm font-semibold text-primary underline-offset-4 hover:underline"
        >
          ← Projects
        </button>
        <button
          type="button"
          onClick={() => setReadyView(readyView === "table" ? "wizard" : "table")}
          className="text-sm font-semibold text-primary underline-offset-4 hover:underline"
        >
          {readyView === "table" ? "Review cast →" : "← Back to segment table"}
        </button>
      </div>
      {readyView === "wizard" ? (
        <CastWizard
          projectId={projectId}
          initialCast={stream.cast}
          initialSegments={stream.segments}
        />
      ) : (
        <ProjectScreen projectId={projectId} />
      )}
    </div>
  )
}

export default App
