// Typed fetch wrappers for the backend's /projects, /characters, /voices
// endpoints (backend/app/main.py). Same-origin via the Vite dev proxy
// (vite.config.ts) — no base URL needed.

// WR-04 fix: the backend's tts_client.py synthesize() allows up to 300s
// (httpx.Timeout read=300.0) for a single real GPU synth call — poll
// ceilings for a triggered generation/preview must stay comfortably above
// that or a legitimately slow (not failed) call gets abandoned mid-poll,
// leaving the UI stuck on "Generating…" forever with nothing left to
// refresh it. 330s gives a safety margin over the backend's own timeout.
export const GENERATION_POLL_CEILING_MS = 330_000

/** Shared error-message extraction for the inline `role="alert"` error
 * pattern used across UploadScreen/ProjectListScreen/ConfigPanel/
 * SegmentTable/ProjectScreen (WR-06/WR-07): prefer a real Error's message,
 * fall back to a caller-supplied default for non-Error rejections. */
export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback
}

export interface Character {
  id: string
  name: string
  description: string
  is_narrator: boolean
  voice_preset: string | null
  voice_instructions: string
  preview_audio_path: string | null
}

export type GenerationStatus = "pending" | "queued" | "generating" | "complete" | "error"

export interface Segment {
  id: string
  order: number
  character_id: string
  character_name: string | null
  text: string
  voice_instructions: string
  generation_status: GenerationStatus
  generation_error: string | null
  audio_path: string | null
}

export interface Project {
  id: string
  filename: string
  status: "analyzing" | "ready" | "error"
  error_detail: string | null
  // CFG-01: set once the whole-project batch join (plan 03-03) completes;
  // output_format is a fixed server setting, not a per-project choice.
  output_path: string | null
  output_format: string
  // CFG-04: per-project source of truth for which TTS checkpoint is
  // resident ("1.7b" | "0.6b") — server state, so a failed swap (D-02)
  // reverts here automatically on refetch rather than needing local
  // optimistic-state rollback.
  tts_model: string
  characters: Character[]
  segments: Segment[]
}

// PERS-02: thin row for the project list/landing screen — id/filename/
// status/created_at only, no character/segment payload.
export interface ProjectSummary {
  id: string
  filename: string
  status: "analyzing" | "ready" | "error"
  created_at: string
}

export interface GenerationProgress {
  segment_id: string
  n: number
  total: number
  status: GenerationStatus
}

export interface VoicePreset {
  name: string
  label: string
}

export interface GenerationLockStatus {
  active: boolean
}

export interface CharacterPatch {
  name?: string
  description?: string
  voice_preset?: string
  voice_instructions?: string
}

export interface SegmentPatch {
  character_id?: string
  voice_instructions?: string
  text?: string
}

export interface MergeUndoSnapshot {
  character: {
    id: string
    project_id: string
    name: string
    description: string
    is_narrator: boolean
    voice_preset: string | null
    voice_instructions: string
    voice_version: number
    had_preview: boolean
  }
  segment_ids: string[]
}

async function parseJsonOrThrow(response: Response) {
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body?.detail)
      .catch(() => undefined)
    throw new Error(detail || `Request failed with ${response.status}`)
  }
  return response.json()
}

export async function createProject(
  file: File
): Promise<{ id: string; status: string }> {
  const formData = new FormData()
  formData.append("file", file)
  const response = await fetch("/projects", { method: "POST", body: formData })
  return parseJsonOrThrow(response)
}

/** PERS-02: the project list/landing screen's data source. */
export async function listProjects(): Promise<ProjectSummary[]> {
  const response = await fetch("/projects")
  return parseJsonOrThrow(response)
}

export async function getProject(id: string): Promise<Project> {
  const response = await fetch(`/projects/${id}`)
  return parseJsonOrThrow(response)
}

export async function deleteProject(id: string): Promise<void> {
  const response = await fetch(`/projects/${id}`, { method: "DELETE" })
  if (!response.ok) {
    throw new Error(`Request failed with ${response.status}`)
  }
}

export async function patchCharacter(
  id: string,
  body: CharacterPatch
): Promise<Character> {
  const response = await fetch(`/characters/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  return parseJsonOrThrow(response)
}

export async function mergeCharacter(
  sourceId: string,
  targetId: string
): Promise<Character & { undo: MergeUndoSnapshot }> {
  const response = await fetch(`/characters/${sourceId}/merge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_id: targetId }),
  })
  return parseJsonOrThrow(response)
}

