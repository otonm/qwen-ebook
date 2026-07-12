---
phase: 03-editable-table-full-generation-pipeline-persistence-deployme
reviewed: 2026-07-12T00:00:00Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - backend/Containerfile.backend
  - backend/app/cache_key.py
  - backend/app/db.py
  - backend/app/generation_worker.py
  - backend/app/main.py
  - backend/app/models.py
  - backend/tests/test_config.py
  - backend/tests/test_generation.py
  - backend/tests/test_wizard_endpoints.py
  - deploy/README.md
  - deploy/qwen-ebook-backend.container
  - deploy/qwen-ebook-tts.container
  - deploy/qwen-ebook.pod
  - deploy/run-local.sh
  - frontend/src/App.tsx
  - frontend/src/api/client.ts
  - frontend/src/components/ConfigPanel.tsx
  - frontend/src/components/ProjectListScreen.tsx
  - frontend/src/components/ProjectScreen.tsx
  - frontend/src/components/SegmentTable.tsx
  - frontend/src/components/ui/checkbox.tsx
  - frontend/src/hooks/useAnalysisStream.ts
  - frontend/src/hooks/useGenerationStream.ts
findings:
  critical: 1
  warning: 6
  info: 4
  total: 11
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-07-12T00:00:00Z
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Reviewed the full generation pipeline (per-segment cache-key generation,
resumable batch generation, cancel), persistence (SQLModel + additive column
migrator), and the Podman/Quadlet deployment story, plus the segment table
and config-panel frontend that drives them.

The core content-hash caching design (`cache_key.py` + `regenerate_segment`'s
live recompute) is sound and the last-request-wins version guards
(`generation_version`/`voice_version`) are applied consistently everywhere
they're needed **except** one important place: the batch generation loop's
"skip if already complete" optimization trusts `generation_status ==
"complete"` as a proxy for cache validity, but three separate code paths
(bulk-reassign, character merge, character voice-preset edit) change a
segment's effective voice **without** resetting that status flag. That is a
real, traceable correctness bug (CR-01 below) — it will silently ship
wrong-voice audio in the joined output whenever a user reassigns/merges after
already having generated once and then runs "Generate All" instead of
manually re-triggering each affected row.

Beyond that, there's a cluster of validation gaps at trust-boundary
endpoints (`patch_segment`'s unchecked `character_id`, `undo_merge_character`
trusting an entirely client-supplied snapshot) that are lower severity given
the single-trusted-user/Tailscale-only threat model, but are still real gaps
relative to the validation the sibling endpoints (`bulk_reassign_segments`,
`merge_character`) already do. On the frontend, error handling for failed
PATCH/POST calls is largely absent (unhandled promise rejections, no
user-facing failure feedback), and one preview-generation UI state can get
permanently stuck.

## Critical Issues

### CR-01: Reassigning a segment's character doesn't invalidate its cached audio — "Generate All" then ships stale, wrong-voice audio

