# Phase 3: Editable Table, Full Generation Pipeline, Persistence & Deployment - Context

**Gathered:** 2026-07-11
**Status:** Ready for planning

<domain>
## Phase Boundary

User has the complete production workflow: an editable segment table (Narrator/Voice Instructions/Text columns, bulk row reassignment), on-demand and batch audio generation with content-hash caching and single-row regeneration, resumable per-segment progress, project save/reopen (including a project list to reopen from), and private access to the whole running app over Tailscale on the real production GPU VM. This is the last phase — it completes full v1 scope.

Builds directly on Phase 2's cast/segment data (`Character`/`Segment` SQLModel tables) and Phase 1's `tts_client.synthesize()`/`audio_join.join_wavs()`. Does NOT include: VoiceDesign custom voice generation (deferred past v1 per Phase 2's D-17), SSML/timeline editing, M4B/chapter-marker output, or any new ingestion/cast-detection capability — those are out of scope per REQUIREMENTS.md.

</domain>

<decisions>
## Implementation Decisions

### Real-hardware validation (this phase's biggest departure from Phase 1/2's mock-first default)
- **D-01:** The production RX 9070 XT VM is not a future unknown — it is the exact machine this session has been developing against (Tailscale hostname `tts`, real Navi 48/gfx1201 GPU, `/dev/kfd`+`/dev/dri` present). The Phase 1 D-09 GPU re-verification checklist was already closed out here on 2026-07-10 (commit `1ce34aa`): `rocminfo`/on-device PyTorch matmul confirmed gfx1201 with no dev-host workarounds needed; rootless Podman GPU passthrough does NOT work on this Podman/crun combo (host GID mapping gap); rootful (`sudo podman run --user 0:0`) does, and is `run-local.sh`'s default; a real end-to-end request returned a genuine non-silent WAV (24kHz, 21.4s, 96.5% non-zero samples). `STATE.md`/`PROJECT.md` blockers were stale claiming this was still unproven — corrected as part of this discussion (see commits to those files).
- **D-02:** No pod is currently running on the VM (nothing persists a teardown between sessions) and this exact combination (caching + resumable batch generation + regenerate-while-batch-running) has never been tested against real GPU inference, only `TTS_BACKEND=mock`. Phase 3's plan should start by running `bash deploy/run-local.sh` to re-confirm the pod still comes up cleanly, then build/test the generation pipeline against real synthesis where practical during execution — not defer all real-hardware contact to a final sign-off step the way Phase 1/2 did with `TTS_BACKEND=mock`/`LLM_BACKEND=mock`.
- **D-03:** This does NOT mean dropping the mock backends — `TTS_BACKEND=mock`/`LLM_BACKEND=mock` remain the default for fast local iteration (UI work, table logic, caching-key correctness) exactly as before. The shift is specifically: validate the real pipeline early and incrementally during this phase's execution, rather than only at the very end.

### Project List / Reopen (PERS-02)
- **D-04:** Add a simple project list screen — not just the single-slot "resume last project" localStorage mechanism from Phase 2. Lists saved projects (filename, date, status) and lets the user pick one to reopen. Backend already has multiple `Project` rows in SQLite; this is a new `GET /projects` list endpoint + a new frontend screen, not a schema change.
- Where this screen sits in the navigation flow (entry point before upload, a link from the wizard, etc.) is Claude's discretion — no specific placement was dictated.

### Bulk Row Selection (TBL-03)
- **D-05:** Checkbox column + toolbar action — a checkbox per row plus a header "select all," with an action bar appearing above the table when 1+ rows are selected (e.g. "Reassign narrator to: [dropdown]"). Not shift/ctrl-click range select.

### Regeneration Trigger (GEN-03)
- **D-06:** Auto-regenerate on blur — editing a row's Narrator/Voice Instructions/Text and clicking away triggers that row's regeneration automatically in the background, consistent with Phase 2's autosave-on-blur pattern for character fields (no separate "Save" or "confirm regenerate" step). This applies per-row; it is not the same action as the batch "generate all" run.
- Whether/how a still-generating row's background regeneration interacts with a concurrently-running batch generation pass (e.g., does an edit mid-batch queue-jump or wait) is Claude's discretion during planning — no specific interleaving behavior was dictated. Note this against D-02: this exact interaction is one of the "never tested against real GPU inference" gaps flagged above and should get real-hardware coverage during this phase, not just a mock-backend unit test.

### Claude's Discretion
- Project list screen's navigation placement/entry point.
- Batch-vs-per-row-edit interleaving behavior during concurrent generation (flagged above for real-hardware testing).
- Exact content-hash implementation (algorithm, what "voice/model version" concretely means given only one TTS model exists today) — must satisfy GEN-02's stated key: (character, voice instructions, text, voice/model version).
- Exact SSE/polling mechanism for CFG-03's live per-segment/overall progress — likely reuses Phase 2's `EventSourceResponse` pattern, but exact event schema is open.
- Internal schema additions for generation status (pending/queued/generating/complete/error per GEN-05) and cache key storage — Phase 2's D-02 explicitly deferred this to Phase 3's own design.
- CFG-01's "model" field: whether this is a real dropdown (multiple TTS model choices) or a fixed display value, since only one model (Qwen3-TTS-12Hz-1.7B-CustomVoice) is in scope for v1.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Tech stack (governs almost every Phase 3 implementation choice)
- `CLAUDE.md` (repo root) — Technology stack: SQLModel/SQLite persistence, FastAPI, `fastapi.sse.EventSourceResponse` for progress push, ffmpeg concat demuxer for joining, Podman + Quadlets deployment, `TTS_BACKEND=mock` dev-degradation pattern.
- `.planning/research/STACK.md` — Full stack research writeup (referenced by CLAUDE.md's stack table as the source doc).

### Real-hardware state (the key finding from this discussion — read before assuming mock-only)
- `deploy/README.md` §"Production VM bring-up" and §"D-09 GPU re-verification checklist" — documents the closed-out real-GPU verification on the exact VM this phase should build/test against: rootful Podman invocation shape, real non-silent WAV confirmed, `sox` packaging fix.
- `deploy/run-local.sh` — the one-command bring-up script for the real pod (backend + GPU-scoped TTS container) on this VM.
- `deploy/bootstrap-vm.sh` — idempotent one-time host setup (already run on this VM per D-01/D-02).
- `backend/GPU-ENABLEMENT.md` — historical gfx1103 dev-host fallback-ladder investigation log; explains why rootful/`--user 0:0` is required (do not modify this file, per its own header note carried from the prior quick task).
- `.planning/STATE.md` §Blockers/Concerns — corrected in this discussion to reflect the resolved GPU/VM state; also flags the Phase 3-specific gap (caching/resumable-batch/concurrent-regen untested against real inference).
- `.planning/PROJECT.md` §Active requirements + §Key Decisions — corrected in this discussion (GEN-01/DEPL-01 rows no longer say "UNPROVEN").

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 3: Editable Table, Full Generation Pipeline, Persistence & Deployment" — phase goal, 5 success criteria, requirement mapping.
- `.planning/REQUIREMENTS.md` §Segment Table (TBL-01..04), §Generation & Audio (GEN-02/03/05), §Persistence (PERS-01/02), §Config & Progress (CFG-01..03), §Deployment (DEPL-02) — exact requirement text.
- `.planning/PROJECT.md` — project vision, core value, constraints.

### Prior phase context
- `.planning/phases/02-llm-cast-detection-review-wizard/02-CONTEXT.md` — D-02 there explicitly deferred generation-status/content-hash-cache schema fields to this phase's own design; D-14/D-15 established the single-page spreadsheet-editing UI philosophy this phase's table extends.
- `.planning/phases/01-upload-to-audio-spike-tts-rocm-de-risk/01-CONTEXT.md` — D-09 there is the real-hardware-verification follow-up this phase's D-01/D-02 confirm is now closed.
- `.planning/phases/02-llm-cast-detection-review-wizard/02-UAT.md` — documents the fixes made during Phase 2 UAT (merge undo, segments table sizing, description field removal, refresh-persistence via localStorage) that this phase's project-list screen (D-04) supersedes/extends.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/tts_client.py` (`synthesize`, `tts_health`) — existing TTS client (mock/http backends), reused as-is for per-segment generation (GEN-01 already proven).
- `backend/app/audio_join.py` (`join_wavs`) — existing ffmpeg concat-demuxer joiner, reused for rejoining after single-segment regeneration (GEN-03).
- `backend/app/models.py` (`Project`, `Character`, `Segment` SQLModel tables) — Phase 2's schema is the base this phase extends (generation status, cache key/path fields) rather than replaces.
- `backend/app/db.py` (`engine`, `init_db`, session pattern) — established SQLModel/SQLite session-per-request pattern to reuse.
- `frontend/src/api/client.ts` — typed fetch wrapper pattern (one function per endpoint) to extend for new list/generate/bulk endpoints.
- `frontend/src/components/SegmentPreview.tsx` — Phase 2's read-only TanStack Table segment preview is the direct precedent this phase's editable table extends (add editable cells, row selection, bulk toolbar) rather than building a new table component from scratch.
- `frontend/src/App.tsx`'s `PROJECT_ID_STORAGE_KEY` localStorage pattern — the single-slot "current project" mechanism this phase's project list screen (D-04) extends into a real list/reopen flow.
- `deploy/run-local.sh` / `deploy/qwen-ebook-pod.yaml` — existing two-container Podman pod topology (DEPL-01), the direct base for DEPL-02's actual long-running deployment (vs. this being a manual dev bring-up script).

### Established Patterns
- Background `asyncio.create_task` + version-stamped "last-request-wins" race guard (Phase 2's `_generate_preview`/`voice_version`) — the direct precedent for GEN-03's auto-regenerate-on-blur (D-06): a content-hash or generation-version field plays the same role `voice_version` did for preview races.
- `EventSourceResponse` SSE pattern (Phase 2's `/projects/{id}/analysis-stream`) — the direct precedent for CFG-03's live per-segment/overall progress push.
- Mock-backend-via-env-flag (`TTS_BACKEND=mock`) — still the default for fast iteration per D-03; real-hardware validation (D-01/D-02) is additive, not a replacement default.
- Inline-edit-on-blur, no separate Save button (Phase 2's `CharacterCard.tsx`) — the UI convention D-06 explicitly carries into the segment table.

### Integration Points
- `GET /projects/{project_id}` (existing) returns characters + segments — the new editable table's data source; likely needs a new/extended endpoint for per-segment generation status and cache metadata.
- New `GET /projects` (list) endpoint needed for D-04's project list screen — does not exist today (only single-project-by-id reads exist).
- New per-row `POST /segments/{id}/generate` (or similar) and bulk-reassign endpoint needed for TBL-04/TBL-03 — no generation-trigger endpoint exists yet (Phase 1's generation was a single synchronous whole-project flow, since replaced by Phase 2's analysis-first flow; Phase 3 reintroduces per-segment generation against the reviewed cast, as `main.py`'s module docstring already anticipates).

</code_context>

<specifics>
## Specific Ideas

- User, verbatim, on real-hardware validation: "option one and update your documentation/instructions to properly mirror the current actuall state of the project" — chose earliest/most continuous real-hardware validation (not mock-first-then-check-at-end, not skip-GPU-this-phase), AND explicitly asked for the stale "VM doesn't exist yet" documentation to be corrected as part of this decision — done in this session (`STATE.md`, `PROJECT.md` updated; commits pending at git_commit step).
- All four gray-area questions were answered by picking the presented "Recommended" option — no push-back or alternative framing offered on project list, bulk select, or regen trigger, suggesting these are genuinely uncontroversial/default-expectation choices for this user rather than areas needing deeper exploration.

</specifics>

<deferred>
## Deferred Ideas

- VoiceDesign custom voice generation — already deferred past Phase 2 (D-17 there); still out of scope here, no new discussion needed.
- Full git-like edit history / diff — explicitly out of scope per REQUIREMENTS.md's Out of Scope table; not raised as a live idea in this discussion, just noting it stays excluded.

### Reviewed Todos (not folded)
None — no pending todos matched this phase's scope during `cross_reference_todos` (`gsd_run query todo.match-phase 3` returned 0 matches).

</deferred>

---

*Phase: 3-editable-table-full-generation-pipeline-persistence-deployment*
*Context gathered: 2026-07-11*
