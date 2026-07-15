# Phase 6: Config Panel — Output Format, Filename & Download - Research

**Researched:** 2026-07-15
**Domain:** FastAPI file-download endpoint + ffmpeg codec dispatch + per-project config columns (SQLModel/SQLite)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Format choice is per-generation, selectable from the Config Panel — not a global environment setting like v1.0's `OUTPUT_FORMAT` env var. The selector shows three options: FLAC, MP3, Opus. User can try different formats for the same segment/project without re-generating the underlying audio (all formats use the same WAV intermediates from synthesis; the format choice only affects the final ffmpeg join step).
- **D-02:** Format selection is persisted per-project in a new `Project.output_format` column (defaults to a sensible first choice, TBD once codec availability is confirmed — likely MP3 for broad compatibility). User can change the format before each generation run; the previous choice is preserved as the default.
- **D-03:** Filename is user-set and persisted per-project via a new `Project.output_filename` column. A text input in the Config Panel lets the user type a custom filename. The app automatically appends the correct file extension based on the chosen format (e.g., user types "my-book" + format=MP3 → saved as "my-book.mp3"). User can edit the filename anytime before clicking Generate All.
- **D-04:** Filename is sanitized automatically (strict mode) — the app removes/replaces invalid filesystem characters (e.g., /, \, :, *, ?, |, ", <, >) without showing a dialog. If sanitization occurs, the user sees the final name in the Config Panel immediately (no hidden surprise at download time). No user confirmation for sanitization; the field always shows the actual filename that will be used.
- **D-05:** If the user leaves the filename field empty, auto-generate a sensible default — derive it from the original upload filename (e.g., book.epub → "book"; or if that's unavailable, use the project id or "output"). This keeps the user from accidentally leaving it blank.
- **D-06:** After batch generation completes and the output file is successfully joined, a blue "Download" button appears in the Config Panel (next to or below the existing Generate All button). Clicking it triggers a browser download with the chosen filename.
- **D-07:** When a user clicks Generate All while a previous output file exists, the old file is deleted and replaced with the new one. Only the latest output ever persists on disk. The `Project.output_path` always points to the current file.
- **D-08:** The download endpoint must serve the file with the correct `Content-Type` header based on the actual format (audio/flac for FLAC, audio/mpeg for MP3, audio/opus or audio/ogg for Opus). The file extension must always match the format so the browser doesn't double-guess the type.
- **D-09:** Before planning, spike to verify codec availability (specifically, `libopus` in the deploy VM's ffmpeg build). Run `ffmpeg -codecs | grep -E 'opus|flac|mp3'` on the deploy container. If Opus is unavailable, escalate to the user — either drop Opus from the Phase 6 requirements or add a DevOps task to rebuild ffmpeg with libopus support.
- **D-10:** Phase 6 planning and implementation assumes all three codecs (FLAC, MP3, Opus) are available and working. No runtime fallback if a codec fails; if the spike finds Opus missing, the decision is made upstream before code lands.
- **D-11:** Existing `audio_join.py`'s `join_wavs(fmt)` function is the integration point. The function already handles "wav" (stream copy) and "mp3" (libmp3lame) — add "flac" (libflac or -c:a flac) and "opus" (libopus or -c:a libopus) with the same pattern. No new internal codecs, no named_codec registries; keep the same simple `if fmt == X` dispatch.
- **D-12:** New `Project.output_format` and `Project.output_filename` columns default sensibly — `output_format` to MP3 (broad compatibility, TBD confirm once D-09's spike is done — now done, see Summary); `output_filename` to the original upload filename's stem or project id if unavailable.
- **D-13:** Format and filename choices flow through the existing generation pipeline unchanged: `generate_project` remains fire-and-forget and reads `Project.output_format`/`output_filename` when calling `run_batch_generation`; `run_batch_generation` passes these to `join_wavs(..., fmt=project.output_format)` — no change to the function signature, just pass the format. Download is a separate, new endpoint (`GET /projects/{id}/download` or similar).
- **D-14:** No change to segment/character preview generation — those still produce WAV. Only the final joined output respects the user's format choice.

### Claude's Discretion

- Exact default value for `output_format` column (D-09's spike is resolved this session: all three codecs confirmed available — MP3 remains the recommended default for broad compatibility per D-12's own stated rationale).
- Exact location of the Format dropdown + Filename text input in the Config Panel layout (next to the model dropdown, or below it; exact copy/labels).
- Exact file extension strategy if the user's filename already includes an extension (e.g., user types "my-book.mp3" for an Opus output) — see Open Question 2 for this research's recommendation (strip and re-add).
- Exact Content-Type headers for each format (this research resolves the Opus ambiguity: `audio/ogg`, not `audio/opus` — see Common Pitfalls / Pitfall 5).
- Whether the Download button should be disabled until output exists, or visible-but-disabled with a tooltip.

### Deferred Ideas (OUT OF SCOPE)

None yet (per CONTEXT.md `<deferred>`). Also explicitly out of scope per REQUIREMENTS.md v1.1 and CONTEXT.md's Phase Boundary: auto-download or auto-play on completion; WAV as an output format; a configurable codec fallback strategy; multi-file retention (only the latest output persists).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CFG-06 | User can choose the output audio format: FLAC, MP3, or Opus (WAV is dropped as an option) | Codec availability verified this session (`ffmpeg -codecs`/`-encoders`, live encode round-trips) — see Summary, Standard Stack, Pattern 2. `_ALLOWED_OUTPUT_FORMATS` widening + `audio_join.py`'s 3-way dispatch table fully specified with verified working flags. |
| CFG-07 | User can set a custom output filename before generating the final file | Pattern 3 (filename is display-only, never the on-disk path) + Pattern 4 (PATCH endpoint pattern) + Open Questions 1/2 (default-derivation and extension-stripping rules) fully specify the mechanism, following existing `patch_character`/`T-03-01`/`T-03-06` discipline. |
| CFG-08 | User can download the finished, joined audio file via a blue "Download" button once generation completes | Architecture Patterns (System Diagram, Pattern 3) + Pitfalls 3-5 (path safety, header safety, correct Content-Type) fully specify the new `GET /projects/{id}/download` route using `FileResponse`. The existing `primary`/indigo Button variant (already used for "Generate All") satisfies D-06's "blue" requirement with no new variant needed — confirmed via `frontend/src/index.css`'s `--primary: oklch(51.1% 0.262 276.966)` (indigo-600, hue ~277, the app's established single accent color for primary CTAs). |

</phase_requirements>

## Summary

Phase 6 is almost entirely mechanical: extend an already-parametrized ffmpeg join function from 2 formats to 3, promote a global env setting to two new per-project DB columns (following the exact pattern Phase 5 already established for `Project.tts_model`), and add one new download route using FastAPI's built-in `FileResponse`. There is no new library, no new architectural boundary, and no unresolved technical risk — the milestone's own pre-existing research (`.planning/research/ARCHITECTURE.md` Capability 3/4, `PITFALLS.md` Pitfalls 6-9, `STACK.md` §(c)) already scoped this phase in detail before the roadmap was written; this pass **confirms those findings against the actual deploy-equivalent environment** rather than re-deriving them.

**The single blocking unknown flagged in CONTEXT.md (D-09) is now resolved.** This research session ran directly on a Debian 13 (trixie) host matching the deploy VM's OS (`/etc/os-release` confirms `VERSION_CODENAME=trixie`) and installed the exact `apt-get install ffmpeg` package the project's `Containerfile.backend` already uses. The resulting `ffmpeg 7.1.5-0+deb13u1` build has `--enable-libopus`, `--enable-libmp3lame`, and the native `flac` encoder all compiled in, and a live encode of a synthetic WAV to all three formats succeeded with zero errors. **All three codecs (FLAC, MP3, Opus) are confirmed available — no escalation to the user is needed, no codec needs to be dropped.**

**Primary recommendation:** Extend `audio_join.py`'s codec dispatch to an explicit 3-way lookup table (no catch-all `else`), add `Project.output_format`/`Project.output_filename` columns via the existing `_NEW_COLUMNS` migrator in `db.py`, add a `PATCH /projects/{id}` endpoint mirroring `patch_character`'s optional-field pattern (no generation-lock needed — these fields don't touch the GPU), and add `GET /projects/{id}/download` using `FileResponse(path, media_type=..., filename=...)` — never hand-format the `Content-Disposition` header.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Format/filename selection UI | Browser / Client (React ConfigPanel) | API (persists via PATCH) | Pure form state until submitted; server is source of truth once persisted |
| Format/filename persistence | API / Backend | Database / Storage | New `Project` columns, read at generate time — same pattern as `tts_model` |
| Codec dispatch (ffmpeg invocation) | API / Backend | — | `audio_join.py` already shells out to system ffmpeg from the backend process; no separate service |
| Output file storage | Database / Storage (path) + filesystem (bytes) | — | `Project.output_path` stays a server-generated UUID path; DB is the pointer, disk is the blob store |
| Download serving | API / Backend | — | New `GET /projects/{id}/download` resolves path from DB by id, serves via `FileResponse` |
| Filename sanitization | API / Backend | — | Must happen server-side at write time (PATCH handler), not trusted from client, not deferred to header-encoding time |

## Standard Stack

### Core

No new packages. Every piece needed is already installed or already an OS-level dependency:

| Component | Version (verified) | Purpose | Why Standard |
|-----------|---------------------|---------|---------------|
| `ffmpeg` (system binary) | `7.1.5-0+deb13u1` (Debian 13 trixie `apt` candidate, confirmed installed and working during this research session) | flac/mp3/opus encode via concat demuxer | Already the project's only audio-join mechanism (`audio_join.py`); `--enable-libopus`, `--enable-libmp3lame`, native `flac` all present in this exact build |
| `fastapi.responses.FileResponse` | Ships with `fastapi==0.139.0` (already pinned in `backend/pyproject.toml`) | Serve the joined output file with correct `Content-Type` + RFC-6266-correct `Content-Disposition` | Framework-native; existing routes (`get_segment_audio`, `get_character_preview`) use the cruder `Response(content=..., media_type=...)` because those never needed a `Content-Disposition` filename — the download route is the first place that requirement actually appears |
| `sqlmodel` (existing) | Already `>=0.0.39` in `pyproject.toml` | Two new `Project` columns | No new dependency; extend the existing model + the existing `_NEW_COLUMNS` additive migrator in `db.py` |
| Python stdlib (`re`/`str` methods) | stdlib | Filename sanitization | A regex stripping path separators/control characters is sufficient for D-04's "strict mode" — no sanitization library needed for a single-user tool serving its own generated file back to itself |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| (none) | — | — | This phase adds zero new supporting libraries |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Python stdlib regex sanitization | `python-slugify` / `pathvalidate` | Unnecessary dependency for stripping ~10 known-bad characters in a single-user, server-controlled-path app; adds a package for what `re.sub` does in one line |
| `FileResponse` | Reading bytes into memory (`Response(content=Path(...).read_bytes())`, matching existing WAV preview routes) | The existing pattern is fine for short preview clips but wrong for a full joined audiobook file — don't buffer a potentially large file fully into memory when the framework already streams it from disk |
| ffmpeg native `opus` encoder | `libopus` | Native encoder is lower quality/maturity at equivalent bitrate — always prefer `-c:a libopus` explicitly (verified present in this build) |

**Installation:**
No new packages to install. `ffmpeg` is already declared in `backend/Containerfile.backend` (`apt-get install -y --no-install-recommends ffmpeg`) and already present with all needed codecs — no `Containerfile` change required for codec support itself.

**Version verification:** Ran directly on a Debian 13 (trixie) host matching the deploy VM:
```
$ ffmpeg -version | head -1
ffmpeg version 7.1.5-0+deb13u1 Copyright (c) 2000-2026 the FFmpeg developers
$ ffmpeg -codecs | grep -E '\bopus\b|\bflac\b|\bmp3\b'
 DEAI.S flac    FLAC (Free Lossless Audio Codec)
 DEAIL. mp3     MP3 (MPEG audio layer 3) (decoders: mp3float mp3) (encoders: libmp3lame libshine)
 DEAIL. opus    Opus (Opus Interactive Audio Codec) (decoders: opus libopus) (encoders: opus libopus)
```
`[VERIFIED: ffmpeg 7.1.5-0+deb13u1 on Debian 13 trixie, apt candidate package matching Containerfile.backend's install line]` — this directly resolves CONTEXT.md D-09's spike gate. `_ALLOWED_OUTPUT_FORMATS` can be widened to `{"flac", "mp3", "opus"}` (WAV dropped) with no further codec-availability risk.

## Package Legitimacy Audit

**Not applicable — this phase installs no new external packages.** `ffmpeg`'s `libopus`/`libmp3lame`/`flac` are codec components of the already-installed `ffmpeg` system binary, not separate pip/npm/cargo packages, and no new Python or JS dependency is added to `pyproject.toml` or `package.json` by this phase.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────┐
│  ConfigPanel.tsx (browser)  │
│  - Format <Select>          │
│  - Filename <input>         │
│  - blue "Download" <Button> │
└──────────┬───────────────────┘
           │ 1. onChange/onBlur → PATCH
           ▼
┌───────────────────────────────────────────┐
│  PATCH /projects/{id}                     │  (NEW — no GPU lock needed)
│  - validates format ∈ {flac,mp3,opus}     │
│  - sanitizes filename (strict mode, D-04) │
│  - writes Project.output_format/          │
│    output_filename                        │
└──────────┬─────────────────────────────────┘
           │ 2. persisted, read back on next render
           ▼
   [ user clicks Generate All — unchanged endpoint ]
           │
           ▼
┌───────────────────────────────────────────┐
│  run_batch_generation / _join_project     │  (existing, Phase 3)
│  - synth all segments → per-segment WAVs  │
│  - reads project.output_format (NEW: was  │
│    settings.OUTPUT_FORMAT)                │
│  - D-07: unlink old output_path first     │
│  - join_wavs(wav_paths, out_path, fmt)    │
└──────────┬─────────────────────────────────┘
           │ 3. ffmpeg concat demuxer, format-specific codec_args + -f <fmt>
           ▼
┌───────────────────────────────────────────┐
│  audio_join.py: join_wavs()               │  (EXTENDED — 3-way dispatch)
│  {"flac": [...], "mp3": [...],            │
│   "opus": [...]}[fmt]  (no catch-all else)│
└──────────┬─────────────────────────────────┘
           │ 4. Project.output_path = out_path (server UUID path, unchanged)
           ▼
┌───────────────────────────────────────────┐
│  GET /projects/{id}/download              │  (NEW)
│  - resolve path from DB by id only        │
│  - FileResponse(path, media_type=lookup[fmt],
│    filename=f"{sanitized_name}.{fmt}")    │
└──────────┬─────────────────────────────────┘
           │ 5. browser download, correct extension/Content-Type
           ▼
      [ user's downloaded file ]
```

### Recommended Project Structure

No new files. All changes land in existing files:
```
backend/app/
├── config.py           # _ALLOWED_OUTPUT_FORMATS widened; OUTPUT_FORMAT env default reconsidered (Pitfall 7)
├── models.py            # Project gains output_format: str, output_filename: str | None
├── db.py                 # _NEW_COLUMNS["project"] gains the two new columns (additive migrator, same as tts_model)
├── audio_join.py         # join_wavs' codec_args becomes an explicit {flac,mp3,opus} dict, no else
├── generation_worker.py  # _join_project reads project.output_format/output_filename instead of settings.OUTPUT_FORMAT; D-07 unlink-old-output-first
└── main.py                # _serialize_project exposes new fields; new PATCH /projects/{id}; new GET /projects/{id}/download

frontend/src/
├── api/client.ts          # Project interface gains output_filename; new patchProjectConfig()/downloadUrl() helpers
└── components/ConfigPanel.tsx  # Format <Select> (replaces read-only ConfigField), Filename <input>, Download <Button>
```

### Pattern 1: Per-project config column, following the Phase 5 `tts_model` precedent exactly

**What:** A new setting that must vary per-project (not read from ambient global `Settings`) is added as a `Project` column, exposed via `_serialize_project`, and read live at generate/join time — never cached in a closure or read once at process start.
**When to use:** Any config choice (format, filename, model) that could legitimately differ between two projects running in the same backend process.
**Example:**
```python
# Source: backend/app/models.py (existing tts_model column, Phase 5 CFG-04)
class Project(SQLModel, table=True):
    ...
    tts_model: str = "1.7b"
    # Phase 6 additions, same pattern:
    # output_format: str = "mp3"
    # output_filename: str | None = None
```
```python
# Source: backend/app/db.py — additive, idempotent column migrator (existing)
_NEW_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "project": [
        ("created_at", "TEXT"),
        ("output_path", "TEXT"),
        ("tts_model", "TEXT DEFAULT '1.7b'"),
        # Phase 6 additions:
        # ("output_format", "TEXT DEFAULT 'mp3'"),
        # ("output_filename", "TEXT"),
    ],
}
```

### Pattern 2: Explicit format → (codec_args, content_type, extension) mapping, no catch-all

**What:** Replace the current `if fmt == "wav": ... else: ...` two-way branch with an explicit dict covering exactly the three supported formats. An unrecognized format raises immediately — mirrors `config.py`'s existing "fail fast at settings-load time" philosophy, just moved to request time since format is no longer settings-load-time-fixed.
**When to use:** Any place format-specific behavior branches (encode args, `Content-Type`, file extension) — there are three such places in this codebase (`audio_join.py`, `main.py`'s new download route, `config.py`'s allowlist) and per Pitfall 6 they must move together, atomically.
**Example:**
```python
# Source: .planning/research/STACK.md §(c), verified working during this
# research session (live ffmpeg 7.1.5 encode of a synthetic WAV, zero errors)
CODEC_TABLE = {
    "flac": {
        "codec_args": ["-c:a", "flac", "-compression_level", "8"],
        "content_type": "audio/flac",
    },
    "mp3": {
        "codec_args": ["-c:a", "libmp3lame"],
        "content_type": "audio/mpeg",
    },
    "opus": {
        "codec_args": ["-c:a", "libopus", "-b:a", "48k", "-vbr", "on", "-application", "voip"],
        # VERIFIED this session: ffmpeg's `-f opus` muxer actually produces
        # an Ogg container (ffprobe reports format_name=ogg for a `.opus`
        # output) — audio/ogg is the IANA/RFC-7845-correct Content-Type for
        # Ogg-Opus, NOT audio/opus (a distinct, rarely-supported raw type).
        # Python's own `mimetypes.guess_type("x.opus")` independently
        # confirms this: returns ('audio/ogg', None).
        "content_type": "audio/ogg",
    },
}
if fmt not in CODEC_TABLE:
    raise ValueError(f"unsupported output format: {fmt!r}")
codec_args = CODEC_TABLE[fmt]["codec_args"]
# Also force the muxer explicitly so codec/container/filename can never
# disagree (STACK.md): add ["-f", fmt] to the ffmpeg argv, independent of
# out_path's suffix.
```

### Pattern 3: Filename is display-only — never the on-disk path

**What:** `Project.output_filename` (user-editable) is used ONLY for the download route's `Content-Disposition` filename. The actual file on disk keeps the existing `uuid4().hex`-based server-generated path (`_join_project`'s own comment: "Server-generated uuid filename — never derived from any client string (T-03-06)").
**When to use:** Every place a user-editable string reaches a file-serving or file-writing code path.
**Example:**
```python
# Source: backend/app/generation_worker.py (existing pattern, unchanged)
out_path = str(out_dir / f"{uuid.uuid4().hex}.{fmt}")  # NEVER project.output_filename here

# Source: backend/app/main.py, new download route
from fastapi.responses import FileResponse

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
        filename=display_name,  # FileResponse builds the RFC-6266 header for you
    )
```

### Pattern 4: Simple field-set PATCH, no generation lock

**What:** `patch_character` (existing, `backend/app/main.py:555`) is the precedent for a PATCH endpoint with optional fields that only touch DB state, no GPU/generation-lock claim. Format/filename PATCH follows this exact shape — unlike `set_project_model` (which DOES claim `try_claim_generation` because it triggers an actual GPU model swap), format/filename changes are inert until the next Generate All click, so no lock is needed.
**When to use:** Config fields that are *read* at generation time but don't themselves trigger any generation-adjacent side effect.
**Example:**
```python
# Source: backend/app/main.py:548-556 (existing CharacterPatch/patch_character), adapted
class ProjectConfigPatch(BaseModel):
    output_format: str | None = None
    output_filename: str | None = None

@app.patch("/projects/{project_id}")
async def patch_project_config(project_id: str, patch: ProjectConfigPatch) -> dict:
    if patch.output_format is not None and patch.output_format not in CODEC_TABLE:
        raise HTTPException(status_code=422, detail=f"unknown output_format {patch.output_format!r}")
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if patch.output_format is not None:
            project.output_format = patch.output_format
        if patch.output_filename is not None:
            project.output_filename = sanitize_filename(patch.output_filename)
        session.add(project)
        session.commit()
        session.refresh(project)
        characters = list(session.exec(select(Character).where(Character.project_id == project_id)).all())
        segments = list(session.exec(select(Segment).where(Segment.project_id == project_id)).all())
        return _serialize_project(project, characters, segments)
```

### Anti-Patterns to Avoid

- **Widening `_ALLOWED_OUTPUT_FORMATS` without touching `audio_join.py`'s branch and `main.py`'s content-type lookup in the same change (Pitfall 6):** the two-way `if fmt == "wav" ... else ...` treats "mp3" and "not wav" as identical today — adding "flac"/"opus" to the allowlist alone would silently encode a project's chosen Opus output as MP3 bytes wearing an `.opus` extension. Do the format→(codec_args, content_type) mapping as one atomic change across all three call sites.
- **Leaving `config.py`'s `load_settings()` default at `"wav"` after removing wav from the allowlist (Pitfall 7):** `os.environ.get("OUTPUT_FORMAT", "wav")` would make any deployment that doesn't explicitly set `OUTPUT_FORMAT` fail at startup once `"wav"` is no longer in `_ALLOWED_OUTPUT_FORMATS`. Since format is being promoted to a per-project DB column this phase, the cleanest fix is retiring `settings.OUTPUT_FORMAT`/`_ALLOWED_OUTPUT_FORMATS` entirely in favor of a per-project default handled in `models.py`/the PATCH validator — but if `OUTPUT_FORMAT` env var is kept as a bootstrap default for brand-new projects, update its fallback string to `"mp3"` and audit `backend/.env` (gitignored — not directly readable this session) for a stale hardcoded `OUTPUT_FORMAT=wav`.
- **Using the user-editable filename as the on-disk save path (Pitfall 8):** this codebase has two existing comments (`T-03-01`, `T-03-06`) explicitly guarding against exactly this. Keep the server-generated UUID path; the user's string is `Content-Disposition` display-name only.
- **Hand-formatting the `Content-Disposition` header (Pitfall 9):** an embedded `"`, a CRLF sequence, or a non-ASCII character in a hand-built `f'attachment; filename="{name}"'` string corrupts the response. Use `FileResponse`'s `filename=` kwarg — it's RFC-6266-correct out of the box. None of this codebase's existing download-adjacent routes (`get_segment_audio`, `get_character_preview`) set `Content-Disposition` at all today, so there's no in-repo pattern to copy *correctly* by extrapolation — only the wrong one to avoid.
- **Relying on the output filename's extension to pick ffmpeg's muxer:** force `-f {flac,mp3,opus}` explicitly in the `subprocess.run` argv, independent of `out_path`'s suffix, so a mismatched extension can never silently produce the wrong container.
- **Adding a codec "strategy" class/registry for 3 fixed formats:** a plain dict lookup is the whole feature (per D-11 and this project's established "no generic registry for a fixed small set" convention from the Phase 5 model-choice precedent).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| `Content-Disposition` header construction/quoting | A hand-built f-string header | `fastapi.responses.FileResponse(..., filename=...)` | RFC 6266 quoting/UTF-8 fallback already implemented; hand-rolling breaks on embedded quotes, CRLF, non-ASCII (Pitfall 9) |
| Filename sanitization | A general-purpose sanitization library (`pathvalidate`, `python-slugify`) | `re.sub` stripping a small known-bad character set (`/ \ : * ? | " < >` and control chars) | Single-user tool serving its own generated file back to itself — a full library is overkill for stripping ~10 characters; stdlib regex is the correct-size solution here |
| Format→codec/content-type mapping | A codec "strategy" class hierarchy | A plain `dict` literal (3 fixed keys) | Exactly 3 formats, never dynamically extended at runtime — a class hierarchy is speculative generality for a fixed enum |
| Schema migration | Alembic (or any migration framework) | The existing additive-only `_NEW_COLUMNS` migrator in `db.py` | Already the established pattern for every prior phase's new columns (`tts_model`, `output_path`); this project explicitly marks it "ponytail: this is the ceiling; upgrade to Alembic if the project ever needs down-migrations or column renames/drops" — Phase 6 needs neither |

**Key insight:** every piece of this phase already has an established in-repo precedent from Phases 3-5 (per-project column, PATCH-with-optional-fields, additive migrator, format dispatch table). The work is applying those exact patterns to two new fields and one new route — not inventing new mechanisms.

## Common Pitfalls

*(These are the milestone-level pitfalls from `.planning/research/PITFALLS.md`, specific to Phase 6's two capabilities — reproduced here with this session's verification status added.)*

### Pitfall 1 (repo Pitfall 6): FLAC/Opus fall through the existing mp3-shaped `else` branch
**What goes wrong:** `join_wavs`'s current `if fmt == "wav": copy else: libmp3lame` treats any non-wav string as MP3. Adding "flac"/"opus" to `_ALLOWED_OUTPUT_FORMATS` without a matching `elif` produces a file with the wrong codec/container wearing the right extension.
**How to avoid:** One explicit `{"flac": ..., "mp3": ..., "opus": ...}` dict, no catch-all — an unrecognized format raises immediately.
**Status this session:** Verified fix pattern (the dict above) actually encodes correctly for all 3 formats — `ffprobe` confirmed `format_name=flac`/`mp3`/`ogg` respectively with zero ffmpeg errors.

### Pitfall 2 (repo Pitfall 7): Dropping WAV without updating `config.py`'s own default
**What goes wrong:** `load_settings()`'s `os.environ.get("OUTPUT_FORMAT", "wav")` default breaks the app at startup on any deployment without an explicit `OUTPUT_FORMAT` env var, once `"wav"` leaves `_ALLOWED_OUTPUT_FORMATS`.
**How to avoid:** Since format becomes a per-project DB column this phase, plan to retire `settings.OUTPUT_FORMAT` as the source of truth entirely (only keep it, if at all, as the seed default for a fresh project's `output_format` column) — and audit `deploy/qwen-ebook-backend.container` + `backend/.env` for a stale reference.
**Status this session:** Confirmed the Quadlet unit (`deploy/qwen-ebook-backend.container`) does NOT hardcode `OUTPUT_FORMAT` today (only `TTS_BACKEND`, `TTS_SERVICE_URL`, `DATABASE_URL`, `UPLOAD_DIR`, `OUTPUT_DIR`, `LOG_LEVEL` are set) — one less place to audit. `backend/.env` is gitignored and this session's Bash tool was denied permission to read it directly; the planner/executor should grep it for `OUTPUT_FORMAT` before removing the setting entirely.

### Pitfall 3 (repo Pitfall 8): Using the editable filename as the on-disk path
**What goes wrong:** Reopens the exact path-traversal/collision class this codebase has twice explicitly guarded against elsewhere (`T-03-01`, `T-03-06`).
**How to avoid:** Server-generated UUID path always; `output_filename` is `Content-Disposition`-only.
**Status this session:** No new verification needed — this is a design discipline, not a technical unknown; the plan-checker should specifically grep for `output_filename` landing inside any `Path(...)` construction used for a write.

### Pitfall 4 (repo Pitfall 9): Hand-formatted `Content-Disposition` header
**What goes wrong:** An f-string header breaks on embedded quotes/CRLF/non-ASCII.
**How to avoid:** `FileResponse(..., filename=...)`.
**Status this session:** Confirmed `fastapi==0.139.0` (already pinned) ships `fastapi.responses.FileResponse` re-exporting Starlette's implementation, which handles this correctly — no version concern.

### Pitfall 5 (new this session): Opus's Content-Type is `audio/ogg`, not `audio/opus`
**What goes wrong:** CONTEXT.md's D-08 lists `audio/opus or audio/ogg` as open options. Setting `Content-Type: audio/opus` for a `.opus` file is a real, easy mistake — the name matches, but it's the wrong IANA type for ffmpeg's actual output container.
**Why it happens:** ffmpeg's `-f opus` muxer (and the `.opus` file extension convention) both suggest "opus" is the container name, but it's actually muxed as Ogg (RFC 7845, "Ogg Opus"). `audio/opus` exists as a distinct, much-less-supported raw-Opus MIME type.
**How to avoid:** Use `audio/ogg` as the `Content-Type` for the Opus output — confirmed both by a live `ffprobe -show_entries format=format_name` (`ogg`) on this session's own test-encoded file, and independently by Python's stdlib `mimetypes.guess_type("x.opus")` → `('audio/ogg', None)`.
**Warning signs:** A browser or player rejects/mishandles a `.opus` download served with `Content-Type: audio/opus` while the identical bytes play fine when served as `audio/ogg`.

## Code Examples

### Verified codec + muxer flags (live ffmpeg 7.1.5 run, this session)
```bash
# FLAC — lossless, -compression_level trades encode time for size only
ffmpeg -y -i in.wav -c:a flac -compression_level 8 -f flac out.flac
# Result: Stream #0:0: Audio: flac, 24000 Hz, mono, s16, 128 kb/s — no errors

# MP3 — unchanged from existing audio_join.py behavior
ffmpeg -y -i in.wav -c:a libmp3lame -f mp3 out.mp3
# Result: Stream #0:0: Audio: mp3 — no errors

# Opus — voip application mode favors speech intelligibility over music fidelity
ffmpeg -y -i in.wav -c:a libopus -b:a 48k -vbr on -application voip -f opus out.opus
# Result: Output #0, opus, to 'out.opus' / Stream #0:0: Audio: opus, 24000 Hz, mono, s16, 48 kb/s
# ffprobe format_name for this file: "ogg" (confirms Content-Type should be audio/ogg)
```

### `PATCH /characters/{character_id}` — the exact precedent for the new project-config PATCH
```python
# Source: backend/app/main.py:548-556 (existing, verified by direct read)
class CharacterPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    voice_preset: str | None = None
    voice_instructions: str | None = None

@app.patch("/characters/{character_id}")
async def patch_character(character_id: str, patch: CharacterPatch) -> dict:
    with Session(engine) as session:
        character = session.get(Character, character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Character not found")
        if patch.name is not None:
            character.name = patch.name
        # ... one `if patch.X is not None` per field ...
        session.add(character)
        session.commit()
        session.refresh(character)
        return _serialize_character(character)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `settings.OUTPUT_FORMAT` (global env var, `{"wav", "mp3"}` allowlist) | `Project.output_format` (per-project DB column, `{"flac", "mp3", "opus"}` allowlist) | This phase | Two projects in the same running backend can now use different output formats; format choice becomes part of project state, not process state |
| No download endpoint (output only reachable by inspecting `output_path` on disk) | `GET /projects/{id}/download` with `Content-Disposition: attachment` | This phase | User gets a real one-click download UX with the correct filename/extension, matching browsers' native save-file flow |

**Deprecated/outdated:**
- WAV as a selectable output format: explicitly dropped per REQUIREMENTS.md v1.1 (CFG-06) and CONTEXT.md's Out of Scope. Note per STACK.md: don't scrub WAV support from `audio_join.py`'s function signature/tests — only remove it from `_ALLOWED_OUTPUT_FORMATS`/the UI dropdown; segment/character preview audio legitimately stays WAV internally (D-14).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `backend/.env` does not contain a hardcoded `OUTPUT_FORMAT=wav` that would need updating alongside `config.py`'s default | Common Pitfalls (Pitfall 2) | Low — this session's Bash tool was denied permission to read `.env` directly (expected, it's gitignored/secrets-adjacent); if it does contain a stale value, the fix is a one-line edit, not a design change. Planner/executor should `grep OUTPUT_FORMAT backend/.env` before removing `settings.OUTPUT_FORMAT` as the fallback source. |
| A2 | `audio/ogg` (not `audio/opus`) is the correct `Content-Type` for the ffmpeg-produced `.opus` file | Common Pitfalls (Pitfall 5), Pattern 2 | Low — cross-verified two independent ways this session (live `ffprobe` on an actual encoded file, and Python's stdlib `mimetypes.guess_type`), both agree; this is settled, not speculative |

**Both assumptions above are LOW risk and independently cross-checked** — nothing in this research needs user confirmation before becoming a locked planning decision. D-09's actual open question (codec availability) is resolved with `[VERIFIED]` confidence, not merely assumed.

## Open Questions

1. **Should `output_filename`'s default (D-05, "derive from original upload filename's stem") strip a pre-existing extension from the upload filename, or from the project's `filename` field verbatim?**
   - What we know: `Project.filename` stores the original upload name (e.g., `"book.epub"`), verified by reading `models.py`/`main.py`'s upload handler.
   - What's unclear: whether `"book.epub"` → default output filename `"book"` (stem only) or `"book.epub"` (verbatim, then the format extension gets appended making `"book.epub.mp3"` — clearly wrong). CONTEXT.md D-05's own example (`book.epub → "book"`) already answers this — stem only, strip any existing extension via `Path(project.filename).stem`.
   - Recommendation: Use `Path(project.filename).stem` as the D-05 default; this is a one-line stdlib call, not an open design question in practice — flagging here only so the planner writes it explicitly rather than reinventing it in a task.

2. **Exact behavior when the user's typed filename already includes an extension (CONTEXT.md's own "Claude's Discretion" item)?**
   - What we know: D-04 sanitizes strictly and shows the final name immediately; the backend always appends the canonical extension for the *currently selected* format at serve time (per Pitfall 8's guidance — "normalize/ensure it carries the correct extension for the currently-configured format so a user can't rename a `.flac` file to display as `.mp3`").
   - What's unclear: whether to strip a user-typed `.mp3` before appending the real extension, or leave it and produce `"my-book.mp3.flac"`.
   - Recommendation: Strip any extension the user types (`Path(name).stem` at sanitize time) and always append the format-derived extension at serve time — never trust the user's typed extension to match their format selection, since the Format dropdown and Filename field are edited independently and can disagree at any point before Generate is clicked.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `ffmpeg` (system binary, with `libopus`/`libmp3lame`/native `flac`) | CFG-06 codec dispatch | ✓ (verified this session on Debian 13 trixie, matching `Containerfile.backend`) | 7.1.5-0+deb13u1 | — |
| `fastapi.responses.FileResponse` | CFG-08 download endpoint | ✓ (ships with pinned `fastapi==0.139.0`) | bundled | — |
| SQLite additive column migration (`db.py`'s `_NEW_COLUMNS`) | CFG-06/07 schema change | ✓ (existing mechanism, already used for `tts_model`) | — | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — every dependency this phase needs is already present and verified working.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Tailscale is the sole access boundary (CLAUDE.md); no auth layer in this app |
| V3 Session Management | No | No session concept in this single-user app |
| V4 Access Control | No | Single-tenant; every route is already reachable by the one trusted user |
| V5 Input Validation | Yes | Format value validated against a fixed allowlist (`CODEC_TABLE` keys) before reaching ffmpeg; filename sanitized (strip path separators/control chars) before persisting, following the `patch_character`/`SegmentPatch` precedent of Pydantic-typed optional fields |
| V6 Cryptography | No | No new cryptographic surface in this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via user-supplied filename reaching a filesystem write | Tampering | Never construct the on-disk path from `output_filename` — keep the existing server-generated UUID path scheme (Pitfall 8); this is a design discipline already established twice elsewhere in this codebase (`T-03-01`, `T-03-06`) |
| HTTP header injection via CRLF/quotes in a hand-built `Content-Disposition` header | Tampering | Use `FileResponse`'s `filename=` kwarg — never hand-format the header string (Pitfall 9) |
| Download route resolving an arbitrary path instead of the DB-owned `output_path` | Information Disclosure | Mirror `get_segment_audio`/`get_character_preview`'s existing discipline: resolve the served path only via `session.get(Project, project_id).output_path`, never from any client-supplied path/filename text |
| Unrecognized/malformed `output_format` value reaching ffmpeg | Tampering / Denial of Service (malformed subprocess args) | Validate against the fixed `{"flac","mp3","opus"}` allowlist at the PATCH boundary (422 on rejection) — same fail-fast philosophy `config.py` already uses for `OUTPUT_FORMAT` |

## Sources

### Primary (HIGH confidence)
- Direct execution in this research session: `ffmpeg -version`, `ffmpeg -codecs`, `ffmpeg -encoders`, and three live encode round-trips (WAV→FLAC/MP3/Opus) plus `ffprobe -show_entries format=format_name` on a Debian 13 (trixie) host matching the deploy VM's OS and the project's own `Containerfile.backend` install line (`apt-get install -y --no-install-recommends ffmpeg`) — `[VERIFIED]`, resolves CONTEXT.md D-09.
- Direct read of `backend/app/{audio_join.py, generation_worker.py, models.py, db.py, config.py, main.py}`, `frontend/src/{api/client.ts, components/ConfigPanel.tsx}`, `deploy/qwen-ebook-backend.container` — `[VERIFIED: repo source]`.
- Python 3.12 stdlib `mimetypes.guess_type()` output for `.mp3`/`.flac`/`.opus`/`.ogg` extensions, run this session — `[VERIFIED]`.

### Secondary (MEDIUM confidence)
- `.planning/research/ARCHITECTURE.md` (Capability 3/4), `.planning/research/PITFALLS.md` (Pitfalls 6-10), `.planning/research/STACK.md` (§(c) FLAC/Opus) — the milestone-level research pass done before the v1.1 roadmap was written; cross-checked against this session's own direct verification and found accurate on every point it could re-check.
- WebSearch, cross-checked: "correct MIME type for .opus / Ogg Opus files" — confirms `audio/ogg; codecs=opus` (RFC 7845) is IANA/spec-correct, matching this session's own `ffprobe`/`mimetypes` findings independently.

### Tertiary (LOW confidence)
- None — every claim in this document was either directly verified this session or cross-checked against the existing, already-reviewed milestone research.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; every existing package/binary version directly confirmed in this session or already pinned in `pyproject.toml`
- Architecture: HIGH — every pattern (per-project column, PATCH-with-optional-fields, additive migrator, format dispatch) has a working precedent already in this exact codebase (Phases 3/5)
- Pitfalls: HIGH — sourced from the project's own pre-existing, detailed milestone research pass (PITFALLS.md), which this session's direct ffmpeg verification confirmed rather than contradicted
- Codec availability (D-09 spike): HIGH — directly verified via live command execution and live encode round-trips, not assumed or cited from documentation

**Research date:** 2026-07-15
**Valid until:** Stable for the remaining lifetime of this deploy VM's OS (Debian 13 trixie) and `ffmpeg` package version; re-verify only if the base OS/ffmpeg package is upgraded.

## Project Constraints (from CLAUDE.md)

- **Podman, not Docker** — no relevance to this phase's code changes, but any deploy-step note (e.g., rebuilding the backend image) must stay Podman/Quadlet-shaped.
- **Lint gate (required):** after any major Python change, run `cd backend && uv run ruff check .` and fix all warnings (strict `E, F, I, UP, B`) before committing — applies to every file this phase touches (`audio_join.py`, `config.py`, `models.py`, `db.py`, `generation_worker.py`, `main.py`).
- **No `noqa` directives** in non-test code without a justifying comment — none of this phase's changes are expected to need one.
- **Logging, not `print()`:** any new debug/error output in the new PATCH/download routes and the extended `join_wavs` must go through `logging.getLogger(__name__)`, with f-string interpolation per the F-strings convention.
- **No pydub** for the join path — already honored; this phase only extends the existing `ffmpeg subprocess.run` call, never introduces pydub.
- **ffmpeg as an OS package inside the container image, not pip** — already true (`Containerfile.backend`); no change needed since codec support is already present in the installed build (verified this session).
