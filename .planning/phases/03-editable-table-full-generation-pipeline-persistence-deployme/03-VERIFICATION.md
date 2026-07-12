---
phase: 03-editable-table-full-generation-pipeline-persistence-deployme
verified: 2026-07-12T16:24:24Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 3: Editable Table, Full Generation Pipeline, Persistence & Deployment Verification Report

**Phase Goal:** User has the complete production workflow — an editable segment table, on-demand and batch audio generation with content-hash caching and single-row regeneration, resumable per-segment progress, project save/reopen, and private access to the whole running app over Tailscale — completing the full v1 scope.

**Verified:** 2026-07-12T16:24:24Z
**Status:** passed
**Re-verification:** No — initial verification of this phase (03-01 through 03-09, including gap-closure plans 06-09 and the follow-up code-review fix commit)

This verification was performed with direct live access to the actual running
production Podman/Quadlet deployment on the RX 9070 XT VM (the same host this
session runs on) — SUMMARY.md claims for the deployment/restart-resilience/
real-GPU findings were re-run live rather than trusted, not just re-read.

## Goal Achievement

### Observable Truths (ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Main UI shows an editable table (~70% width) with Narrator/Voice Instructions/Text columns; user can edit any cell and bulk-reassign multiple selected rows in one action | ✓ VERIFIED | `SegmentTable.tsx` has `NarratorCell` (Select, commits via `patchSegment` on change), `EditableTextCell` (Textarea, commits on blur) for both `text`/`voice_instructions`, a checkbox column + header select-all (TanStack `RowSelectionState`, `getRowId: s => s.id`), and `BulkReassignToolbar` that calls `bulkReassignSegments`. Live-tested: `POST /segments/bulk-reassign` against the real running project reassigned a segment's narrator (`character_name` flipped `Narrator` → `Alex`) in one call. |
| 2 | User can generate and preview any single row's audio on demand via a per-row generate + play/pause button | ✓ VERIFIED | `GeneratePlayButton` in `SegmentTable.tsx` calls `generateSegment(id)` then auto-plays; toggles play/pause once `audio_path` exists. Live-tested against real GPU TTS: `POST /segments/{id}/generate` on a live project segment returned `generation_status: "complete"` with a real `audio_path`; downloaded the resulting WAV — 24kHz, 2.8s, 91.5% non-zero-byte fraction (genuinely audible, not silence). |
| 3 | Editing a row's Narrator/Voice Instructions/Text after generation regenerates only that segment via a content-hash cache keyed on (character, voice instructions, text, voice/model version), then rejoins the full output — unchanged rows untouched | ✓ VERIFIED (with confirmed, documented requirement reversal — see below) | `compute_cache_key(speaker, voice_instructions, text)` in `cache_key.py`; `regenerate_segment` (main.py:678-751) recomputes it live from current DB state before every synth and cache-hits (no synth call) on a match. Live-tested GEN-02 cache hit: re-generating an unchanged segment returned in 0.026s with the identical `audio_path` (vs. ~20s for the original synthesis) — genuine cache hit, not a re-synthesis. **GEN-03 was intentionally reversed during UAT** (03-CONTEXT.md D-06, REQUIREMENTS.md GEN-03 both updated in commit `78a84e8`): an edit now only *invalidates* (clears `audio_path`, sets `pending`) — it does **not** auto-fire regeneration; the user triggers it manually. Verified the current code and current requirement wording agree, and live-tested the invalidate-only behavior: `PATCH /segments/{id}` on a real project segment cleared `audio_path` and set `generation_status: "pending"` with no background task firing (status did not flip to `generating` on its own). CR-01 (batch "skip if complete" trusting a stale status flag after bulk-reassign/merge/voice-edit) was found by the code review and fixed in `cdcdbf4` — `run_batch_generation` no longer skips on status; it always defers to `regenerate_segment`'s live cache-key recompute. Regression-tested with `test_batch_regenerates_after_reassign_to_different_voice` (passes) and confirmed the fix's rationale holds by reading the current code. |
| 4 | Right-side config panel (~30% width) shows input file/model/output format/output file, character list with preview controls, live per-segment/overall progress; a batch run resumes correctly after interruption/crash via persisted per-segment status | ✓ VERIFIED | `ConfigPanel.tsx` renders `ConfigField` rows for filename/model/output format/output path, `CharacterPreviewRow` per character (Play button + on-demand "Generate preview" trigger with an explanatory tooltip when no preview exists — closes UAT gap 4), and a `Progress` bar driven by `useGenerationStream`'s SSE `overall` state. `run_batch_generation` (generation_worker.py) resets stale `"generating"` rows to `"pending"` before its loop (crash-safety), and `pytest test_batch_continues_past_error`/interrupted-batch tests pass. Live-verified the crash/restart half of this end-to-end on the real production Quadlet deployment: restarted `qwen-ebook-backend.service` + `qwen-ebook-tts.service` simultaneously, confirmed the pod (`ExitPolicy` via `--exit-policy=continue`) self-healed without manual intervention, `/healthz` returned 200 within ~10s, and all 7 pre-restart projects were still present afterward (persistent `/data` volume). |
| 5 | Projects (source text, cast, segment table, cached audio, joined output) are auto-saved as the user works and reopenable, reachable only over Tailscale with no public exposure/added auth | ✓ VERIFIED | Every mutating endpoint (`patchSegment`, `patchCharacter`, `bulkReassignSegments`, `generateSegment`) commits immediately via `Session.commit()` — no separate save action anywhere in the frontend. `GET /projects` (list) + `ProjectListScreen.tsx` (filename/date/status badge, Open action, "No projects yet" empty state, New Project CTA) is the app's landing screen (`App.tsx`: no `projectId` → `ProjectListScreen`). Live-verified DEPL-02 on the real VM: `sudo tailscale serve status` shows `https://tts.pigeon-bearded.ts.net (tailnet only) -> proxy http://127.0.0.1:8000`; `ss -tlnp` confirms the backend listens on `127.0.0.1:8000` only (no `0.0.0.0` binding); `qwen-ebook.pod`'s `PublishPort=127.0.0.1:8000:8000` matches. Podman Quadlet units are systemd-managed (`Loaded: loaded (/etc/containers/systemd/...; generated)`), not a manual dev script. |

