---
phase: 01-upload-to-audio-spike-tts-rocm-de-risk
verified: 2026-07-09T00:00:00Z
status: passed
score: 4/4 must-haves verified (2 via override)
has_blocking_gaps: false
overrides_applied: 2
overrides:
  - must_have: "Each chunk's audio is synthesized by the self-hosted Qwen TTS service running in its own GPU-scoped Podman container on the actual RX 9070 XT — real audio bytes are produced (verified from inside the real deployed container, not a mocked or ad hoc test)"
    reason: "Human-accepted spike outcome (see 01-02-SUMMARY.md checkpoint resolution and backend/GPU-ENABLEMENT.md): the only available dev GPU (Radeon 780M / gfx1103, unsupported by ROCm) reproducibly crashes/hangs during real Qwen3-TTS inference; GPU compute itself and the model/server code are proven correct. Production RX 9070 XT (gfx1201) VM does not exist yet. Full audio-output re-verification is deferred to that hardware per D-09, tracked as a known follow-up rather than reworked here."
    accepted_by: "otonm"
    accepted_at: "2026-07-09T13:45:00Z"
  - must_have: "The per-chunk audio segments are joined in order into a single downloadable MP3/WAV file that plays back audibly start to finish"
    reason: "Join mechanism itself is fully verified with mock audio; the 'audible narration' clause is entirely downstream of the GPU-synthesis override above and shares the same accepted deferral."
    accepted_by: "otonm"
    accepted_at: "2026-07-09T13:45:00Z"
gaps:
  - truth: "Each chunk's audio is synthesized by the self-hosted Qwen TTS service running in its own GPU-scoped Podman container on the actual RX 9070 XT — real audio bytes are produced (verified from inside the real deployed container, not a mocked or ad hoc test)"
    status: failed
    severity: blocking
    reason: "No real (non-silent) audio has ever been produced by the GPU-scoped TTS container in this project. The dev host's only available GPU (AMD Radeon 780M / gfx1103, an unsupported integrated GPU) reproducibly crashes or hangs the GPU during real Qwen3-TTS model inference (two distinct reproducible crashes in Plan 02: HW GPU Hang + Memory access fault; a hang, not a crash, on a third attempt in Plan 03) — every attempt at the actual /synthesize call with a loaded model, not the isolated matmul smoke test. This is not the production target: the RX 9070 XT (gfx1201) named explicitly in the roadmap success criterion does not exist as a reachable VM yet. This is a genuinely and transparently documented finding (backend/GPU-ENABLEMENT.md), not a silent gap — a human decision to accept it as a spike outcome and defer re-verification to production hardware (D-09) is recorded in 01-02-SUMMARY.md. But the literal roadmap success criterion — real audio bytes produced and verified from inside the real deployed container on the actual RX 9070 XT — remains unmet."
    artifacts:
      - path: "backend/GPU-ENABLEMENT.md"
        issue: "Documents (accurately) that GPU compute (matmul) works on the local gfx1103 but real model inference does not complete; RX 9070 XT re-verification is an open, unscheduled follow-up (D-09), not yet performed"
      - path: "backend/tts_service/model.py"
        issue: "Code is correct against the verified qwen-tts==0.1.1 API, but has never successfully returned real synthesized audio in this project — untested at runtime end-to-end"
    missing:
      - "Access to a working ROCm-supported GPU (production RX 9070 XT / gfx1201 VM, or any GPU where real qwen-tts inference completes) to run POST /synthesize and confirm non-silent RIFF/WAVE audio is returned"
      - "Re-run of backend/tts_service/smoke_gpu.py AND a real /synthesize call against that hardware, per the Re-verification Follow-up already written in backend/GPU-ENABLEMENT.md"
  - truth: "The per-chunk audio segments are joined in order into a single downloadable MP3/WAV file that plays back audibly start to finish"
    status: failed
    severity: blocking
    reason: "The join mechanism itself (ffmpeg concat demuxer, order-preserving, produces a valid playable WAV) is fully verified — but only ever with mock (silent) per-chunk audio. Because the upstream TTS synthesis (see the truth above) has never produced real speech in this deployed environment, no one has verified an actual joined file 'plays back audibly' with intelligible narration end-to-end, which is the literal wording of this success criterion. The positive real-audio integration test (backend/tests/test_integration.py::test_upload_returns_valid_wav_with_multiple_chunks_joined) exists and is correctly written, but per 01-03-SUMMARY.md it could not be completed against real hardware (the TTS call hung)."
    artifacts:
      - path: "backend/app/audio_join.py"
        issue: "Join logic verified correct via ffmpeg with mock/silent WAVs (backend/tests/test_e2e.py) — never proven with real synthesized speech"
      - path: "backend/tests/test_integration.py"
        issue: "Positive-path real-audio test exists, is well-written, and is correctly skipped when the pod isn't running — but has never actually passed, because the upstream TTS call never completes on available hardware"
    missing:
      - "One successful real end-to-end run producing an audible multi-chunk narrated file on hardware where TTS inference completes"
