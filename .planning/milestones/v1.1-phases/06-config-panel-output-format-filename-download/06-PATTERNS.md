# Phase 6: Config Panel — Output Format, Filename & Download - Pattern Map

**Mapped:** 2026-07-15
**Files analyzed:** 8 (all modified, no new files)
**Analogs found:** 8 / 8 (all analogs are in-file precedents — same files this phase edits, following patterns established in earlier phases)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `backend/app/models.py` (add `Project.output_format`/`output_filename`) | model | CRUD | `backend/app/models.py` lines 24-30 (`tts_model` column + comment) | exact |
| `backend/app/db.py` (add 2 columns to `_NEW_COLUMNS["project"]`) | migration | batch | `backend/app/db.py` lines 42-55 (`_NEW_COLUMNS` dict) | exact |
| `backend/app/audio_join.py` (`join_wavs` 3-way codec dispatch) | service | transform | `backend/app/audio_join.py` lines 16-61 (existing 2-way dispatch, same function) | exact |
| `backend/app/config.py` (`_ALLOWED_OUTPUT_FORMATS` / `OUTPUT_FORMAT` default) | config | request-response | `backend/app/config.py` lines 41,54,68-83 (existing allowlist/fail-fast pattern) | exact |
| `backend/app/generation_worker.py` (`_join_project` reads `project.output_format`/`output_filename`, D-07 unlink-old) | service | event-driven | `backend/app/generation_worker.py` lines 27-30, 221-232 (existing `_join_project` join call) | exact |
| `backend/app/main.py` — new `PATCH /projects/{id}` (`ProjectConfigPatch`) | controller | CRUD | `backend/app/main.py` lines 548-577 (`CharacterPatch`/`patch_character`) | exact |
| `backend/app/main.py` — new `GET /projects/{id}/download` | controller | file-I/O | `backend/app/main.py` lines 1239-1250 (`get_segment_audio`) | role-match (upgrade `Response(read_bytes())` → `FileResponse`) |
| `backend/app/main.py` — `_serialize_project` (expose new fields) | transform | CRUD | `backend/app/main.py` lines 241-268 (existing `_serialize_project`) | exact |
| `frontend/src/api/client.ts` (`Project` interface + `patchProjectConfig`/`downloadUrl`) | service | request-response | `frontend/src/api/client.ts` lines 45-61, 154-164, 203-205, 280-287 (`Project` iface, `patchCharacter`, `previewUrl`, `setProjectModel`) | exact |
| `frontend/src/components/ConfigPanel.tsx` (Format `<Select>`, Filename `<input>`, Download `<Button>`) | component | request-response | `frontend/src/components/ConfigPanel.tsx` lines 320-366 (existing Model `<Select>` + `ConfigField` block) | exact |

## Pattern Assignments

### `backend/app/models.py` — add `output_format`/`output_filename` to `Project`

**Analog:** same file, `tts_model` column (lines 24-30)

```python
# Source: backend/app/models.py lines 24-30 (existing)
    # Phase 5 (CFG-04): the per-project source of truth for which Qwen TTS
    # checkpoint this project wants ("1.7b" | "0.6b") — compute_cache_key
    # reads this live on every generate-check. Never treat model choice as
    # ambient global config (RESEARCH.md Anti-Pattern) — it must live here,
    # per-project, so a swap in one project can't silently affect another's
    # cache correctness. Defaults to today's baseline model.
    tts_model: str = "1.7b"
```
Copy this shape exactly for the two new fields: `output_format: str = "mp3"` and `output_filename: str | None = None`, each with a comment citing Phase 6/CFG-06/CFG-07 and "per-project, read live at join/download time — never cached."

---

### `backend/app/db.py` — additive migrator entries

**Analog:** same file, `_NEW_COLUMNS["project"]` (lines 42-55)

```python
# Source: backend/app/db.py lines 42-55 (existing)
_NEW_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "segment": [...],
    "project": [
        ("created_at", "TEXT"),
        ("output_path", "TEXT"),
        ("tts_model", "TEXT DEFAULT '1.7b'"),
    ],
}
```
Append `("output_format", "TEXT DEFAULT 'mp3'")` and `("output_filename", "TEXT")` to the `"project"` list — no other change needed; the migrator loop (line ~59-63) is generic over the dict.

---

### `backend/app/audio_join.py` — `join_wavs` 3-way dispatch

**Analog:** same function, current 2-way dispatch (whole file, 62 lines)

