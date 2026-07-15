# Roadmap: Qwen Ebook Narrator

## Milestones

- ✅ **v1.0 MVP** — Phases 1-3 (shipped 2026-07-12)
- 🚧 **v1.1 Generation UX & Config Rework** — Phases 4-7 (in progress)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-3) — SHIPPED 2026-07-12</summary>

- [x] Phase 1: Upload-to-Audio Spike (TTS/ROCm De-risk) (3/3 plans) — completed 2026-07-09
- [x] Phase 2: LLM Cast Detection & Review Wizard (5/5 plans) — completed 2026-07-10
- [x] Phase 3: Editable Table, Full Generation Pipeline, Persistence & Deployment (9/9 plans) — completed 2026-07-12

Full details archived: `.planning/milestones/v1.0-ROADMAP.md`

</details>

### 🚧 v1.1 Generation UX & Config Rework (In Progress)

**Milestone Goal:** Replace ambiguous status indicators with a single clear color-coded generate/stop/play control everywhere audio is generated, and give the user real control over model, output format, filename, and downloading the finished file.

- [x] **Phase 4: Immediate Cancellation** - Stopping a segment, character preview, or batch generation interrupts the in-flight GPU call immediately, not just the queue (completed 2026-07-14)
- [x] **Phase 5: On-Demand Model Swap** - User can switch between the 1.7B and 0.6B Qwen TTS models per project, with VRAM-safe load/unload and a steering-limitation warning (completed 2026-07-14)
- [x] **Phase 6: Config Panel — Output Format, Filename & Download** - User can pick FLAC/MP3/Opus, set a custom filename, and download the finished joined file (completed 2026-07-15)
- [ ] **Phase 7: Unified Generate/Stop/Play Button & Trimmed Segment Table** - One consistent yellow/red/green control replaces all four hand-rolled generate/play implementations and the separate status badge column

## Phase Details

### Phase 1: Upload-to-Audio Spike (TTS/ROCm De-risk)

**Status**: Complete (v1.0) — see `.planning/milestones/v1.0-ROADMAP.md` for full detail

### Phase 2: LLM Cast Detection & Review Wizard

**Status**: Complete (v1.0) — see `.planning/milestones/v1.0-ROADMAP.md` for full detail

### Phase 3: Editable Table, Full Generation Pipeline, Persistence & Deployment

**Status**: Complete (v1.0) — see `.planning/milestones/v1.0-ROADMAP.md` for full detail

### Phase 4: Immediate Cancellation

**Goal**: User can stop any in-flight TTS generation — a segment preview, a character voice preview, or a running batch — and have the underlying GPU call itself interrupted immediately, not merely the queue of remaining work.
**Depends on**: Phase 3 (v1.0 baseline — extends the existing generation pipeline and generation lock)
**Requirements**: GEN-06, GEN-07, GEN-08
**Success Criteria** (what must be TRUE):

  1. User can click Stop on a generating segment and its GPU inference halts immediately, not merely gets prevented from a next queued call
  2. User can click Stop on a generating character voice preview and its GPU inference halts immediately
  3. User can click Stop on a running Generate All batch and the currently in-flight segment's generation halts immediately, not just skips remaining queued segments
  4. Immediately after any stop completes, the user can start a new generation without errors or a stuck "still generating" state — proving the interruption is real, not cosmetic

**Plans**: 4/4 plans complete
**Wave 1**

- [x] 04-01-PLAN.md — D-02 spike: StoppingCriteria cancellation machinery + real-hardware abort-timing validation (checkpoint-gated)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 04-02-PLAN.md — HTTP cancel surface: tts_service POST /cancel + best-effort backend tts_client.cancel()

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 04-03-PLAN.md — Backend restructure: async 202 segment generate, label-keyed task registry, segment/character/batch cancel endpoints, hold-lock-until-stopped

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 04-04-PLAN.md — Frontend: bare-bones Stop + distinct "stopping…" state on segment/character/batch, 202+poll wiring, D-06 caveat copy fix

### Phase 5: On-Demand Model Swap

**Goal**: User can pick between two Qwen TTS model sizes per project, and the app safely swaps the resident model in VRAM on demand, warning about the smaller model's steering limitation.
**Depends on**: Phase 4 (reuses the `tts_service` engine-state module and single-flight lock extended in Phase 4)
**Requirements**: CFG-04, CFG-05
**Success Criteria** (what must be TRUE):

  1. User can select "Higher quality (1.7B)" or "Faster (0.6B)" for a project
  2. Selecting a different model swaps the resident model in VRAM (only one loaded at a time) before the next generation uses it
  3. When the 0.6B model is selected, the UI warns the user that free-text voice-instruction steering isn't supported by that checkpoint
  4. Segments generated after a model swap reflect the newly selected model — no stale cached audio from the previously loaded model is served

**Plans**: 3/3 plans complete
**UI hint**: yes

**Wave 1** *(parallel — disjoint files)*

- [x] 05-01-PLAN.md — tts_service engine: singleton → ensure_loaded(model_id) swap + POST /model/{id}/load + real-hardware VRAM swap-cycle test
- [x] 05-02-PLAN.md — backend orchestration: Project.tts_model column, model_id in cache key, tts_client.load_model, POST /projects/{id}/model handler with lock + segment/preview invalidation (D-02/D-05/D-06)

