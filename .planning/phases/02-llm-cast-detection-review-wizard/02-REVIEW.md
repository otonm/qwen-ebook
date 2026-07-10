---
phase: 02-llm-cast-detection-review-wizard
reviewed: 2026-07-10T00:00:00Z
depth: standard
files_reviewed: 27
files_reviewed_list:
  - backend/.gitignore
  - backend/Containerfile.backend
  - backend/app/analysis_client.py
  - backend/app/analysis_worker.py
  - backend/app/config.py
  - backend/app/db.py
  - backend/app/epub_parser.py
  - backend/app/main.py
  - backend/app/models.py
  - backend/app/schemas.py
  - backend/app/token_estimate.py
  - backend/pyproject.toml
  - backend/tests/fixtures/__init__.py
  - backend/tests/fixtures/epub_builder.py
  - backend/tests/test_analysis_pipeline.py
  - backend/tests/test_analysis_reconciliation.py
  - backend/tests/test_e2e.py
  - backend/tests/test_epub_parser.py
  - backend/uv.lock
  - frontend/package.json
  - frontend/src/App.tsx
  - frontend/src/api/client.ts
  - frontend/src/components/CastWizard.tsx
  - frontend/src/components/CharacterCard.tsx
  - frontend/src/components/SegmentPreview.tsx
  - frontend/src/components/UploadScreen.tsx
  - frontend/src/hooks/useAnalysisStream.ts
  - frontend/src/main.tsx
  - frontend/vite.config.ts
findings:
  critical: 2
  warning: 6
  info: 2
  total: 10
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 27 (2 were empty/trivial: `backend/tests/fixtures/__init__.py`, `backend/uv.lock` scanned only for supply-chain anomalies)
**Status:** issues_found

## Summary

Reviewed the Phase 2 (cast detection + review wizard) backend (analysis client/worker, EPUB parsing, FastAPI endpoints, models/schemas) and frontend (SSE progress hook, upload screen, cast wizard, character card, segment preview). The prompt-injection mitigation (system/user role separation), the mock/real LLM backend isolation, and the multi-chunk reconciliation logic are all solid and match their documentation.

Two issues are Critical:
1. The EPUB upload path bounds only the *compressed* upload size, not the decompressed size — the code's own docstring claims this guards against zip bombs, but `ebooklib`/`zipfile.ZipFile.read()` has no size cap, so a small malicious `.epub` can still exhaust memory.
2. The only voice preset currently shipped (`""`, "Default narrator (auto-selected)") is written back to the DB as the literal string `""` whenever a user interacts with the (single-item) preset dropdown, which — because `_generate_preview` only falls back to `best_guess_preset()` when `voice_preset is None`, not when it's an empty string — permanently defeats the best-guess voice selection and sends an empty `speaker` straight to the real TTS backend for that character.