```python
# Source: backend/app/audio_join.py lines 16-61 (existing, full function)
def join_wavs(wav_paths: list[str], out_path: str, fmt: str = "wav") -> str:
    ...
    try:
        codec_args = ["-c", "copy"] if fmt == "wav" else ["-c:a", "libmp3lame"]
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file_path,
             *codec_args, out_path],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed (exit {result.returncode}): {result.stderr}")
    finally:
        Path(list_file_path).unlink(missing_ok=True)
    return out_path
```
Replace the `if/else` ternary with RESEARCH.md's verified `CODEC_TABLE` dict (flac/mp3/opus, no catch-all — raise on unknown fmt) and add explicit `-f {fmt}` to the ffmpeg argv (RESEARCH Pattern 2). Keep the subprocess-shape (`capture_output`, `check=False`, manual returncode check, `finally: unlink`) — that error-handling skeleton is the reusable part, don't restructure it. `-c copy`/wav path can stay for internal callers if any remain (D-14 keeps WAV internally); `_ALLOWED_OUTPUT_FORMATS`-facing default becomes `"mp3"`.

---

### `backend/app/config.py` — allowlist + default

**Analog:** same file (lines 41, 54, 68-83)

```python
# Source: backend/app/config.py (existing, paraphrase of the read block)
_ALLOWED_OUTPUT_FORMATS = {"wav", "mp3"}
...
    output_format = os.environ.get("OUTPUT_FORMAT", "wav")
    if output_format not in _ALLOWED_OUTPUT_FORMATS:
        raise RuntimeError(
            f"OUTPUT_FORMAT={output_format!r} is not supported; "
            f"must be one of {sorted(_ALLOWED_OUTPUT_FORMATS)}"
        )
```
Widen `_ALLOWED_OUTPUT_FORMATS` to `{"flac", "mp3", "opus"}` (drop `"wav"`) and change the env fallback default from `"wav"` to `"mp3"` (RESEARCH Pitfall 2) — check `backend/.env` for a stale `OUTPUT_FORMAT=wav` first. Fail-fast-at-load philosophy is preserved verbatim; only the allowed set and default move.

---

### `backend/app/generation_worker.py` — `_join_project` reads per-project fields + D-07 unlink

**Analog:** same file (imports lines 27-30, join call lines 221-232)

```python
# Source: backend/app/generation_worker.py lines 221-232 (existing)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Server-generated uuid filename — never derived from any client string
    # (T-03-06).
    out_path = str(out_dir / f"{uuid.uuid4().hex}.{settings.OUTPUT_FORMAT}")
    await run_in_threadpool(join_wavs, wav_paths, out_path, settings.OUTPUT_FORMAT)

    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project is not None:
            project.output_path = out_path
            session.add(project)
            session.commit()
```
Replace `settings.OUTPUT_FORMAT` with `project.output_format` (read from the session, same place `tts_model` is already read elsewhere in this file for cache-key purposes — grep for `project.tts_model` in this file for that exact pattern). Add D-07's delete-old-output-first: before computing `out_path`, if `project.output_path` is set and `Path(project.output_path).is_file()`, `Path(project.output_path).unlink(missing_ok=True)`. Keep the UUID-based `out_path` naming (Pattern 3 in RESEARCH — filename is display-only, never used here).

---

### `backend/app/main.py` — new `PATCH /projects/{id}` config endpoint

**Analog:** `CharacterPatch`/`patch_character` (lines 548-577)