**Score:** 5/5 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/cache_key.py` | GEN-02 content-hash key | ✓ VERIFIED | Used live by `regenerate_segment`; confirmed cache-hit behavior end-to-end on real GPU synth |
| `backend/app/models.py` | Segment/Project generation fields | ✓ VERIFIED | `generation_status`/`generation_version`/`cache_key`/`audio_path`/`generation_error`, `Project.created_at`/`output_path` all present and populated in live API responses |
| `backend/app/main.py` | All Phase 3 endpoints | ✓ VERIFIED | `GET /projects`, `GET/PATCH /segments/{id}`, `POST /segments/{id}/generate`, `POST /segments/bulk-reassign`, `POST/GET /projects/{id}/generate[/cancel]`, `/projects/{id}/generation-stream`, `POST /characters/{id}/preview` all live-exercised against the production deployment |
| `backend/app/generation_worker.py` | Resumable batch state machine | ✓ VERIFIED | Stale-row reset, per-project in-flight registry (`_running_generations`), cancel-safe (CancelledError propagates untouched), CR-01 fix applied (no status-based skip) |
| `frontend/src/components/SegmentTable.tsx` | Editable table + per-row generate + bulk toolbar | ✓ VERIFIED | Status-driven `GeneratePlayButton` (disabled while `generation_status === "generating"` from ANY source, not just its own click — closes UAT gap "test 4 continuation") |
| `frontend/src/components/ConfigPanel.tsx` | Config panel + progress + Stop + preview trigger | ✓ VERIFIED | `isRunning` combines batch SSE status AND any per-row `generating` segment (closes UAT major gap); Stop control calls `cancelBatchGeneration`; on-demand preview trigger with explanatory disabled state (closes UAT major gap) |
| `frontend/src/components/ProjectListScreen.tsx` | Project list/reopen landing screen | ✓ VERIFIED | Empty state, status badges, Open action, New Project CTA |
| `deploy/qwen-ebook.pod`, `qwen-ebook-backend.container`, `qwen-ebook-tts.container` | Restart-resilient, persistent, loopback-only Quadlet units | ✓ VERIFIED (live) | Confirmed running as systemd units on the production VM; `qwen-ebook-data` named volume mounted at `/data` (not shadowing `/backend/static`); `--exit-policy=continue`; live restart test passed (self-healed, data survived) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `SegmentTable.tsx` editable cells | `PATCH /segments/{id}` | `patchSegment` on blur/change | ✓ WIRED | Live-tested; also correctly invalidates-only (no auto-regen task) per the D-06/GEN-03 reversal |
| `regenerate_segment` | `cache_key.py` | live recompute before every synth, incl. from the batch loop | ✓ WIRED | Live cache-hit confirmed (0.026s re-generate, identical `audio_path`); CR-01 fix removed the batch loop's bypass of this check |
| `ConfigPanel`/`SegmentTable` | `segment.generation_status` (live SSE-merged state) | `ProjectScreen`'s `liveSegments` | ✓ WIRED | Both components read live per-segment status to drive disabled state, not just local click flags — confirmed by code read (closes two UAT major gaps) |
| `generate_project` | per-project in-flight registry | `is_generation_running`/`_running_generations` | ✓ WIRED | Second `POST /projects/{id}/generate` while one is running returns `{"status": "already_running"}` without spawning a second task (pytest-covered) |
| Quadlet units | `tailscale serve` | `PublishPort=127.0.0.1:8000:8000` + `sudo tailscale serve --bg 8000` | ✓ WIRED (live) | Confirmed via `tailscale serve status` and `ss -tlnp` on the real VM |
| `patch_segment`/`undo_merge_character` | ownership validation | character/segment project_id checks | ✓ WIRED | WR-02/WR-01 fixes confirmed live: `PATCH /segments/{id}` with a nonexistent `character_id` returns 404 |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|-------------|--------|----------|
| TBL-01 | 03-01 | Editable table, 3 columns | ✓ SATISFIED | `SegmentTable.tsx` |
| TBL-02 | 03-01 | Edit any row field | ✓ SATISFIED | `patchSegment` wiring, live-tested |
| TBL-03 | 03-02 | Bulk select + reassign | ✓ SATISFIED | `bulk_reassign_segments`, live-tested |
| TBL-04 | 03-01, 03-09 | Per-row generate+play | ✓ SATISFIED | `GeneratePlayButton`, live real-GPU synth |
| GEN-02 | 03-01, 03-08 | Content-hash cache | ✓ SATISFIED | Live cache-hit confirmed; CR-01 batch-loop fix applied |
| GEN-03 | 03-01, 03-08 | Invalidate-on-edit (reversed from auto-regenerate) | ✓ SATISFIED | Current code + current REQUIREMENTS.md/03-CONTEXT.md wording agree; live-tested |
| GEN-05 | 03-03, 03-08, 03-09 | Persisted resumable batch status | ✓ SATISFIED | Stale-row reset, in-flight guard, cancel, live restart-resilience test |
| PERS-01 | 03-04 | Auto-save | ✓ SATISFIED | No save action exists; every mutation commits immediately |
| PERS-02 | 03-04, 03-06, 03-07 | Project list + reopen | ✓ SATISFIED | `ProjectListScreen`, `GET /projects`, permanent-404 recovery path (03-07) |
| CFG-01 | 03-03 | Config panel: input/model/output | ✓ SATISFIED | `ConfigPanel.tsx` |
| CFG-02 | 03-03, 03-09 | Character list + preview controls | ✓ SATISFIED | `CharacterPreviewRow` with on-demand trigger |
| CFG-03 | 03-03, 03-08, 03-09 | Live progress | ✓ SATISFIED | SSE `useGenerationStream`, `Progress` bar |
| DEPL-02 | 03-05, 03-06 | Tailscale-only, no public exposure | ✓ SATISFIED | Live-verified on production VM |

All 13 phase requirement IDs are declared across the 9 plans' `requirements:` frontmatter and are all marked "Complete" in REQUIREMENTS.md's Traceability table. No orphaned requirements found for Phase 3.

Note: `.planning/phases/.../deferred-items.md` flags an unrelated pre-existing gap — Phase 2's requirement IDs (ING-02, CAST-01..03, WIZ-01..05) are still shown "Pending" in REQUIREMENTS.md despite Phase 2 being complete. This is explicitly out of scope for Phase 3 (a Phase 2 bookkeeping gap, not a Phase 3 deliverable) and does not affect this verification.

### Anti-Patterns Found

No `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers found in the Phase 3 key files (`main.py`, `generation_worker.py`, `cache_key.py`, `SegmentTable.tsx`, `ConfigPanel.tsx`, `ProjectListScreen.tsx`, `useAnalysisStream.ts`, `App.tsx`, deploy Quadlet units).

