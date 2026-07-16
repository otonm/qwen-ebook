# Milestones

## v1.1 Generation UX & Config Rework (Shipped: 2026-07-16)

**Phases completed:** 4 phases (4-7), 15 plans, 37 tasks
**Timeline:** 2026-07-13 → 2026-07-16 (4 days)

**Delivered:** True mid-flight GPU cancellation, on-demand 1.7B/0.6B model swap, output format/filename/download controls, and one unified yellow/red/green Generate/Stop/Play button across every generation site.

**Key accomplishments:**

- True immediate cancellation: `StoppingCriteria` patched into qwen-tts's decode loop (its wrapper silently drops the kwarg — fixed by patching `talker.generate` directly), verified to abort a live ROCm decode within ~46ms, exposed via `POST /cancel` + async 202/poll contract with label-keyed task registry and hold-lock-until-genuinely-stopped semantics.
- On-demand model swap: `ensure_loaded(model_id)` engine proven on the RX 9070 XT with zero VRAM drift over 10+ swap cycles; `Project.tts_model` threaded into the content-hash cache key so a swap can never serve stale cross-model audio; Config Panel Select with load-spinner/revert-on-failure UX and persistent 0.6B steering warning.
- Output controls: 3-way FLAC/MP3/Opus ffmpeg codec dispatch (single CODEC_TABLE, no new dependencies), per-project format/filename columns with sanitizing PATCH endpoint, and a blue Download button backed by a FileResponse route.
- UI unification: shared `useGenerateStopPlay` hook + `GenerateStopPlayButton` component collapsed four hand-rolled generate/play implementations (segment rows, character preview rows, CastWizard cards, batch Generate All) into one yellow/red/green control; CharacterCard gained its first working Stop; segment table trimmed to exactly 3 editable columns with the Status badge column deleted; joined-output in-browser green Play added.
- Verification depth: every phase human-verified on the real deploy target; post-completion standard code review fixed 8 further findings (3 critical, 5 warning); final UAT passed 23/23; security review closed all 10 threats (threats_open: 0).

**Known deferrals:** 1 acknowledged open item at close — SegmentPreview (wizard right panel) generate-all/stop capability, recorded in STATE.md Deferred Items (parts 1-2 of the originating todo shipped in Phase 7).

---

## v1.0 MVP (Shipped: 2026-07-12)

**Phases completed:** 3 phases, 17 plans, 39 tasks

**Key accomplishments:**

- A real FastAPI backend (`uv`-managed, no GPU deps) that accepts a `.txt` upload, chunks it into ~800-char paragraph blocks, synthesizes each chunk via a stdlib-only mock TTS backend, joins them with an ffmpeg concat-demuxer subprocess call, and returns one downloadable WAV — proven end-to-end with `TTS_BACKEND=mock` and zero GPU dependency.
- GPU-scoped Podman container for Qwen3-TTS built and proven for raw compute on local gfx1103 hardware (device detection + on-device matmul); real model inference reproducibly GPU-hangs on this specific dev iGPU (auto-recovers cleanly) -- accepted as a documented spike limitation, with audio-output verification deferred to the production RX 9070 XT VM per D-09.
- Wired the CPU backend and GPU-scoped TTS service together as a real two-container Podman pod with GPU devices isolated to the TTS container only, proved pod wiring/network isolation/graceful-degradation against the actual running containers; real audio synthesis deferred to the production RX 9070 XT VM (D-09), later resolved (see below).
- SQLModel/SQLite persistence and an async-worker + native SSE analysis pipeline: upload a .txt, get back a persisted narrator+character cast and ordered voice-tagged segments, streamed live, all against a mock LLM backend with zero xai_sdk import.
- EPUB upload support (ING-02): ebooklib+BeautifulSoup/lxml spine-order text extraction with EPUB3 footnote stripping, cover/copyright skip heuristic, and fail-fast rejection of unparseable chapters, wired into the existing POST /projects analysis pipeline.
- Real xai-sdk `chat.parse(CastAnalysisResult)` wiring with role-separated system/user messages, plus a multi-chunk fallback that re-supplies the running cast + last-20 segments to each subsequent Grok call so oversized books reconcile repeat characters by name instead of duplicating them.
- PATCH/merge character endpoints, a `/voices` preset list, and eager voice-preview generation guarded by a `voice_version` stamp so a rapid re-assignment can never leave a stale preview served.
- Single-page React cast-review wizard (Vite + shadcn/radix) — upload -> SSE-driven analyzing state -> inline-editable character cards with merge/voice-assign/instant native-audio preview -> read-only TanStack Table segment preview.
- Per-segment generate/patch/cache endpoints (content-hash sha256, last-request-wins version guard) plus an editable TanStack SegmentTable with blur-commit cells, verified against both TTS_BACKEND=mock (test suite) and the real gfx1201 GPU pod (Task 4 automated smoke).
- Checkbox row selection (header select-all + per-row) with a 48px bulk-action toolbar that reassigns narrator across selected segments in one validated POST /segments/bulk-reassign request, rejecting cross-project tampering.
- Resumable per-segment batch generation (stale-reset, cache-skip, continue-past-error, blocking join) driving live SSE progress into a new ConfigPanel with a Generate All/Resume Generation CTA — verified against both `TTS_BACKEND=mock` (11 tests) and real gfx1201 GPU synthesis including a simulated mid-batch crash and a concurrent per-row-edit race.
- GET /projects list endpoint plus a new ProjectListScreen landing route in App.tsx — the app now opens on a list of saved projects (filename/date/status) instead of straight into the upload form, and PERS-01 auto-save-by-construction is confirmed rather than rebuilt.
- Three Podman Quadlet units (`.pod` + 2 `.container`) translating `run-local.sh`'s ad hoc pod bring-up into a systemd-managed service, deployed on the production RX 9070 XT VM and exposed tailnet-only via `tailscale serve --bg 8000` — verified with a real end-to-end GPU generate through `https://tts.pigeon-bearded.ts.net`.
- Persistent `/data` named volume for the backend's SQLite DB/uploads/output plus a restart-resilient Quadlet unit set (pod exit-policy=continue, member Restart=on-failure), verified live on the production VM.
- useAnalysisStream now probes a no-data SSE error via a single guarded getProject() fetch, ending the infinite-reconnect loop for a stale/deleted projectId and driving App.tsx's existing error→recover-to-list path.
- Reversed GEN-03/D-06 to invalidate-only edits, added a per-project in-flight generation registry guarding both batch and per-row generate, a cancel endpoint for a running batch, and an on-demand character-preview trigger endpoint.
- Status-driven per-row Generate/Play button, a Generate All guard that also watches per-row generating state, a Stop control that cancels a running batch, and an on-demand character-preview trigger — all wired to plan 03-08's backend guards and verified live against the real running app.
- Production GPU passthrough fixed (commit `1ce34aa`): rootful Podman (not rootless `--group-add keep-groups`) required for `/dev/kfd` access on this Podman/crun combo — real non-silent Qwen TTS audio confirmed end-to-end on the RX 9070 XT VM (closing D-09/GEN-01/DEPL-01).
- Frontend now actually served (commit `63b705b`): the backend previously only exposed API routes, so the browser URL 404'd — added a Containerfile frontend build stage + `StaticFiles` mount, verified live over `tailscale serve`.

---