export async function undoMergeCharacter(
  snapshot: MergeUndoSnapshot
): Promise<Character> {
  const response = await fetch("/characters/undo-merge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(snapshot),
  })
  return parseJsonOrThrow(response)
}

export async function getVoices(): Promise<VoicePreset[]> {
  const response = await fetch("/voices")
  return parseJsonOrThrow(response)
}

/** Global single-flight generation lock — true while ANY generation
 * (a character preview, a per-row segment, or a batch run, in any
 * project) is in flight. Polled to disable every OTHER
 * generation-triggering control while one is active. */
export async function getGenerationLockStatus(): Promise<GenerationLockStatus> {
  const response = await fetch("/generation-status")
  return parseJsonOrThrow(response)
}

export function previewUrl(characterId: string): string {
  return `/characters/${characterId}/preview.wav`
}

export async function patchSegment(id: string, body: SegmentPatch): Promise<Segment> {
  const response = await fetch(`/segments/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  return parseJsonOrThrow(response)
}

/** GEN-06: fires the segment's generation and returns immediately (202
 * {"status": "generating"}) — matching 04-03's async contract. No segment
 * body comes back; the caller must refetch/poll (e.g. onRefresh) to pick up
 * the resulting audio_path/generation_status once the background task
 * completes, mirroring triggerCharacterPreview. */
export async function generateSegment(id: string): Promise<{ status: string }> {
  const response = await fetch(`/segments/${id}/generate`, { method: "POST" })
  return parseJsonOrThrow(response)
}

/** GEN-06: true-kill cancel for a single in-flight segment generation.
 * Returns {"status": "cancelled"} or {"status": "not_running"} if nothing
 * was in flight for this segment. */
export async function cancelSegmentGeneration(id: string): Promise<{ status: string }> {
  const response = await fetch(`/segments/${id}/generate/cancel`, { method: "POST" })
  return parseJsonOrThrow(response)
}

/** GEN-07: true-kill cancel for a single in-flight character preview
 * generation. Returns {"status": "cancelled"} or {"status": "not_running"}
 * if nothing was in flight for this character. */
export async function cancelCharacterPreview(id: string): Promise<{ status: string }> {
  const response = await fetch(`/characters/${id}/preview/cancel`, { method: "POST" })
  return parseJsonOrThrow(response)
}

export function segmentAudioUrl(id: string): string {
  return `/segments/${id}/audio.wav`
}

export async function bulkReassignSegments(
  segmentIds: string[],
  characterId: string
): Promise<{ updated: number }> {
  const response = await fetch("/segments/bulk-reassign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ segment_ids: segmentIds, character_id: characterId }),
  })
  return parseJsonOrThrow(response)
}

/** CFG-03/GEN-05: kick off (or resume) the whole-project batch generation
 * run. Fires immediately (202) — progress is pushed over
 * /projects/{id}/generation-stream, consumed by useGenerationStream. */
export async function runBatchGeneration(projectId: string): Promise<{ status: string }> {
  const response = await fetch(`/projects/${projectId}/generate`, { method: "POST" })
  return parseJsonOrThrow(response)
}

/** GEN-05: cancel a running batch generation. Returns {"status": "cancelled"}
 * or {"status": "not_running"} if nothing was in flight for this project. */
export async function cancelBatchGeneration(projectId: string): Promise<{ status: string }> {
  const response = await fetch(`/projects/${projectId}/generate/cancel`, { method: "POST" })
  return parseJsonOrThrow(response)
}

/** CFG-04/D-01: explicit-load model swap trigger — POSTs the chosen
 * model_id, fires the swap immediately (blocking for the request's
 * duration, tens of seconds), and returns the updated Project (with
 * every segment/character preview invalidated per D-05/D-06 on success).
 * A failed swap raises — the caller's `project.tts_model` (server state)
 * stays on whichever model is still actually resident (D-02), never left
 * optimistically on the failed target. */
export async function setProjectModel(id: string, model_id: string): Promise<Project> {
  const response = await fetch(`/projects/${id}/model`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id }),
  })
  return parseJsonOrThrow(response)
}

/** CFG-03: on-demand character preview trigger for a character whose voice
 * was never (re)saved via PATCH /characters/{id}, so preview_audio_path is
 * still null. Returns {"status": "generating"} — preview generation runs as
 * a background task; the caller must refetch to pick up the result. */
export async function triggerCharacterPreview(characterId: string): Promise<{ status: string }> {
  const response = await fetch(`/characters/${characterId}/preview`, { method: "POST" })
  return parseJsonOrThrow(response)
}