**Files:**
- `backend/app/main.py:760-793` (`bulk_reassign_segments`)
- `backend/app/main.py:467-527` (`merge_character`, segment-reassignment loop at 500-506)
- `backend/app/main.py:298-341` (`patch_character` — voice-preset/instructions edit)
- `backend/app/generation_worker.py:180-201` (`run_batch_generation`'s skip-if-complete optimization)

**Issue:** The GEN-02 cache-key design is `(resolved_speaker, voice_instructions, text, model_version)` — `resolved_speaker` is derived from the assigned character's `voice_preset` (`_resolve_segment_speaker`, `main.py:637-649`). Three endpoints change what "resolved speaker" a segment will use on its *next* generation, but none of them reset the row's `generation_status`/`audio_path`/`cache_key` the way `patch_segment` does when `character_id` changes (`main.py:611-621`):

- `bulk_reassign_segments` only sets `segment.character_id` and bumps `generation_version` (main.py:787-791) — it never clears `audio_path`/`generation_status`.
- `merge_character` only sets `segment.character_id = target_id` for every reassigned segment (main.py:504-506) — it doesn't even bump `generation_version`.
- `patch_character` bumps `character.voice_version` and regenerates that character's *preview* clip (main.py:326-338), but never touches any segment currently assigned to that character.

In isolation this would still self-heal, because `regenerate_segment` always recomputes the cache key live from current DB state (Pitfall 3) and would see a genuine cache miss once the speaker changed. But `run_batch_generation`'s per-segment loop short-circuits *before* ever calling `regenerate_segment`:

```python
# generation_worker.py:180-189
if (
    segment.generation_status == "complete"
    and segment.audio_path
    and Path(segment.audio_path).is_file()
):
    # Optimization only, not a correctness requirement:
    # regenerate_segment below would no-op via its own live
    # cache-key recompute anyway (Pitfall 3); skipping here
    # just avoids a spurious "generating" progress blip for
    # an already-good row.
    ...
    continue
```

The comment's claim ("would no-op via its own live cache-key recompute
anyway") is false for exactly the scenarios above: `regenerate_segment` is
never called in this branch, so its live recompute never runs. The loop
treats `generation_status == "complete" and file exists` as sufficient proof
the cached audio is still valid, but that invariant is violated the moment a
segment's character (and therefore its resolved speaker) changes through any
path that doesn't also reset `generation_status`.

**Concrete failure sequence:**
1. Generate a project once — every segment is `"complete"` with an audio file.
2. Bulk-reassign (or merge) segment 5 onto a character with a different voice, or edit that character's `voice_preset`.
3. Click "Generate All" (`POST /projects/{id}/generate`).
4. Segment 5 is skipped by the optimization above (still `"complete"`, file still exists) — it keeps the **old character's voice**.
5. The batch join (`_join_project`) stitches this stale file into the final output with no error, no warning, and no UI indication that segment 5 needs regeneration.

The only way to get correct audio after a reassignment/merge/voice-edit today is to manually click the per-row Generate/Play button on every affected segment — nothing in the UI communicates that this is required, and `test_bulk_reassign_updates_all_rows`/`test_bulk_reassign_bumps_generation_version` (`backend/tests/test_generation.py:248-289`) don't assert on `generation_status`/`audio_path`, so this regression has no test coverage either.

**Fix:** Apply the same invalidation `patch_segment` already does whenever a
segment's effective character changes, in all three places:

```python
# bulk_reassign_segments — inside the `for segment in segments:` loop
for segment in segments:
    segment.character_id = target.id
    segment.generation_version += 1
    segment.generation_status = "pending"
    segment.generation_error = None
    if segment.audio_path:
        Path(segment.audio_path).unlink(missing_ok=True)
        segment.audio_path = None
    session.add(segment)

# merge_character — inside the segment-reassignment loop
for segment in segments:
    segment.character_id = target_id
    segment.generation_version += 1
    segment.generation_status = "pending"
    segment.generation_error = None
    if segment.audio_path:
        Path(segment.audio_path).unlink(missing_ok=True)
        segment.audio_path = None
    session.add(segment)

# patch_character — after bumping character.voice_version, invalidate every
# segment currently assigned to this character (same pattern, queried by
# character_id) before returning.
```

Alternatively (smaller diff, fixes the root cause once): make
`run_batch_generation`'s skip decision itself cache-key-aware instead of
trusting `generation_status` — i.e. always call `regenerate_segment` and let
its own live recompute decide whether to skip synthesis, removing the
duplicated (and now provably incorrect) heuristic from the batch loop
entirely. That also removes the need to fix three call sites individually,
since the loop would only ever skip a *genuinely* unchanged segment.

## Warnings

### WR-01: `undo_merge_character` trusts a fully client-supplied snapshot with no ownership/consistency validation

**File:** `backend/app/main.py:530-577`
**Issue:** `merge_character` and `bulk_reassign_segments` both validate that
segments belong to the same project as the target character before mutating
anything (`main.py:482`, `782-785`). `undo_merge_character` does not: it
recreates a `Character` row directly from client-supplied fields (`id`,
`project_id`, etc.) and reassigns `body.segment_ids` to it with no check that
those segments belong to `character.project_id`, or that `project_id` even
refers to a real project. Since this is a public POST endpoint (not just
"whatever the frontend happens to send back"), a malformed or crafted request
body can fabricate a character in an arbitrary project and reassign arbitrary
segment ids onto it — silently corrupting unrelated projects' data.
**Fix:** Before reassigning, verify every id in `body.segment_ids` currently
resolves to a `Segment` whose `project_id == body.character.project_id` (same
check `bulk_reassign_segments` already performs), and 404/400 otherwise.

### WR-02: `patch_segment` accepts any `character_id` with no existence/ownership check

**File:** `backend/app/main.py:580-634`
**Issue:** `SegmentPatch.character_id` is written straight to
`segment.character_id` (line 606) with no lookup. Compare to
`bulk_reassign_segments`, which validates both that the target character
exists (404) and belongs to the same project (400). SQLite's foreign keys are
never enabled (`backend/app/db.py:29-34` has no `PRAGMA foreign_keys=ON`), so
this isn't caught at the DB layer either — a bad `character_id` silently
leaves the segment pointing at nothing, degrading to `character_name: null`
in `_serialize_segment` and a `best_guess_preset` fallback speaker in
`_resolve_segment_speaker` rather than erroring.
**Fix:** Look up the character by id inside `patch_segment` and 404 (or 400
if it belongs to a different project) before assigning, mirroring
`bulk_reassign_segments`'s check.

### WR-03: `run-local.sh` publishes the backend port without binding to loopback

**File:** `deploy/run-local.sh:65`
**Issue:** `${PODMAN} pod create --name "${POD_NAME}" -p "${BACKEND_HOST_PORT}:8000"` omits a host IP, so Podman (like Docker) defaults to binding `0.0.0.0` — the port is reachable from any interface on the dev host's network, not just loopback. This directly contradicts the project's stated network model ("no public internet exposure... single trusted user/network", `deploy/README.md` and `deploy/qwen-ebook.pod:17-19`, whose Quadlet unit explicitly uses `PublishPort=127.0.0.1:8000:8000`). On a dev host connected to a shared/untrusted LAN, this exposes the unauthenticated backend beyond the intended boundary.
**Fix:** `-p "127.0.0.1:${BACKEND_HOST_PORT}:8000"` to match the Quadlet unit's loopback-only guarantee.

### WR-04: `cancel_generation` can leak a permanently un-drained progress queue on a narrow race

**File:** `backend/app/main.py:846-883`, `backend/app/generation_worker.py:48-49, 63-70`
**Issue:** If the batch task finishes (pushes its own terminal event and is
removed from `_running_generations` via the done-callback) in the window
between `get_generation_task(project_id)` returning it and `task.cancel()`
being called, `cancel()` is a no-op and `await task` returns normally instead
of raising `CancelledError`. Execution then falls through to unconditionally
push `("done", {"status": "cancelled"})` via `push_generation_event`, which
re-creates a fresh entry in `_generation_progress_queues` (since the real run
already popped and removed the old one on its own terminal event). Nothing
will ever drain this new entry — a permanent dict-entry leak, and a
misleading "cancelled" status if a client ever reconnects to the stream for
this project.
**Fix:** Re-check `is_generation_running(project_id)` (or re-fetch
`get_generation_task`) after `await task` and only push the synthetic
`"cancelled"` event if the task was actually still running/was actually
cancelled (e.g. compare `task.cancelled()`).

### WR-05: Preview-generation button can get stuck in a permanent loading state

**File:** `frontend/src/components/ConfigPanel.tsx:38-66, 78-86`
**Issue:** `isTriggeringPreview` is set `true` in `handleGeneratePreview`
(line 79) and is only ever reset to `false` in the `catch` block, which only
fires if the `triggerCharacterPreview` fetch itself throws (line 83-85). The
comment at lines 49-51 asserts this is safe because `hasPreview` flipping
true unmounts the button — true when generation *succeeds*, but if the
backend's fire-and-forget `_generate_preview` fails or silently never
completes (e.g. TTS error, `main.py:374-381`'s broad except), `hasPreview`
never becomes true. The bounded poll (`setTimeout` at line 61) stops
*polling* after 15s but never resets `isTriggeringPreview`, so
`isGeneratingPreview` (line 52) stays `true` forever, and the "Generate
preview" button (disabled while `isGeneratingPreview`) is stuck showing a
spinner with no way to retry short of a full page reload.
**Fix:** In the timeout callback (or the effect's cleanup once the timeout
fires without `hasPreview` becoming true), also `setIsTriggeringPreview(false)` so the button becomes clickable again.

### WR-06: Widespread missing error handling on PATCH/POST calls in the segment table and config panel

**Files:**
- `frontend/src/components/SegmentTable.tsx:184` (`NarratorCell.handleChange`)
- `frontend/src/components/SegmentTable.tsx:231-234` (`EditableTextCell.handleBlur`)
- `frontend/src/components/SegmentTable.tsx:111-130` (`GeneratePlayButton.handleClick`)
- `frontend/src/components/SegmentTable.tsx:263-272` (`BulkReassignToolbar.handleConfirm`)
- `frontend/src/components/ConfigPanel.tsx:170-187` (`handleGenerateAll`/`handleStop`)

**Issue:** None of these call sites attach a `.catch()`/`catch` block around
the network call. They're invoked as `void handleX()` from `onClick`/`onBlur`
handlers, so a failed request (e.g. 404/409/500, or the network dropping)
produces an unhandled promise rejection with no user-facing feedback — the UI
either silently does nothing (`NarratorCell`, `EditableTextCell`, which never
call `onSegmentChange` on failure, leaving the row looking unchanged with no
explanation) or resets a loading flag via `finally` with no indication
anything went wrong (`GeneratePlayButton`, `BulkReassignToolbar`,
`ConfigPanel`'s generate/stop buttons).
**Fix:** Add a `.catch()`/`try/catch` at each of these sites that surfaces a
visible error (toast, inline message, etc.) rather than letting the
rejection go unhandled.

## Info

### IN-01: Unpinned `uv` install in the backend image

**File:** `backend/Containerfile.backend:35`
**Issue:** `RUN pip install --no-cache-dir uv` installs whatever the latest
`uv` release is at build time, contrary to this project's own stated
convention of pinning exact versions for fast-moving tooling (CLAUDE.md /
this file's own comment about `qwen-tts`). A future `uv` release with
behavior changes could silently break reproducible builds.
**Fix:** Pin a version, e.g. `pip install --no-cache-dir "uv==<version>"`.

### IN-02: Cross-module mutation of a "private" registry dict

**File:** `backend/app/main.py:46, 833, 838-839`; `backend/app/generation_worker.py:45`
**Issue:** `generation_worker._running_generations` is named with a leading
underscore (module-private convention) but is imported and mutated directly
from `main.py` (`_running_generations[project_id] = task`, `.discard(...)`,
`.pop(...)`), alongside the module's own accessor functions
(`is_generation_running`, `get_generation_task`) that exist for exactly this
purpose. This is a minor encapsulation leak — a future refactor of the
registry's internal shape in `generation_worker.py` would need to also chase
down this direct access in `main.py`.
**Fix:** Add a small `register_generation_task(project_id, task)` /
`unregister_generation_task(project_id, task)` pair in `generation_worker.py`
and have `main.py` call those instead of touching the dict directly.

### IN-03: PATCH endpoints can't express "clear this field"

**File:** `backend/app/main.py:298-303` (`CharacterPatch`), `580-584` (`SegmentPatch`)
**Issue:** Both patch models default every field to `None`, and both
handlers only apply a field `if patch.X is not None`. This means an explicit
`{"voice_preset": null}` in the request body is indistinguishable from
omitting the field entirely — there is no way to null out `voice_preset`,
`voice_instructions`, or `text` via these endpoints. Currently masked because
the frontend always sends `""` rather than `null` for "no preset", but it's a
latent API limitation.
**Fix:** Not urgent given current usage; if ever needed, switch to a sentinel
(`exclude_unset=True` + explicit "was this key present in the body" check)
rather than relying on `is not None`.

### IN-04: `_join_project` has no explicit handling for a zero-segment project

**File:** `backend/app/generation_worker.py:93-114`
**Issue:** If a project somehow has zero segments, `missing` and `wav_paths`
are both empty lists, and `join_wavs([], out_path, settings.OUTPUT_FORMAT)`
is invoked unconditionally, with `project.output_path` then set to whatever
that call produces (empty/invalid audio file, since `audio_join.py` isn't in
this review's scope its exact behavior on an empty list wasn't verified
here). Worth an explicit guard/clear error rather than relying on
`join_wavs`'s own behavior for this input.
**Fix:** `if not wav_paths: raise RuntimeError("No segments to join")` before
calling `join_wavs`.

---

_Reviewed: 2026-07-12T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