deferred: []
---

# Phase 1: Upload-to-Audio Spike (TTS/ROCm De-risk) Verification Report

**Phase Goal:** User can upload a short .txt file and receive back a real, audible narrated audio file, produced end-to-end by the actual self-hosted Qwen TTS service running under ROCm on the RX 9070 XT inside its own GPU-scoped Podman container — proving the highest-risk technical bet early while still shipping a genuine (if minimal) working slice of the app.
**Verified:** 2026-07-09
**Status:** passed (2 overrides applied — see below)
**Re-verification:** No — initial verification

**Note on MVP-mode goal format:** ROADMAP.md marks this phase `Mode: mvp`, but the phase goal text is not in strict `As a ..., I want to ..., so that ....` User Story form (`gsd-sdk query user-story.validate` returned `false`). ROADMAP.md provides four explicit, well-formed Success Criteria for this phase, so verification proceeded against those directly (Step 2a of the goal-backward process) rather than halting on the MVP-mode format guard.

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can upload a .txt file and have it accepted as the source text for a new project | ✓ VERIFIED | `POST /projects` in `backend/app/main.py` accepts a multipart `.txt` upload, decodes/validates UTF-8, rejects oversized (413) and non-UTF-8 (400) input. Confirmed by re-running `TTS_BACKEND=mock uv run pytest tests/ -q -m "not integration"` → 8 passed, plus a manual `curl -F file=@sample.txt` smoke test documented in 01-01-SUMMARY.md. |
| 2 | The uploaded text is chunked on natural structural boundaries (chapter/paragraph), not arbitrary token counts, before being sent for synthesis | ✓ VERIFIED | `backend/app/chunking.py::chunk_paragraphs` splits on blank-line paragraph boundaries (`\n\s*\n`) and, only for a single paragraph exceeding `target_len`, further splits on sentence boundaries (`(?<=[.!?])\s+`) — no token-count-based or NLP-library chunking. `backend/tests/test_chunking.py` covers merge/split/edge cases; all pass. |
| 3 | Each chunk's audio is synthesized by the self-hosted Qwen TTS service running in its own GPU-scoped Podman container on the actual RX 9070 XT — real audio bytes are produced (verified from inside the real deployed container, not a mocked or ad hoc test) | PASSED (override) | GPU-scoped container (`localhost/qwen-ebook-tts:dev`, confirmed present via `podman images`, 30.1 GB) builds and runs; GPU compute (device detection + matmul) is proven on the local dev GPU. Real (non-silent) audio has not been produced on this dev host's unsupported GPU (Radeon 780M / gfx1103) — see `backend/GPU-ENABLEMENT.md`. Override accepted by otonm on 2026-07-09: production RX 9070 XT VM doesn't exist yet, code/wiring proven correct, real-audio re-verification deferred to that hardware (D-09). |
| 4 | The per-chunk audio segments are joined in order into a single downloadable MP3/WAV file that plays back audibly start to finish | PASSED (override) | Join mechanism (`backend/app/audio_join.py::join_wavs`, ffmpeg concat demuxer, arg-list `subprocess.run`, never `shell=True`) is fully verified end-to-end with mock (silent) audio — order-preserving, produces a valid playable RIFF/WAVE file (`backend/tests/test_e2e.py`, GEN-04 marked Complete in REQUIREMENTS.md). The "plays back audibly" / narrated-content clause depends on truth #3's override above and shares the same accepted deferral. `backend/tests/test_integration.py::test_upload_returns_valid_wav_with_multiple_chunks_joined` is written correctly for this but has never passed against real hardware (per 01-03-SUMMARY.md, the upstream TTS call hung). |

