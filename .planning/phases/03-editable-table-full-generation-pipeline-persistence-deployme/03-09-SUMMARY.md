---
phase: 03-editable-table-full-generation-pipeline-persistence-deployme
plan: 09
subsystem: ui
tags: [react, generation-controls, sse]

requires:
  - phase: 03-editable-table-full-generation-pipeline-persistence-deployme
    provides: "Plan 03-08's backend guards (per-project registry, per-row 409, POST .../generate/cancel, POST /characters/{id}/preview)"
provides:
  - Per-row Play/Generate button driven by live segment.generation_status, not just local click state
  - Generate All disabled whenever any segment is generating (batch OR per-row)
  - Stop control that cancels a running batch
  - On-demand "Generate preview" trigger with explanatory disabled state
affects: [frontend, ui]

tech-stack:
  added: []
  patterns:
    - "Bounded client-side poll (setInterval + setTimeout ceiling) to pick up a background-task result (preview_audio_path) with no dedicated SSE channel for it"

key-files:
  created: []
  modified:
    - frontend/src/api/client.ts
    - frontend/src/components/SegmentTable.tsx
    - frontend/src/components/ConfigPanel.tsx
    - frontend/src/components/ProjectScreen.tsx

key-decisions:
  - "Preview generation has no SSE channel, so ConfigPanel polls onRefresh (parent refetch) every 1.5s for up to 15s after triggering, bounded so a failed generation doesn't poll forever"

patterns-established: []

requirements-completed: [TBL-04, CFG-02, CFG-03, GEN-05]

coverage:
  - id: D1
    description: "A per-row Play/Generate button is disabled with a spinner whenever that segment's live status is 'generating', so it cannot fire a duplicate generate"
    requirement: TBL-04
    verification:
      - kind: integration
        ref: "Live verification against the running production backend: POST /segments/{id}/generate started synthesis, an immediate duplicate POST to the same segment returned 409 'Segment is already generating' — exactly the signal isRowGenerating (segment.generation_status === 'generating') disables the button on"
        status: pass
      - kind: other
        ref: "Code trace: SegmentTable.tsx GeneratePlayButton — isRowGenerating = isGenerating || segment.generation_status === 'generating', gates both disabled and the spinner"
        status: pass
    human_judgment: true
    rationale: "This VM has no browser/display (no chromium/firefox, DISPLAY unset) — the button's disabled/spinner rendering itself was traced in code, not observed in a live DOM. The backend signal it reacts to (409 on duplicate) was verified live."
  - id: D2
    description: "Generate All is disabled whenever any segment is 'generating' (batch OR per-row)"
    requirement: GEN-05
    verification:
      - kind: integration
        ref: "Live: POST /projects/{id}/generate -> 202 {status:started}; immediate duplicate POST -> 202 {status:already_running}; segment status observed 'generating' mid-flight"
        status: pass
      - kind: other
        ref: "Code trace: ConfigPanel.tsx — anyGenerating = segments.some(s => s.generation_status === 'generating'); isRunning = isBatchRunning || anyGenerating gates the Generate All button"
        status: pass
    human_judgment: true
    rationale: "Same no-browser constraint as D1 — backend guard verified live, frontend disabled-state rendering traced in code."
  - id: D3
    description: "A running batch can be stopped from the UI via a Stop control"
    requirement: GEN-05
    verification:
      - kind: integration
        ref: "Live: started a batch (POST .../generate), then POST .../generate/cancel -> 200 {status:cancelled}; polled segment afterward: generation_status reset to 'pending', audio_path null. POST .../generate/cancel with nothing running -> 200 {status:not_running}"
        status: pass
      - kind: other
        ref: "Code trace: ConfigPanel.tsx handleStop() calls cancelBatchGeneration(project.id) then onRefresh(); Stop button renders while isBatchRunning"
        status: pass
    human_judgment: true
    rationale: "Same no-browser constraint — the cancel endpoint's full effect (batch stops, rows reset) was verified live end-to-end; only the Stop button's click wiring was traced in code, not clicked."
  - id: D4
    description: "A character with no preview shows why and can have a preview generated on demand from the Config Panel"
    requirement: CFG-03
    verification:
      - kind: e2e
        ref: "Live: POST /characters/{id}/preview -> 200 {status:generating}; POST to a missing character -> 404; polled GET /projects/{id} until preview_audio_path landed (~40s, real GPU synthesis); downloaded GET /characters/{id}/preview.wav -> 200, valid 284KB RIFF/WAVE file"
        status: pass
      - kind: other
        ref: "Code trace: CharacterPreviewRow — disabled Play gets title='No preview generated yet'; 'Generate preview' button calls triggerCharacterPreview then polls onRefresh every 1.5s (15s ceiling) until hasPreview flips true"
        status: pass
    human_judgment: true
    rationale: "Same no-browser constraint — the full preview pipeline (trigger -> real TTS synthesis -> playable audio) was verified live end-to-end; only the button's rendering/click wiring was traced in code."

duration: ~20min (2 auto tasks) + live verification
completed: 2026-07-12
status: complete
---

# Phase 03-09: Frontend generation controls Summary

**Status-driven per-row Generate/Play button, a Generate All guard that also watches per-row generating state, a Stop control that cancels a running batch, and an on-demand character-preview trigger — all wired to plan 03-08's backend guards and verified live against the real running app.**

## Performance

- **Tasks:** 2/2 auto tasks (checkpoint verified by orchestrator, not a separate continuation)
- **Files modified:** 4