**Wave 2** *(blocked on Wave 1)*

- [x] 05-03-PLAN.md — frontend + integration: Config Panel Model dropdown (D-01/D-02/D-03), disabled Voice Instructions cells on 0.6B (D-04), end-to-end human-verify on the deploy target

### Phase 6: Config Panel — Output Format, Filename & Download

**Goal**: User can choose the output audio format, set a custom output filename, and download the finished joined file once generation completes, all from the config panel UI.
**Depends on**: Phase 3 (v1.0 baseline) — technically independent of Phases 4-5's TTS/cancellation work; sequenced here per research's default milestone build order
**Requirements**: CFG-06, CFG-07, CFG-08
**Success Criteria** (what must be TRUE):

  1. User can select FLAC, MP3, or Opus as the output format (WAV is no longer offered)
  2. User can set a custom output filename before generating the final file
  3. Once the joined file is ready, user can click a blue "Download" button to save it under the chosen filename
  4. The downloaded file matches the selected format (correct extension, content type, and audio codec)

**Plans**: 3/3 plans complete
**UI hint**: yes

**Wave 1**

- [x] 06-01-PLAN.md — backend: Project.output_format/output_filename columns, 3-way ffmpeg CODEC_TABLE (FLAC/MP3/Opus), per-project format read + D-07 delete-old, PATCH /projects/{id} config + GET /projects/{id}/download (CFG-06/07/08)

**Wave 2** *(blocked on Wave 1)*

- [x] 06-02-PLAN.md — frontend: editable Output Format Select, Output Filename Input + extension suffix, blue Download button wired to the new endpoints

**Wave 3** *(blocked on Wave 2)*

- [x] 06-03-PLAN.md — human-verify: format/filename/download end-to-end on the deploy target (checkpoint-gated)

### Phase 7: Unified Generate/Stop/Play Button & Trimmed Segment Table

**Goal**: Every place audio is generated (segment, character preview, batch) uses one consistent yellow/red/green generate/stop/play UI component, and the segment table shows only the 3 core editable columns with no separate status indicator.
**Depends on**: Phase 4, Phase 5, Phase 6 (wires up the async stop contract from Phase 4 and the model/format/download controls from Phases 5-6 into the unified button)
**Requirements**: GEN-09, GEN-10, GEN-11, GEN-12, TBL-05
**Success Criteria** (what must be TRUE):

  1. Each segment row shows a single button that is yellow "Generate Preview" when idle/stale, red "Stop Generation" while generating, and green "Play" once audio exists
  2. Each character preview control follows the same yellow/red/green generate/stop/play pattern
  3. The Generate All control follows the same pattern, and once the joined output file is ready it additionally shows a green "Play" to preview it in-browser
  4. Editing a segment's or character's text, voice instructions, or narrator immediately reverts its control back to yellow, with no separate status badge anywhere in the UI
  5. The segment table shows exactly 3 editable columns (Narrator, Voice Instructions, Text) — the Status badge column is gone

**Plans**: 5 plans
**UI hint**: yes

**Wave 1**

- [ ] 07-01-PLAN.md — foundation: shared useGenerateStopPlay hook + presentational GenerateStopPlayButton + outputUrl helper (GEN-12)

**Wave 2** *(parallel — disjoint files)*

- [ ] 07-02-PLAN.md — SegmentTable: swap in unified button, delete Status column/badge code + dead imports (GEN-09, TBL-05, D-07)
- [ ] 07-03-PLAN.md — ConfigPanel: unify character-preview row + batch Generate All, joined-output green Play with Pitfall-2 precedence, Download unchanged (GEN-10, GEN-11, D-04)
- [ ] 07-04-PLAN.md — CharacterCard gains real Stop via shared button + CastWizard xl:items-start layout fix; SegmentPreview untouched (GEN-10, D-01/D-02/D-05)

**Wave 3** *(blocked on Wave 2)*

- [ ] 07-05-PLAN.md — human-verify: all four buttons, joined-output Play, edit-reverts, trimmed table, layout, and the Pitfall-2 regenerate case end-to-end (checkpoint-gated)

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|-----------------|--------|-----------|
| 1. Upload-to-Audio Spike (TTS/ROCm De-risk) | v1.0 | 3/3 | Complete | 2026-07-09 |
| 2. LLM Cast Detection & Review Wizard | v1.0 | 5/5 | Complete | 2026-07-10 |
| 3. Editable Table, Full Generation Pipeline, Persistence & Deployment | v1.0 | 9/9 | Complete | 2026-07-12 |
| 4. Immediate Cancellation | v1.1 | 4/4 | Complete    | 2026-07-14 |
| 5. On-Demand Model Swap | v1.1 | 3/3 | Complete    | 2026-07-14 |
| 6. Config Panel — Output Format, Filename & Download | v1.1 | 3/3 | Complete    | 2026-07-15 |
| 7. Unified Generate/Stop/Play Button & Trimmed Segment Table | v1.1 | 0/5 | Not started | - |
