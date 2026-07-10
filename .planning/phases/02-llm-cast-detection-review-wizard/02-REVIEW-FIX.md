---
phase: 02-llm-cast-detection-review-wizard
fixed_at: 2026-07-10T12:11:00Z
review_path: .planning/phases/02-llm-cast-detection-review-wizard/02-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-07-10T12:11:00Z
**Source review:** .planning/phases/02-llm-cast-detection-review-wizard/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (2 Critical, 6 Warning — `fix_scope: critical_warning`, so the 2 Info findings were excluded)
- Fixed: 8
- Skipped: 0

## Fixed Issues

### CR-01: EPUB decompression is unbounded — upload size cap does not prevent a zip-bomb DoS

**Files modified:** `backend/app/epub_parser.py`
**Commit:** `422ad24`
**Applied fix:** Added `_check_decompressed_size()`, which sums each zip entry's uncompressed `ZipInfo.file_size` (no decompression needed — read from the central directory) and rejects the archive via `EpubParseError` if total uncompressed size exceeds 100x the compressed upload size. Called at the top of `extract_text()`, before `epub.read_epub()` ever runs. Also corrected the module docstring, which previously claimed `_read_upload_bounded` (compressed-size-only) was "what guards against a zip-bomb" — it now describes the real guard.

### CR-02: "Auto" voice preset selection permanently disables best-guess voice selection

**Files modified:** `backend/app/main.py`
**Commit:** `f2a3d30`
**Applied fix:** In `_generate_preview`, changed `if speaker is None:` to `if not speaker:` so an empty-string `voice_preset` (the literal value persisted by the frontend's single-item preset dropdown) falls back to `best_guess_preset(...)` the same way `None` does, instead of being sent verbatim as an empty `speaker` to the TTS backend.

### WR-01: `EventSource` "error" listener conflates transient connection drops with real server-sent failures

**Files modified:** `frontend/src/hooks/useAnalysisStream.ts`
**Commit:** `7335272`
**Applied fix:** The `error` listener now returns early (without closing the connection or setting `status: "error"`) when `event.data` is absent — that's the browser's native connection-drop signal, not a real server-sent failure, so `EventSource`'s built-in reconnect is now allowed to proceed. Only an actual `event: error` with a JSON payload is treated as terminal.

*Note: the source file at the cited lines had already been partially modified from what REVIEW.md described (a different fallback error message was already present), but the core bug — closing/erroring unconditionally on any `error` event — was still live. The fix was adapted to the current code rather than applied as a literal patch.*

### WR-02: SSE progress-stream endpoint never validates the project exists, and leaks a `Queue` per unmatched `project_id`

**Files modified:** `backend/app/main.py`, `backend/app/analysis_worker.py`
**Commit:** `1523d72`
**Applied fix:** Added a `_require_project_exists` FastAPI dependency (404 if the project doesn't exist) on `GET /projects/{project_id}/analysis-stream`. A dependency was required rather than an in-body check because `analysis_stream` is an async-generator SSE endpoint — raising `HTTPException` from inside such a generator is swallowed by FastAPI's SSE producer task group and surfaces as an unhandled 500, not a clean 404 (verified empirically before settling on the dependency approach). Also added `has_pending_queue()` to `analysis_worker.py` and used it to short-circuit serving the terminal state directly (skipping the blocking queue read) only when the project's status is already terminal **and** its queue has already been fully drained by an earlier subscriber — this avoids both the original infinite-hang bug and a regression where a still-buffered "progress" event would be skipped on a race between analysis finishing and the SSE subscriber connecting. Verified with the full backend test suite plus two manual scenarios (bogus id -> 404; reconnect after full drain -> immediate terminal event, no hang).

### WR-03: Segments referencing an unknown character name are silently dropped with no logging

**Files modified:** `backend/app/analysis_worker.py`
**Commit:** `37b6e82`
**Applied fix:** Added `logger.warning(...)` in `_persist_result`'s FK-violation guard, exactly as suggested in REVIEW.md, logging the project id and the unresolved `character_name`.

### WR-04: `SegmentSuggestion.order` is defined and populated but never actually used for ordering

**Files modified:** `backend/app/analysis_worker.py`
**Commit:** `9829f75`
**Applied fix:** `_persist_result` now iterates `sorted(result.segments, key=lambda s: s.order)` instead of trusting raw list-iteration order, so the LLM's own `.order` field is the actual source of truth for within-call ordering (kept the field in the schema rather than removing it, per REVIEW.md's first suggested option).

### WR-05: `merge_character` leaves the source character's preview WAV orphaned on disk

**Files modified:** `backend/app/main.py`
**Commit:** `02acd53`
**Applied fix:** Captured `source.preview_audio_path` before deleting the source character, and added `Path(source_preview_path).unlink(missing_ok=True)` after the transaction commits, mirroring `_generate_preview`'s own stale-preview cleanup pattern.

### WR-06: `CastWizard`'s delayed refetch timers aren't cleared on unmount

**Files modified:** `frontend/src/components/CastWizard.tsx`
**Commit:** `51f8cf8`
**Applied fix:** Added a `timeoutsRef` ref to track scheduled `setTimeout` ids from `handleCastRefresh`, and a `useEffect` cleanup that clears all of them on unmount — as suggested in REVIEW.md.

## Skipped Issues

None — all in-scope findings were fixed.

---

_Fixed: 2026-07-10T12:11:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