```python
# Source: backend/app/main.py lines 548-577 (existing, full pattern)
class CharacterPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    voice_preset: str | None = None
    voice_instructions: str | None = None


@app.patch("/characters/{character_id}")
async def patch_character(character_id: str, patch: CharacterPatch) -> dict:
    ...
    with Session(engine) as session:
        character = session.get(Character, character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Character not found")
        if patch.name is not None:
            character.name = patch.name
        # ... one `if patch.X is not None:` per field ...
        session.add(character)
        session.commit()
        session.refresh(character)
        return _serialize_character(character)
```
New `ProjectConfigPatch(BaseModel)` with `output_format: str | None = None`, `output_filename: str | None = None`. Validate `output_format` against the `CODEC_TABLE`/allowlist before entering the session (422 on mismatch, mirroring `set_project_model`'s `MODEL_CHOICES` check at line 396-397). Sanitize `output_filename` (strip `/ \ : * ? | " < >` + control chars, `Path(name).stem` to drop any user-typed extension per Open Question 2) before assignment. No `try_claim_generation` lock needed (RESEARCH Pattern 4 — this is inert DB state, unlike `set_project_model`). Return `_serialize_project(...)` like `patch_character` returns `_serialize_character`.

---

### `backend/app/main.py` — new `GET /projects/{id}/download`

**Analog:** `get_segment_audio` (lines 1239-1250)

```python
# Source: backend/app/main.py lines 1239-1250 (existing, full pattern)
@app.get("/segments/{segment_id}/audio.wav")
async def get_segment_audio(segment_id: str) -> Response:
    with Session(engine) as session:
        segment = session.get(Segment, segment_id)
        if segment is None:
            raise HTTPException(status_code=404, detail="Segment not found")
        audio_path = segment.audio_path

    if not audio_path or not Path(audio_path).is_file():
        raise HTTPException(status_code=409, detail="Audio not ready")

    return Response(content=Path(audio_path).read_bytes(), media_type="audio/wav")
```
Same 404/409 shape (404 project not found, 409 output not ready), but swap `Response(content=read_bytes())` for `fastapi.responses.FileResponse` per RESEARCH Pattern 3/Pitfall 4 — never hand-build `Content-Disposition`. Content-Type from `CODEC_TABLE[fmt]["content_type"]` (flac→`audio/flac`, mp3→`audio/mpeg`, opus→`audio/ogg` — NOT `audio/opus`, verified). `filename=` kwarg carries the sanitized `output_filename` + correct extension for the *current* format (never trust a stale extension the user may have typed).

```python
# Target shape, from RESEARCH.md Pattern 3 (already fully worked out there)
@app.get("/projects/{project_id}/download")
async def download_project(project_id: str) -> FileResponse:
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if not project.output_path or not Path(project.output_path).is_file():
            raise HTTPException(status_code=409, detail="Output not ready")
        fmt = project.output_format
        display_name = f"{sanitize_filename(project.output_filename or 'output')}.{fmt}"
    return FileResponse(
        project.output_path,
        media_type=CODEC_TABLE[fmt]["content_type"],
        filename=display_name,
    )
```

---

### `backend/app/main.py` — `_serialize_project` new fields

**Analog:** same function (lines 241-268)

```python
# Source: backend/app/main.py lines 250-257 (existing)
        "output_path": project.output_path,
        "output_format": settings.OUTPUT_FORMAT,
        # Phase 5 (CFG-04): drives the Config Panel's model dropdown ...
        "tts_model": project.tts_model,
```
Change `"output_format": settings.OUTPUT_FORMAT` → `"output_format": project.output_format` (it's per-project now, not a global setting) and add `"output_filename": project.output_filename`.

---

### `frontend/src/api/client.ts` — `Project` interface + config PATCH + download URL helper

**Analog:** `Project` interface (lines 45-61), `patchCharacter` (154-164), `previewUrl` (203-205), `setProjectModel` (280-287)

```typescript
// Source: frontend/src/api/client.ts lines 45-61 (existing)
export interface Project {
  id: string
  filename: string
  status: "analyzing" | "ready" | "error"
  error_detail: string | null
  output_path: string | null
  output_format: string
  tts_model: string
  characters: Character[]
  segments: Segment[]
}
```
Add `output_filename: string | null` to the interface; update the `output_format` comment (no longer "a fixed server setting" — now per-project, same status as `tts_model`).

```typescript
// Source: frontend/src/api/client.ts lines 154-164 (existing PATCH shape)
export async function patchCharacter(id: string, body: CharacterPatch): Promise<Character> {
  const response = await fetch(`/characters/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  return parseJsonOrThrow(response)
}
```
New `patchProjectConfig(id: string, body: { output_format?: string; output_filename?: string }): Promise<Project>` — identical shape, `PATCH /projects/${id}`.

```typescript
// Source: frontend/src/api/client.ts lines 203-205 (existing plain-URL helper)
export function previewUrl(characterId: string): string {
  return `/characters/${characterId}/preview.wav`
}
```
New `downloadUrl(projectId: string): string { return `/projects/${projectId}/download` }` — same "just return the URL string, let the browser/`<a>` tag do the fetch" pattern (no `fetch()` wrapper needed for a download link, matches `segmentAudioUrl`/`previewUrl` precedent exactly).

---

### `frontend/src/components/ConfigPanel.tsx` — Format `<Select>`, Filename `<input>`, Download `<Button>`

**Analog:** existing Model `<Select>` block + `ConfigField` (lines 320-366), `handleModelChange` (284-305)

```tsx
// Source: frontend/src/components/ConfigPanel.tsx lines 320-345 (existing Model Select)
<div className="flex flex-col gap-1">
  <span className="text-xs font-semibold text-muted-foreground">Model</span>
  <Select
    value={project.tts_model}
    onValueChange={(value) => void handleModelChange(value)}
    disabled={isSwapping}
  >
    <SelectTrigger size="sm" aria-label="TTS model" className="w-full">
      <SelectValue />
    </SelectTrigger>
    <SelectContent>
      <SelectItem value="1.7b">Higher quality (1.7B)</SelectItem>
      <SelectItem value="0.6b">Faster (0.6B)</SelectItem>
    </SelectContent>
  </Select>
</div>
```
Copy this exact `<Select>` shape for Format (`FLAC`/`MP3`/`Opus` items), replacing `handleModelChange`'s `setProjectModel` call with `patchProjectConfig(project.id, { output_format: value })`, then `onRefresh()`. Existing `ConfigField label="Output Format" value={project.output_format.toUpperCase()}` (line 359) is the read-only stand-in this phase upgrades into the live `<Select>` — delete that `ConfigField` line once the `<Select>` replaces it.

```tsx
// Source: frontend/src/components/ConfigPanel.tsx lines 284-305 (existing async PATCH handler shape)
async function handleModelChange(nextModelId: string) {
  setIsSwapping(true)
  setSwapError(null)
  try {
    await setProjectModel(project.id, nextModelId)
    onRefresh()
  } catch (err) {
    setSwapError(errorMessage(err, `Couldn't switch to ...`))
  } finally {
    setIsSwapping(false)
  }
}
```
Same shape for `handleFormatChange`/`handleFilenameBlur` (filename uses `onBlur`, not `onChange`, to avoid a PATCH per keystroke — a plain controlled `<input>` with local `useState` mirrored to `project.output_filename` on mount/refresh, PATCH fired on blur).

Download button: use the existing primary `<Button>` (Generate All, lines 384-401) — same `variant` default (already indigo/"blue" per RESEARCH's confirmed `--primary` token, no new variant). Render as `<a href={downloadUrl(project.id)} download>` wrapped in the shadcn `Button` `asChild` pattern, or a plain anchor styled with the Button's classes — check `frontend/src/components/ui/button.tsx` for the `asChild` prop before picking; visible only when `project.output_path` is set (D-06/Claude's Discretion: disabled-with-tooltip vs hidden — precedent in this file is conditional rendering, e.g. `{isBatchRunning && (...)}` at line 402, so hide-until-ready matches existing style better than disabled-with-tooltip).

## Shared Patterns

### Per-project config column (not global `Settings`)
**Source:** `backend/app/models.py` `tts_model` (lines 24-30) + `backend/app/db.py` `_NEW_COLUMNS["project"]` (lines 42-55)
**Apply to:** `models.py`, `db.py`, `generation_worker.py`, `main.py::_serialize_project` — every place `output_format`/`output_filename` are read or written.

### Optional-field PATCH endpoint, no generation lock
**Source:** `backend/app/main.py::CharacterPatch`/`patch_character` (lines 548-577)
**Apply to:** new `ProjectConfigPatch`/`patch_project_config`.

### File-serving via FastAPI response objects, 404/409 error shape
**Source:** `backend/app/main.py::get_segment_audio` (lines 1239-1250)
**Apply to:** new `download_project` — upgrade `Response(read_bytes())` to `FileResponse` for the one new requirement (`Content-Disposition` filename) this codebase hasn't needed before.

### Explicit-only allowlist / fail-fast validation
**Source:** `backend/app/config.py` `_ALLOWED_OUTPUT_FORMATS` (line 41) + `backend/app/main.py::set_project_model`'s `MODEL_CHOICES` check (line 396)
**Apply to:** `audio_join.py`'s `CODEC_TABLE`, the new PATCH's `output_format` validation, and `download_project`'s content-type lookup — all three must move together atomically (RESEARCH Anti-Pattern warning).

### Controlled `<Select>` bound to server state, PATCH-on-change, revert-on-failure
**Source:** `frontend/src/components/ConfigPanel.tsx` Model `<Select>` + `handleModelChange` (lines 284-305, 326-345)
**Apply to:** new Format `<Select>` and Filename `<input>`.

## No Analog Found

None — every file this phase touches already has a same-file or same-repo precedent from Phases 3/5 (per CONTEXT.md D-11/D-13 and RESEARCH.md's "every piece of this phase already has an established in-repo precedent" conclusion).

## Metadata

**Analog search scope:** `backend/app/` (models.py, db.py, audio_join.py, config.py, generation_worker.py, main.py), `frontend/src/api/client.ts`, `frontend/src/components/ConfigPanel.tsx` — no directory-wide Glob/Grep needed since RESEARCH.md's canonical_refs already named every touched file precisely.
**Files scanned:** 8 (all direct reads, no large-file offset/limit needed — largest file, main.py, was read in targeted line ranges already pinpointed by RESEARCH.md's own line-number citations)
**Pattern extraction date:** 2026-07-15