Residual code-review Warnings/Info **not** part of this phase's must-haves and left open (tracked in 03-REVIEW.md, not blocking phase goal achievement):
- WR-03: `deploy/run-local.sh` (dev convenience script, not the production Quadlet path) still binds without an explicit loopback IP — confirmed still present (`grep` on the file). The actual production deployment's `.pod` unit correctly uses `PublishPort=127.0.0.1:8000:8000` (live-verified), so DEPL-02 itself is not affected.
- WR-04: a narrow cancel/done-callback race can leak an un-drained progress queue entry — not fixed, low severity, no user-facing symptom found.
- WR-05: the Config Panel's on-demand preview trigger can get stuck spinning forever if the fire-and-forget preview generation silently fails — not fixed. Confirmed by code read (`ConfigPanel.tsx`'s bounded-poll timeout clears the interval but never resets `isTriggeringPreview`).
- WR-06: several PATCH/POST call sites lack `.catch()` error surfacing on the frontend — not fixed.
- IN-01..IN-04: minor, none blocking.

These are pre-existing, disclosed, lower-severity gaps from the code review that the user's explicit fix commit (`cdcdbf4`) deliberately scoped to CR-01/WR-01/WR-02 only. They do not block the phase goal (all ROADMAP success criteria are independently satisfied) but are worth tracking as technical debt.