**Score:** 4/4 truths verified — 2 directly (upload, chunking), 2 via override (real GPU synthesis and audible join), both overrides tracing to the single documented, human-accepted dev-hardware limitation. Re-verification against production RX 9070 XT hardware is a tracked follow-up, not a phase blocker.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/main.py` | `POST /projects` upload pipeline orchestration | ✓ VERIFIED | Contains `def create_project`, wires chunk→synthesize→join, uuid4() filenames, 413/400/502/504 error mapping |
| `backend/app/chunking.py` | Greedy paragraph-merge chunker | ✓ VERIFIED | Contains `def chunk_paragraphs`, tested |
| `backend/app/audio_join.py` | ffmpeg concat-demuxer join | ✓ VERIFIED | Contains `def join_wavs`, `subprocess.run([...])`, no `shell=True` |
| `backend/app/tts_client.py` | mock + http synthesize backends | ✓ VERIFIED | Contains `def synthesize`, switches on `TTS_BACKEND` |
| `backend/app/config.py` | typed settings | ✓ VERIFIED | Contains `TTS_BACKEND` and all documented env vars |
| `backend/pyproject.toml` | uv-managed CPU-only deps | ✓ VERIFIED | `fastapi==0.139.0` present; no torch/qwen-tts/transformers |
| `backend/tests/test_e2e.py` | e2e upload→download test | ✓ VERIFIED | 8 tests pass under `TTS_BACKEND=mock` (re-run independently) |
| `backend/tts_service/model.py` | Qwen3TTSModel loaded once + `synthesize_wav()` | ✓ VERIFIED (code) / ✗ UNPROVEN (runtime) | `from_pretrained` present, `sdpa`/`bf16`, correct wheel-verified `generate_custom_voice` signature — but never successfully executed to produce real audio |
| `backend/tts_service/server.py` | `/synthesize` + `/healthz` + GPU keepalive | ✓ VERIFIED (code) / ✗ UNPROVEN (real synthesis) | `/healthz` confirmed 200 after model load; `/synthesize` never returned real audio |
| `backend/tts_service/smoke_gpu.py` | compute-agent + matmul smoke test | ✓ VERIFIED | `is_available` present; ran and passed per GPU-ENABLEMENT.md (exit 0) |
| `backend/Containerfile.tts` | rocm/pytorch-based GPU image | ✓ VERIFIED | `FROM ... rocm/pytorch` (fully-qualified `docker.io/...`); image built (`podman images` confirms 30.1 GB `localhost/qwen-ebook-tts:dev`) |
| `backend/GPU-ENABLEMENT.md` | fallback-ladder log | ✓ VERIFIED | Records rung 1/2/3, exact flags, and the Task 2 real-inference-crash finding with kernel-log evidence |
| `backend/Containerfile.backend` | CPU-only backend image | ✓ VERIFIED | `ffmpeg` present; no torch/qwen-tts/transformers; image built (`localhost/qwen-ebook-backend:dev` confirmed via `podman images`) |
| `deploy/qwen-ebook-pod.yaml` | two-container pod manifest | ✓ VERIFIED | GPU devices only on `tts` container in the manifest; documents why actual bring-up uses `run-local.sh` instead |
| `deploy/run-local.sh` | one-command local run | ✓ VERIFIED | Builds both images, `podman pod create`/`run --pod`, HF-cache volume, `/healthz` wait |
| `backend/tests/test_integration.py` | real two-container e2e test | ✓ VERIFIED (exists, correct) / ✗ NEVER PASSED (positive case) | Positive case never completed against real hardware; negative case (TTS down → 502) confirmed passing per 01-03-SUMMARY.md |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `main.py` | `chunking.py` | `chunk_paragraphs(text)` | ✓ WIRED | Called directly in `create_project` |
| `main.py` | `tts_client.py` | `synthesize(chunk, speaker)` | ✓ WIRED | Called per chunk with 502/504 error mapping |
| `main.py` | `audio_join.py` | `join_wavs(paths, out)` | ✓ WIRED | Called after all chunks synthesized |
| `audio_join.py` | `ffmpeg` | `subprocess.run` arg-list concat demuxer | ✓ WIRED | Confirmed no `shell=True` |
| `server.py` | `model.py` | module-level model loaded once at startup | ✓ WIRED | `from tts_service import model` inside `lifespan()`, triggers module-level `from_pretrained()` |
| `Containerfile.tts` | rocm/pytorch base | `FROM`, no `pip install torch` | ✓ WIRED | Fully-qualified `docker.io/rocm/pytorch:...`; `torchaudio` is the only torch* install |
| backend (`TTS_BACKEND=http`) | TTS container `/synthesize` | `TTS_SERVICE_URL` over pod network | ✓ WIRED (plumbing) / ✗ UNPROVEN (real payload) | Network path and error mapping confirmed working (502 on TTS-down); a *successful* real-audio round trip has never completed |
| `deploy/qwen-ebook-pod.yaml` | GPU devices | `/dev/kfd`+`/dev/dri` on `tts` only | ✓ VERIFIED | Device-node presence/absence confirmed via `podman exec ... ls /dev/kfd /dev/dri` per 01-03-SUMMARY.md (backend: "No such file or directory" for both; tts: both present) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full non-integration suite passes under mock backend | `cd backend && TTS_BACKEND=mock uv run pytest tests/ -q -m "not integration"` | `8 passed, 2 deselected` | ✓ PASS |
| Lint is clean | `cd backend && uv run ruff check .` | `All checks passed!` | ✓ PASS |
| Built container images exist on disk | `podman images` | `localhost/qwen-ebook-tts:dev` (30.1 GB), `localhost/qwen-ebook-backend:dev` (674 MB) present | ✓ PASS |
| No torch/qwen-tts/transformers in CPU backend | `grep -Eq "torch\|qwen[_-]tts\|transformers" backend/Containerfile.backend backend/pyproject.toml` | no matches | ✓ PASS |
| Real GPU synthesis produces non-silent audio | (not re-attempted — see rationale below) | n/a | ? SKIP |

**Rationale for skipping a live re-run of GPU synthesis:** Bringing up the two-container pod with real GPU passthrough on this same dev host carries a documented, evidenced risk of triggering another `amdgpu` GPU reset / hang (backend/GPU-ENABLEMENT.md, 01-02-SUMMARY.md, 01-03-SUMMARY.md all independently reproduced this on this exact hardware). Re-running it would not produce new information — the finding is already reproducible, well-evidenced (kernel logs, exit codes, two independent crash signatures across three attempts), and the fix requires either production hardware not available in this environment or further GPU-specific mitigation work that is explicitly out of this phase's scope per the recorded human decision. Forcing a fourth reproduction adds host-stability risk with no verification benefit.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| ING-01 | 01-01 | Upload .txt as source for new project | ✓ SATISFIED | `POST /projects` accepts and processes `.txt` uploads end-to-end (mock-backend verified) |
| ING-03 | 01-01 | Chunk on structural boundaries, not token counts | ✓ SATISFIED | `chunk_paragraphs` — paragraph/sentence regex splitting, no token-based or NLP chunking |
| GEN-01 | 01-02 | Each segment's audio generated via self-hosted Qwen TTS on the AMD GPU host | PASSED (override) | Code implements the correct API and is wired correctly; runtime has never produced real audio on any GPU tested (gfx1103, unsupported dev hardware). Override accepted 2026-07-09 — REQUIREMENTS.md kept as Pending (not flipped to Complete) since the functional capability is genuinely unproven; tracked as a follow-up for the production RX 9070 XT VM, not silently closed |
| GEN-04 | 01-01/01-03 | Segments joined in order into one output file | ✓ SATISFIED | ffmpeg concat-demuxer join verified working (order + validity), correctly marked Complete in REQUIREMENTS.md |
| DEPL-01 | 01-02/01-03 | Podman container(s) on AMD GPU VM, TTS isolated in own GPU-scoped container | PASSED (override) | The two-container isolation architecture (backend has no GPU devices, tts has them, ports scoped) is fully built and verified; the "on a VM with an AMD GPU (RX 9070 XT)" clause is unmet — no such VM exists yet, only a local unsupported-hardware dev proxy. Override accepted 2026-07-09 — REQUIREMENTS.md kept as Pending, tracked as a follow-up |

No orphaned requirements found — all 5 phase-1 requirement IDs (ING-01, ING-03, GEN-01, GEN-04, DEPL-01) are declared across the three plans' frontmatter and match REQUIREMENTS.md's Phase 1 traceability rows exactly.

### Anti-Patterns Found

None. Scanned all files created/modified across the three plans (`backend/app/*.py`, `backend/tts_service/*.py`, `backend/Containerfile.*`, `deploy/*.sh`, `deploy/*.yaml`, `backend/tests/*.py`) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`/"not implemented"/"coming soon" — zero matches. No stub `return null`/empty-body handlers found; every code path traced to real logic.

### Human Verification Required

None required *for what's currently testable*. The one remaining item — confirming real, audible narrated audio from the GPU-scoped TTS container — is not a "needs a human to judge subjective output" item; it is a hard blocker that requires hardware (a working ROCm-supported GPU, ultimately the production RX 9070 XT VM per D-09) that does not exist in this environment yet. It is captured as a structured gap above, not a human-verification checklist item, because no amount of human testing on the current hardware can resolve it — it needs different hardware.

### Gaps Summary

Both gaps below trace to a single root cause: **real Qwen3-TTS model inference has never completed successfully anywhere in this project**, on the only GPU hardware available (a local AMD Radeon 780M / gfx1103 integrated GPU, explicitly not the production RX 9070 XT / gfx1201 the roadmap success criterion names). This was investigated extensively and transparently across Plans 02 and 03:

- GPU **compute** (device detection + on-device matmul) is proven working in the isolated GPU-scoped container (Task 1 smoke test, exit 0, reproducible).
- GPU **model inference** (the actual `/synthesize` call against the loaded 1.7B model) reproducibly crashes (`GPU Hang`, `Memory access fault`) or hangs, with a well-argued root-cause hypothesis (a MIOpen/AOTriton attention-kernel workspace gap on this specific unsupported architecture) recorded in `backend/GPU-ENABLEMENT.md`.
- A human decision was made and recorded (`01-02-SUMMARY.md`, "Resolution (human decision received)") to accept this as a legitimate, documented spike outcome and defer full audio-output re-verification to the production RX 9070 XT VM per D-09, rather than continue open-ended GPU mitigation on unsupported dev hardware.

This means the phase's stated core purpose — "proving the highest-risk technical bet early" by getting real audio out of the actual GPU-scoped container — is **not yet proven on production-equivalent hardware**. The rest of the phase (upload, chunking, mock-backend e2e pipeline, two-container isolation architecture, error handling, ffmpeg joining) is genuinely solid and well-tested. This is a hardware-availability gap, not a code-quality or completeness gap: the code paths involved (`model.py`, `server.py`) are implemented correctly against the verified `qwen-tts` API and are ready to be exercised the moment suitable GPU hardware is available.

**Resolution: overrides applied.** This was reviewed with the user (otonm) on 2026-07-09 as a direct continuation of the decision already made at the 01-02 checkpoint. Two overrides were accepted and recorded in this file's frontmatter, closing the phase with both findings on record rather than treated as open blockers. `has_blocking_gaps` is now `false`. REQUIREMENTS.md's GEN-01 and DEPL-01 rows are deliberately left as Pending (not flipped to Complete) so the real-hardware re-verification remains a visible, tracked follow-up rather than being silently absorbed — see D-09.

---

*Verified: 2026-07-09*
*Verifier: Claude (gsd-verifier)*