Several warnings cover SSE lifecycle robustness (both the browser `EventSource` client and the backend's per-project progress queue), a silently-dropped-segment code path with no logging, and a persisted-but-unused `order` field.

## Critical Issues

### CR-01: EPUB decompression is unbounded — upload size cap does not prevent a zip-bomb DoS

**File:** `backend/app/epub_parser.py:19-21`, `backend/app/main.py:76-98`
**Issue:** `_read_upload_bounded` (main.py) only bounds the *compressed* bytes read from the HTTP request body (`MAX_UPLOAD_BYTES`, default 10 MiB). `epub_parser.py`'s own module docstring explicitly claims this is "what guards against a zip-bomb (T-02-04)" — but bounding compressed size does nothing to bound decompressed size. `extract_text()` calls `ebooklib.epub.read_epub()`, which internally does `zipfile.ZipFile(..., allowZip64=True)` and `self.zf.read(name)` for every spine item, with no size limit at all. A crafted `.epub` well within the 10 MiB compressed cap (a single highly-repetitive XHTML file, DEFLATE can reach ~1000:1) can expand to multiple GB in memory during `epub.read_epub()`/`BeautifulSoup(item.content, ...)`, before this module's own `_MIN_NARRATIVE_CHARS`/non-narrative filtering ever runs. This is a real, self-hosted-service DoS vector (memory exhaustion), not merely a theoretical one — verified `ebooklib.epub.EpubReader.read_file` calls `self.zf.read(name)` unbounded.

**Fix:** Cap decompressed size, e.g. sum `ZipInfo.file_size` across the archive (available without decompressing) and reject if it exceeds a sane multiple of `MAX_UPLOAD_BYTES`, and/or read each entry through a bounded wrapper that raises once a per-item/cumulative decompressed threshold is exceeded:
```python
import zipfile

def _check_decompressed_size(epub_bytes: bytes, max_ratio: int = 100) -> None:
    with zipfile.ZipFile(BytesIO(epub_bytes)) as zf:
        total = sum(info.file_size for info in zf.infolist())
        if total > len(epub_bytes) * max_ratio:
            raise EpubParseError("EPUB content expands beyond the allowed decompression ratio")
```
Also correct the docstring's claim so it doesn't assert a mitigation that isn't actually implemented.

### CR-02: "Auto" voice preset selection permanently disables best-guess voice selection, breaks real TTS synthesis

**File:** `backend/app/main.py:271-281`, `frontend/src/components/CharacterCard.tsx:90-93,148-165`, `backend/app/voices.py:19-25`
**Issue:** `backend/app/voices.py`'s `PRESET_VOICES` currently ships exactly one entry: `{"name": "", "label": "Default narrator (auto-selected)"}`. In the frontend, `CharacterCard`'s `handlePresetChange` maps the UI's `AUTO_PRESET_VALUE` sentinel back to the empty string `""` before calling `saveField({ voice_preset: "" })` — i.e. simply opening the (single-item) Preset dropdown and picking the only available item writes `voice_preset = ""` to the DB. On the backend, `patch_character` treats any non-`None` `voice_preset` (including `""`) as "voice_preset is now set" (`if patch.voice_preset is not None: character.voice_preset = patch.voice_preset`), and `_generate_preview`'s speaker-resolution only falls back to `best_guess_preset(...)` when `speaker is None`:
```python
speaker = character.voice_preset
if speaker is None:
    speaker = best_guess_preset(character.voice_instructions or description) or ""
```
Since `character.voice_preset` is now `""` (not `None`), this branch is skipped, and `synthesize(intro_line, "")` is called with an empty speaker. Against `TTS_BACKEND=mock` this is invisible (the mock ignores `speaker`), so none of the current tests catch it — but against the real `TTS_BACKEND=http` path (`tts_client.py`), `""` is sent verbatim as `speaker` to the TTS service, defeating the documented "auto best-guess by description/voice_instructions" behavior (D-16/D-17, per this module's own comments) for every character whose preset dropdown is ever touched.

**Fix:** Use the same `None`-vs-`""` sentinel consistently end to end — either treat `""` as "unset" server-side too, or don't let the frontend ever persist `""`:
```python
if speaker is None or speaker == "":
    speaker = best_guess_preset(character.voice_instructions or description) or ""
```

## Warnings

### WR-01: `EventSource` "error" listener conflates transient connection drops with real server-sent failures and kills auto-reconnect

**File:** `frontend/src/hooks/useAnalysisStream.ts:72-79`
**Issue:** `addEventListener("error", ...)` fires both for (a) the server explicitly sending `event: error` (a real analysis failure), and (b) the browser's native `EventSource` connection-drop event on any transient network hiccup — these are indistinguishable via the same listener (a known `EventSource` gotcha). The handler unconditionally calls `source.close()` and sets `status: "error"`, permanently ending the stream and showing a hard failure screen even when the underlying analysis is still running fine server-side and the browser would otherwise have auto-reconnected.
**Fix:** Only treat it as a terminal failure when `event.data` is present (i.e., an actual server-sent `error` event); on the native connection-drop case (no `.data`), let `EventSource`'s built-in reconnect proceed instead of closing:
```ts
source.addEventListener("error", (event) => {
  const messageEvent = event as MessageEvent
  if (!messageEvent.data) return // transient connection drop — let EventSource auto-reconnect
  const detail = JSON.parse(messageEvent.data)?.detail ?? "Analysis failed"
  setState((prev) => ({ ...prev, status: "error", errorDetail: detail }))
  source.close()
})
```

### WR-02: SSE progress-stream endpoint never validates the project exists, and leaks a `Queue` per unmatched `project_id`

**File:** `backend/app/main.py:201-204`, `backend/app/analysis_worker.py:37-50`
**Issue:** `GET /projects/{project_id}/analysis-stream` calls `progress_events(project_id)` unconditionally — there is no check that `project_id` corresponds to a real `Project`, nor to one still `"analyzing"`. `_get_queue` lazily creates-and-caches an `asyncio.Queue` for any id at all. For a bogus/typo'd `project_id`, or a `project_id` whose analysis already completed (queue already popped by its own consumer), the request just hangs forever with no data and no error — there's no 404, no timeout. Each such request also leaves a `Queue` entry sitting in the module-level `_progress_queues` dict indefinitely (it's only ever removed by the terminal-event consumer, which never arrives for these ids), so repeated bogus/duplicate requests grow this dict without bound for the lifetime of the process.
**Fix:** Validate `project_id` exists (404 if not) and reject/short-circuit when `project.status` is already terminal (`"ready"`/`"error"`) by serving the current state directly instead of blocking on an empty queue.

### WR-03: Segments referencing an unknown character name are silently dropped with no logging

**File:** `backend/app/analysis_worker.py:119-126`
**Issue:** `_persist_result` skips any `SegmentSuggestion` whose `character_name` isn't in `name_to_id` (comment: "Grok/mock referenced a character name not in its own cast list — skip rather than violate the FK") but never logs this. `logger` is already imported and used elsewhere in this module (`run_analysis`), so this is an easy, low-risk fix. Without it, an LLM prompt-adherence regression (a very plausible failure mode for structured LLM output) silently loses narration/dialogue with zero trace in logs — a user just sees fewer segments than expected with no way to diagnose why.
**Fix:**
```python
if character_id is None:
    logger.warning(
        "project %s: dropping segment for unknown character_name %r",
        project_id, suggestion.character_name,
    )
    continue
```

### WR-04: `SegmentSuggestion.order` is defined and populated but never actually used for ordering

**File:** `backend/app/schemas.py:17-19`, `backend/app/analysis_worker.py:119-137`
**Issue:** `SegmentSuggestion.order` is part of the LLM's structured-output contract, and both the mock backend and the real prompt populate it per-chunk (see `test_run_analysis_multi_chunk_reconciles_duplicate_and_orders_segments_globally`, where chunk 2's suggestions carry `order=0,1` again). `_persist_result`, however, completely ignores `suggestion.order` and instead assigns `Segment.order` purely from list-iteration position plus a running `order_start` counter. This makes the field dead weight in the schema at best, and a latent ordering bug at worst: if a future prompt change or LLM response ever returns `result.segments` in an order that doesn't match `.order`'s intended sequence (e.g., a provider reordering fields, or future direct API consumers relying on `.order` as ground truth), segments would silently persist in the wrong order with no validation catching the mismatch.
**Fix:** Either sort by `suggestion.order` before assigning `Segment.order` (`for suggestion in sorted(result.segments, key=lambda s: s.order):`), or drop the field from the schema/prompt if list order is the only thing that will ever be trusted, to avoid the two sources of truth diverging silently.

### WR-05: `merge_character` leaves the source character's preview WAV orphaned on disk

**File:** `backend/app/main.py:333-366`
**Issue:** `merge_character` reassigns segments and `session.delete(source)`, but never removes `source.preview_audio_path` from disk (compare with `_generate_preview`'s own stale-preview cleanup via `Path(old_path).unlink(missing_ok=True)`, which this endpoint doesn't replicate). Every merge leaks one preview WAV file under `PREVIEW_DIR`.
**Fix:**
```python
source_preview_path = source.preview_audio_path
...
session.delete(source)
session.commit()
if source_preview_path:
    Path(source_preview_path).unlink(missing_ok=True)
```

### WR-06: `CastWizard`'s delayed refetch timers aren't cleared on unmount

**File:** `frontend/src/components/CastWizard.tsx:38-43`
**Issue:** `handleCastRefresh` schedules three bare `setTimeout(refetch, delay)` calls (800ms/1800ms/3500ms) after every edit/merge/voice-assign, with no `clearTimeout` and no cleanup if the component unmounts before they fire (e.g., user navigates away or re-uploads within the delay window). The scheduled `refetch()` will still fire and call `setCast`/`setSegments` on an unmounted component.
**Fix:** Track the timeout ids in a ref and clear them in a `useEffect` cleanup:
```ts
const timeoutsRef = useRef<number[]>([])
useEffect(() => () => timeoutsRef.current.forEach(clearTimeout), [])
const handleCastRefresh = useCallback(() => {
  refetch()
  for (const delay of REFRESH_DELAYS_MS) {
    timeoutsRef.current.push(window.setTimeout(refetch, delay))
  }
}, [refetch])
```

## Info

### IN-01: `UPLOAD_DIR` setting is defined but never used anywhere in the codebase

**File:** `backend/app/config.py:50,77`
**Issue:** `Settings.UPLOAD_DIR` / `_DEFAULT_UPLOAD_DIR` are computed and exposed, but grepping the backend finds no other reference — raw uploads are only ever held in memory (`_read_upload_bounded`) and never written under this directory. Dead configuration surface.
**Fix:** Remove `UPLOAD_DIR` until something actually persists uploads to disk, or wire it up if that's intended for a future phase.

### IN-02: EPUB detection trusts client-supplied `Content-Type` as an OR condition

**File:** `backend/app/main.py:100-104`
**Issue:** `is_epub` is true if the filename ends in `.epub` **or** `file.content_type` is one of the epub MIME types — the latter is fully client-controlled and unverified. Low impact in practice since a non-epub body sent with a spoofed epub content-type just fails fast in `extract_text` (caught, returned as 400), but it's worth noting the extension check alone would be sufficient and less surprising.
**Fix:** Prefer filename-extension-only detection, or explicitly document why the content-type OR-branch is needed (e.g., for extension-less uploads from certain clients).

---

_Reviewed: 2026-07-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
