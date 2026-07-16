<!-- generated-by: gsd-doc-writer -->
# API

This is the HTTP API for the Qwen Ebook Narrator backend (FastAPI, `backend/app/main.py`).
It is served on the same process/port as the frontend static bundle (mounted last, so any
path not matched by a route below falls through to the SPA).

There is no authentication layer. The app is designed to run behind Tailscale as the sole
access boundary (single trusted user/network — see `CLAUDE.md` Constraints); no API key,
session, or login mechanism exists in this codebase.

A second section at the bottom documents the internal TTS inference service
(`backend/tts_service/server.py`), which is **not** part of this public API — it listens on
port 8001 inside the same pod and is never published to the host or network.

## Authentication

None. Every route below is unauthenticated; access control is entirely at the network layer
(Tailscale). Do not expose this backend to a public or shared network without adding an
auth layer first.

## Global generation lock

Exactly one generation-triggering operation — a character preview, a single segment
generate, a whole-project batch generate, or a model swap — may run at a time, across the
**entire app**, not just per project. This reflects the single-GPU/single-resident-model
constraint (`app/generation_worker.py`'s `try_claim_generation`/`release_generation`).

Any route that would start a new generation returns:

```
409 Conflict
{"detail": "Another generation is already in progress"}
```

if another one is already in flight. `GET /generation-status` lets the frontend poll and
disable generation controls proactively instead of relying solely on the 409.

## Endpoints overview

| Method | Path | Description | Notes |
|---|---|---|---|
| POST | `/projects` | Upload a source file (`.epub` or UTF-8 `.txt`), create a project, kick off background LLM analysis | 201 |
| GET | `/projects` | List all projects (id/filename/status/created_at only), newest first | |
| GET | `/projects/{project_id}` | Fetch full project payload: characters + segments | 404 if missing |
| PATCH | `/projects/{project_id}` | Update `output_format` and/or `output_filename` | |
| DELETE | `/projects/{project_id}` | Delete a project and all its generated audio files | 204 |
| GET | `/projects/{project_id}/download` | Download the joined output audio file | 409 if not ready |
| GET | `/projects/{project_id}/analysis-stream` | SSE stream of LLM analysis progress | `EventSourceResponse` |
| GET | `/projects/{project_id}/generation-stream` | SSE stream of batch-generation progress | `EventSourceResponse` |
| POST | `/projects/{project_id}/generate` | Start (or resume) whole-project batch generation | 202 |
| POST | `/projects/{project_id}/generate/cancel` | Cancel the project's in-flight batch generation | |
| POST | `/projects/{project_id}/model` | Swap the project's resident TTS model (`1.7b` / `0.6b`) | invalidates cached audio + previews |
| GET | `/voices` | List preset voices (name + label) | |
| GET | `/generation-status` | `{"active": bool}` — is any generation running anywhere in the app | |
| GET | `/healthz` | Backend readiness (can it reach the TTS service) | 503 if not |
| PATCH | `/characters/{character_id}` | Edit a character's name/description/voice | invalidates stale preview |
| POST | `/characters/{character_id}/preview` | Generate a voice preview clip for a character | 202-style, 409 if busy |
| POST | `/characters/{character_id}/preview/cancel` | Cancel an in-flight character preview | |
| GET | `/characters/{character_id}/preview.wav` | Fetch the character's preview audio | 409 if not ready |
| POST | `/characters/{character_id}/merge` | Merge one character's segments into another, delete the source | returns an `undo` snapshot |
| POST | `/characters/undo-merge` | Reverse a single merge using its `undo` snapshot | stateless, single-shot |
| PATCH | `/segments/{segment_id}` | Edit a segment's character/text/voice instructions | invalidates cached audio |
| POST | `/segments/{segment_id}/generate` | Generate audio for one segment | 202, 409 if busy or already generating |
| POST | `/segments/{segment_id}/generate/cancel` | Cancel an in-flight segment generation | |
| GET | `/segments/{segment_id}/audio.wav` | Fetch a segment's generated audio | 409 if not ready |
| POST | `/segments/bulk-reassign` | Reassign multiple segments to one character | |

None of these routes require an `Authorization` header or any credential.

## Project endpoints

### `POST /projects`

Uploads a source file and creates a project. Accepts `multipart/form-data` with a `file`
field. `.epub` files (by extension or `Content-Type`) are parsed via `ebooklib`; anything
else is decoded as UTF-8 plain text.

- 413 if the upload exceeds `MAX_UPLOAD_BYTES` (see `docs/CONFIGURATION.md`).
- 400 if EPUB parsing fails, the upload isn't valid UTF-8, or the extracted text is empty.
- 201 on success:

```json
{"id": "a1b2c3...", "status": "analyzing"}
```

Analysis (cast + segment detection via the OpenRouter LLM) runs as a background task.
Poll `GET /projects/{id}` or subscribe to `GET /projects/{id}/analysis-stream` for
completion.

### `GET /projects`

Returns the project list for the landing screen, newest first:

```json
[{"id": "...", "filename": "book.epub", "status": "ready", "created_at": "2026-01-01T00:00:00"}]
```

### `GET /projects/{project_id}`

Returns the full project payload:

```json
{
  "id": "...",
  "filename": "book.epub",
  "status": "ready",
  "error_detail": null,
  "output_path": "/path/to/output.mp3",
  "output_format": "mp3",
  "output_filename": null,
  "tts_model": "1.7b",
  "characters": [
    {
      "id": "...",
      "name": "Narrator",
      "description": "...",
      "is_narrator": true,
      "voice_preset": "narrator_sultry_woman",
      "voice_instructions": "...",
      "preview_audio_path": "/path/to/preview.wav"
    }
  ],
  "segments": [
    {
      "id": "...",
      "order": 0,
      "character_id": "...",
      "character_name": "Narrator",
      "text": "...",
      "voice_instructions": "...",
      "generation_status": "pending",
      "generation_error": null,
      "audio_path": null
    }
  ]
}
```

404 if the project does not exist. `status` is one of `analyzing` / `ready` / `error`.
`generation_status` per segment is one of `pending` / `generating` / `complete` / `error`.

### `PATCH /projects/{project_id}`

Body (all fields optional):

```json
{"output_format": "mp3", "output_filename": "my book"}
```

- `output_format` must be one of the `CODEC_TABLE` keys: `flac`, `mp3`, `opus`. 422 otherwise.
- `output_filename` is sanitized server-side (path separators become `_`, illegal filesystem
  characters and any user-typed extension are stripped); an empty result after sanitizing is
  stored as `null`.
- Changing `output_format` invalidates the current joined output (`output_path` resets to
  `null` and the old file is deleted) since it was encoded in the previous format.
- Returns the full project payload (same shape as `GET /projects/{id}`). 404 if missing, 422
  on an unknown format.

### `DELETE /projects/{project_id}`

Deletes the project row, its characters, its segments, and every generated file referenced
by them (joined output, character previews, segment audio). If a batch generation is
currently running for this project, it is cancelled first. 204 on success, 404 if missing.

### `GET /projects/{project_id}/download`

Streams the joined output file with `Content-Type` set from `CODEC_TABLE` and a
`Content-Disposition` filename built from the sanitized `output_filename` (or the upload
filename's stem as a fallback) plus the correct extension. 409 if no output has been
generated yet, 404 if the project doesn't exist.

### `POST /projects/{project_id}/generate`

Starts (or resumes) whole-project batch generation as a background task; progress is
delivered over `GET /projects/{id}/generation-stream`. 202 with one of:

```json
{"status": "started"}
{"status": "already_running"}
{"status": "busy"}
```

`already_running` means this same project's batch is already in flight (no-op, no new task
spawned). `busy` means a *different* generation (another project, a segment, or a character
preview) holds the global lock. 404 if the project doesn't exist. Re-invoking on an
already-complete project is a fast no-op re-join thanks to per-segment caching.

### `POST /projects/{project_id}/generate/cancel`

Cancels a live batch run: requests a stop, interrupts the in-flight TTS call, waits for the
current segment to settle, then resets any segment left `generating` back to `pending`.

```json
{"status": "cancelled"}
{"status": "not_running"}
```

### `GET /projects/{project_id}/analysis-stream`

`text/event-stream` (`EventSourceResponse`). 404 if the project doesn't exist. Event types:

- `progress` — `{"stage": "estimating"}`, `{"stage": "analyzing"}`, or
  `{"stage": "chunk", "n": <int>, "total": <int>}` for chunked (long-text) analysis.
- `done` — `{"status": "ready"}`
- `error` — `{"detail": "<error message>"}`

If analysis already finished and no client has consumed the terminal event yet, that
buffered `done`/`error` event is replayed on connect.

### `GET /projects/{project_id}/generation-stream`

`text/event-stream` (`EventSourceResponse`). 404 if the project doesn't exist. Event types:

- `progress` — `{"segment_id": "...", "n": <int>, "total": <int>, "status": "generating" | "complete" | "error"}`
- `done` — `{"status": "ready"}` (batch finished and joined), or `{"status": "cancelled"}`
  (batch was cancelled)
- `error` — `{"detail": "<error message>"}`

If no batch is running and nothing is buffered, the endpoint immediately emits
`{"status": "idle"}` as a `done` event and closes.

### `POST /projects/{project_id}/model`

Body:

```json
{"model_id": "1.7b"}
```

`model_id` must be `1.7b` or `0.6b` (422 otherwise). Claims the global generation lock,
requests the TTS service load the checkpoint (`POST /model/{model_id}/load` internally),
and on success:

- Marks every segment in the project `pending` and clears its `audio_path`/`cache_key`
  (invalidated, not deleted from the DB — just needs regeneration).
- Clears every character's `preview_audio_path`.
- Deletes the now-orphaned audio files from disk.

Returns the full project payload. If `model_id` already matches the project's current
`tts_model`, this is a no-op that returns immediately without touching the lock or any
audio. 502 if the model load itself fails — in that case the project, its cached audio, and
previews are left completely untouched (the previous model stays resident). 404 if the
project doesn't exist. 409 if another generation already holds the global lock.

### `GET /voices`

```json
[{"name": "narrator_sultry_woman", "label": "Narrator (young sultry woman)"}, ...]
```

The preset voice picker list for the wizard/config panel.

### `GET /generation-status`

```json
{"active": true}
```

`true` if any generation (preview, segment, batch, or model swap) is currently running
anywhere in the app.

### `GET /healthz`

200 if the backend can currently reach its configured TTS backend; 503 with
`{"detail": "TTS backend unavailable"}` otherwise. No response body on success.

## Character endpoints

### `PATCH /characters/{character_id}`

Body (all fields optional):

```json
{"name": "...", "description": "...", "voice_preset": "...", "voice_instructions": "..."}
```

Changing `voice_preset` and/or `voice_instructions` invalidates (does not regenerate) the
character's existing preview: `voice_version` is bumped and `preview_audio_path` is cleared
and the old file deleted. Returns the serialized character. 404 if the character doesn't
exist.

### `POST /characters/{character_id}/preview`

Generates a short intro-line preview clip ("Hi, my name is {name} and I am a
{description}.") for the character, using its resolved preset/speaker and voice
instructions. Claims the global lock; 409 if busy. On success:

```json
{"status": "generating"}
```

The client polls `GET /projects/{id}` (or the character's `preview_audio_path`) for
completion.

### `POST /characters/{character_id}/preview/cancel`

Interrupts an in-flight preview generation for this character.

```json
{"status": "cancelled"}
{"status": "not_running"}
```

### `GET /characters/{character_id}/preview.wav`

Returns the character's preview clip as `audio/wav`. 409 if none has been generated yet
(or the file is missing), 404 if the character doesn't exist.

### `POST /characters/{character_id}/merge`

Body:

```json
{"target_id": "..."}
```

Reassigns every segment from `character_id` (source) onto `target_id`, then deletes the
source character (and its preview file, if any). 400 if source and target are the same
id; 404 if either doesn't exist or they belong to different projects. Returns the target
character plus a `segment_count` and an `undo` snapshot:

```json
{
  "...target character fields...",
  "segment_count": 12,
  "undo": {
    "character": { "id": "...", "project_id": "...", "name": "...", "description": "...",
                   "is_narrator": false, "voice_preset": null, "voice_instructions": "...",
                   "voice_version": 0, "had_preview": true },
    "segment_ids": ["..."]
  }
}
```

### `POST /characters/undo-merge`

Body: the exact `undo` object returned by the merge this call reverses:

```json
{"character": {...}, "segment_ids": ["..."]}
```

Recreates the source character with its original id/fields and reassigns the given segment
ids back to it. If the merged character had a preview, a fresh preview generation is
kicked off best-effort (silently skipped, not a 409, if the global lock is busy). Stateless
single-shot: only the merge that produced this exact snapshot can be undone; there is no
server-side undo history. 409 if a character with this id already exists, 404 if the
project or any segment id doesn't exist, 400 if a segment belongs to a different project.

## Segment endpoints

### `PATCH /segments/{segment_id}`

Body (all fields optional):

```json
{"character_id": "...", "voice_instructions": "...", "text": "..."}
```

Any change invalidates the segment's cached audio: `generation_version` is bumped,
`generation_status` resets to `pending`, `generation_error` is cleared, and the old audio
file is deleted. Regeneration is not triggered automatically — the user (or a batch run)
must call `POST /segments/{id}/generate` explicitly. 404 if the segment or the given
`character_id` doesn't exist; 400 if `character_id` belongs to a different project.

### `POST /segments/{segment_id}/generate`

Synthesizes audio for one segment. 409 if the segment is already `generating`, or if
another generation holds the global lock. On success:

```json
{"status": "generating"}
```

Synthesis reuses cached audio on a cache hit (unchanged speaker/instructions/text/model) —
no new TTS call is made in that case. Poll `GET /projects/{id}` for the resulting
`generation_status`.

### `POST /segments/{segment_id}/generate/cancel`

Interrupts an in-flight segment generation and resets it to `pending` (a user-requested
stop is not treated as an error).

```json
{"status": "cancelled"}
{"status": "not_running"}
```

### `GET /segments/{segment_id}/audio.wav`

Returns the segment's generated audio as `audio/wav`. 409 if not ready, 404 if the segment
doesn't exist.

### `POST /segments/bulk-reassign`

Body:

```json
{"segment_ids": ["..."], "character_id": "..."}
```

Reassigns every listed segment to `character_id` and bumps each one's `generation_version`
(marks stale; does not itself trigger regeneration). 404 if the target character or any
segment id doesn't exist; 400 if any segment belongs to a different project than the
target character. Returns:

```json
{"updated": 3}
```

## Internal TTS service API (pod-internal, port 8001 — never published)

`backend/tts_service/server.py` runs as a separate container in the same pod, scoped to the
GPU. It is reachable only from the backend container over the pod-internal network
(`TTS_SERVICE_URL`, default `http://localhost:8001` — see `docs/CONFIGURATION.md`). Its
port is never published to the host or Tailscale network; this is not a public API and has
no authentication of its own beyond network isolation.

### `POST /synthesize`

```json
{"text": "...", "speaker": "sohee", "instruct": "sad and aggressive"}
```

`speaker` and `instruct` are optional. Returns `audio/wav` bytes on success (200).

- 422 if `text` is empty or whitespace-only.
- 400 if `speaker` is unsupported (`ValueError` from the underlying `qwen-tts` package).
- 499 if the call was interrupted by `POST /cancel`.
- 503 if no model is currently loaded/resident.
- 500 on any other synthesis/runtime failure.

### `POST /model/{model_id}/load`

Swaps the resident checkpoint. `model_id` must be one of the service's own
`MODEL_CHOICES` allowlist (`1.7b` / `0.6b`); 422 on an unrecognized id, 503 if the model
module isn't initialized yet. 200 once the new checkpoint is resident. On failure (500),
the previously-resident model remains loaded and usable — the old checkpoint is only
released after the new one loads successfully.

### `POST /cancel`

Best-effort, fire-and-forget: flags the in-flight `/synthesize` call's stopping condition,
checked on its next decode step. Does not block until that call actually finishes. 202 on
receipt; 503 if the model module isn't initialized yet.

### `GET /healthz`

200 (`"ok"`) only once a model has finished loading and is resident; 503 (`"model not
loaded"`) otherwise — including during a model swap in progress.