### Behavioral Spot-Checks / Live Verification

Performed directly against the running production Podman/Quadlet deployment on the RX 9070 XT VM (this session's own host) rather than trusting SUMMARY.md narration:

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Real GPU synthesis produces audible, non-silent audio | `POST /segments/{id}/generate` + WAV inspection | 24kHz, 2.8s, 91.5% non-zero bytes | ✓ PASS |
| Content-hash cache hit | Re-`POST /segments/{id}/generate` unchanged | 0.026s (vs. ~20s), same `audio_path` | ✓ PASS |
| GEN-03 reversal (invalidate-only, no auto-regen) | `PATCH /segments/{id}` then poll status | `pending`, `audio_path: null`, no auto `generating` transition | ✓ PASS |
| TBL-03 bulk-reassign | `POST /segments/bulk-reassign` | `{"updated": 1}`, `character_name` changed | ✓ PASS |
| WR-02 fix (patch_segment validates character_id) | `PATCH /segments/{id}` with bogus `character_id` | 404 | ✓ PASS |
| Restart resilience + data persistence (DEPL-02/PERS-01/02, closes UAT test-1 blocker) | `sudo systemctl restart qwen-ebook-backend.service qwen-ebook-tts.service` then poll `/healthz` and `/projects` | Pod self-healed without manual intervention (`ExitPolicy=continue`); `/healthz` 200 within ~10s; all 7 pre-restart projects present after restart | ✓ PASS |
| Tailscale-only exposure | `sudo tailscale serve status`, `ss -tlnp` | Serves only via tailnet proxy to `127.0.0.1:8000`; no `0.0.0.0` bind | ✓ PASS |
| Backend pytest suite (`TTS_BACKEND=mock`) | `uv run pytest -q` | 66 passed, 1 skipped, 1 failed | ⚠️ see note below |
| `ruff check .` | strict lint gate | All checks passed | ✓ PASS |
| Frontend typecheck | `npx tsc --noEmit` | Clean, exit 0 | ✓ PASS |

**Note on the 1 pytest failure:** `test_upload_returns_valid_wav_with_multiple_chunks_joined` in `backend/tests/test_integration.py` failed (`assert 201 == 200`). This is a pre-existing, out-of-scope Phase 1 integration test (marked `@requires_pod`, only runs when a real pod is reachable — it happened to find this session's live production backend on `127.0.0.1:8000`) that asserts the *retired* Phase 1 synchronous upload→WAV flow. Phase 2 intentionally replaced that flow with the analysis-first `202`/`201`-then-poll flow that Phase 3 builds on (`main.py`'s own module docstring: "The prior Phase 1 shape of this endpoint... is retired here"). This test was never updated after Phase 2's flow change and is unrelated to any Phase 3 must-have — not treated as a Phase 3 gap.

## Gaps Summary

No blocking gaps. All 5 ROADMAP.md success criteria and all 13 declared requirement IDs are verified against the actual codebase and, where feasible, against the live running production deployment (not just SUMMARY.md narration). The UAT's 7 diagnosed gaps (1 blocker on deployment restart-resilience, 1 blocker on a stuck-analysis dead end, 4 majors on generation guards/cancel/preview, 1 major requirement reversal) were all closed by gap-closure plans 03-06 through 03-09 and independently confirmed live in this verification. The subsequent code review's 1 Critical finding (CR-01: stale-audio-after-reassign) and 2 Warnings (WR-01/WR-02: missing ownership validation) were fixed in commit `cdcdbf4` with new pytest coverage, and the fix was re-confirmed by reading the current code plus live-testing the WR-02 validation path.

Residual code-review Warnings (WR-03 through WR-06) and Info items remain open by the user's own deliberate scoping of the fix commit — they are documented above as non-blocking technical debt, not phase gaps.

---

_Verified: 2026-07-12T16:24:24Z_
_Verifier: Claude (gsd-verifier)_