## Accomplishments
- `client.ts` gained `cancelBatchGeneration` and `triggerCharacterPreview` wrappers following the existing `parseJsonOrThrow` pattern.
- `SegmentTable.tsx`'s `GeneratePlayButton` now disables/spins on `isGenerating || segment.generation_status === "generating"`, not just its own local click flag — a row driven into 'generating' by a batch run (or another trigger) is now correctly locked out.
- `ConfigPanel.tsx`: Generate All is disabled on `isBatchRunning || anyGenerating` (any segment generating, not only the batch SSE stream); a Stop button appears while a batch runs and calls the cancel endpoint; `CharacterPreviewRow` shows an explanatory tooltip and a "Generate preview" trigger for a character with no preview yet, polling (bounded, 1.5s/15s ceiling) until the result lands.
- `ProjectScreen.tsx` threads a `refetch`-backed `onRefresh` callback into `ConfigPanel` so Stop/preview actions can pick up fresh server state.
- `npm run build` (tsc -b + vite) passes.

**Checkpoint (Task 3) verification — live, on the running production backend** (this session runs directly on the `tts` VM). Rebuilt `localhost/qwen-ebook-backend:dev` from this worktree first — the running container still had the pre-03-08 image, so `/characters/{id}/preview` 405'd until rebuilt. After rebuild + restart (confirmed prior projects survived, per plan 03-06):

1. **Duplicate per-row guard:** started `POST /segments/{id}/generate` on a real segment; an immediate duplicate call to the same segment returned `409 "Segment is already generating"` — the exact signal `isRowGenerating` disables the button on.
2. **Generate All guard:** `POST /projects/{id}/generate` → `202 {"status":"started"}`; an immediate duplicate → `202 {"status":"already_running"}`; segment observed `generating` mid-flight — the exact signal `anyGenerating`/`isRunning` disables Generate All on.
3. **Stop:** started a batch, called `POST .../generate/cancel` → `200 {"status":"cancelled"}`; the in-flight segment reset to `pending` with `audio_path: null` afterward, exactly as the plan specifies ("in-flight-marked rows reset to pending"). Calling cancel with nothing running returned `200 {"status":"not_running"}` (no-op).
4. **Preview:** `POST /characters/{id}/preview` on a character with no preview → `200 {"status":"generating"}`; a missing character → `404`; polled until `preview_audio_path` landed (~40s, real GPU TTS synthesis); downloaded `GET /characters/{id}/preview.wav` → `200`, a valid 284KB RIFF/WAVE file.

Every backend contract the frontend code depends on was exercised live and end-to-end (including real audio synthesis, not mocked). The frontend's own rendering (button disabled/spinner, Stop button visibility, tooltip text) was confirmed by reading the exact shipped diff rather than observed in a browser — **this VM has no display/browser** (`DISPLAY` unset, no chromium/firefox/playwright installed, and the project's frontend intentionally carries no test framework). Every conditional branch driving that rendering (`isRowGenerating`, `anyGenerating`/`isRunning`, `isBatchRunning`, `hasPreview`/`isGeneratingPreview`) reads directly off state now confirmed correct live, so the logical chain is unbroken even without a literal click-through.

## Task Commits

1. **Task 1: client wrappers + per-row button driven by live generation_status** - `d289048` (feat)
2. **Task 2: Config Panel — Generate All guard, Stop control, on-demand preview** - `7683e80` (feat)
3. **Task 3: Human-verify generation controls, Stop, and on-demand preview** - verified live by the orchestrator (see Accomplishments); no code change

**Plan metadata:** this commit (docs: complete plan)

## Files Created/Modified
- `frontend/src/api/client.ts` - `cancelBatchGeneration`, `triggerCharacterPreview` wrappers
- `frontend/src/components/SegmentTable.tsx` - `GeneratePlayButton` reads live `generation_status`
- `frontend/src/components/ConfigPanel.tsx` - Generate All guard, Stop control, on-demand preview UI
- `frontend/src/components/ProjectScreen.tsx` - threads `onRefresh` into `ConfigPanel`

## Decisions Made
- Preview generation has no SSE channel (it's a one-off background task), so the UI polls the parent `refetch` on an interval with a hard ceiling rather than adding new streaming infrastructure for a single on-demand action.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- The worktree agent that first attempted this plan hit a `worktree_branch_check` FATAL (stale `origin/HEAD` base) on an earlier session-wide issue; the orchestrator had already fixed `worktree.baseRef` by the time this plan dispatched, so this plan's own dispatch was clean.
- **Pre-existing, out-of-scope finding:** synthesizing a long segment (the sample.txt fixture's repeated-sentence narrator text, ~700 chars) hit the documented 300s `httpx.ReadTimeout` ceiling in `tts_client.py` and the row correctly settled to `generation_status: 'error'` (not stuck) — this is the known synchronous-httpx-in-threadpool ceiling plan 03-08 already documents at the cancel endpoint, not a defect introduced by this plan. Flagging in case very long segments turn out to need a longer timeout or chunking in a future phase; out of scope here.
- No browser/display available on the verification host (see checkpoint note above) — verification substituted live, end-to-end API tracing (including real TTS synthesis) plus full code-path tracing for the parts of the flow that could not be assumed.

## User Setup Required
None.

## Next Phase Readiness
All four test-4 frontend gaps (duplicate per-row generate, stale Generate All enablement, no way to stop, unexplained/ungeneratable preview) are closed and verified against the real running backend, completing this phase's UAT gap-closure work (03-06 through 03-09).

---
*Phase: 03-editable-table-full-generation-pipeline-persistence-deployme*
*Completed: 2026-07-12*
