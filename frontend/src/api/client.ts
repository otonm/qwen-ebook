// Typed fetch wrappers for the backend's /projects, /characters, /voices
// endpoints (backend/app/main.py). Same-origin via the Vite dev proxy
// (vite.config.ts) — no base URL needed.

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

export async function generateSegment(id: string): Promise<Segment> {
  const response = await fetch(`/segments/${id}/generate`, { method: "POST" })
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

/** CFG-03: on-demand character preview trigger for a character whose voice
 * was never (re)saved via PATCH /characters/{id}, so preview_audio_path is
 * still null. Returns {"status": "generating"} — preview generation runs as
 * a background task; the caller must refetch to pick up the result. */
export async function triggerCharacterPreview(characterId: string): Promise<{ status: string }> {
  const response = await fetch(`/characters/${characterId}/preview`, { method: "POST" })
  return parseJsonOrThrow(response)
}
