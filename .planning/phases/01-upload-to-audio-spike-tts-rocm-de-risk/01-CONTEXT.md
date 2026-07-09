# Phase 1: Upload-to-Audio Spike (TTS/ROCm De-risk) - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

User can upload a short .txt file and receive back a real, audible narrated audio file, produced end-to-end by the actual self-hosted Qwen TTS service running under ROCm inside its own GPU-scoped Podman container — proving the highest-risk technical bet (Qwen TTS on ROCm/RDNA-class AMD hardware, in a GPU-passthrough Podman container) early, with a genuine (if minimal) working slice: upload → chunk → synthesize → join → download.

No LLM cast detection or narration/dialogue segmentation in this phase — that's Phase 2 (CAST-01/CAST-02/CAST-03). No web frontend — that's Phase 2/3 (both already carry UI hints in ROADMAP.md).

</domain>

<decisions>
## Implementation Decisions

### Chunking (non-LLM, Phase 1 only)
- **D-01:** Chunk plain .txt using Python stdlib/regex paragraph splitting (blank-line-delimited paragraphs) — no NLP library (NLTK/spaCy) dependency for this phase. Room to swap in a heavier parser later if needed.
- **D-02:** Greedily merge consecutive paragraphs into chunks up to a target length of ~500–1000 characters, so TTS calls aren't too short (excess joins) or too long (excess latency/risk per call).
- **D-03:** LLM-based interpretation of chunks into narrative/speech blocks is explicitly OUT of scope for Phase 1 — that's CAST-03 in Phase 2. Chunks in Phase 1 go straight to TTS with one voice, no per-segment character/style tagging.

### Voice (Phase 1 spike)
- **D-04:** Use a single default Qwen3-TTS-1.7B-CustomVoice built-in speaker preset for every chunk — plain preset playback, no free-text instruct-steering layered on top. Exact preset name to be picked during research/planning from `model.get_supported_speakers()`.

### API/UI surface
- **D-05:** Phase 1 ships as a FastAPI upload endpoint (curl/Postman-driven), not a web page. Endpoint accepts a .txt file, runs chunk → TTS → join, and returns the resulting audio file. Uses the same backend framework (FastAPI) the full app will use per CLAUDE.md, so this becomes the real app skeleton rather than throwaway code.
- **D-06:** No frontend work in Phase 1 — deferred to Phase 2/3.

### GPU/deployment verification
- **D-07:** Local dev machine's GPU is confirmed (via `lspci`/`glxinfo` during this discussion) to be an AMD Radeon 780M integrated GPU — "Phoenix/HawkPoint" APU, RDNA3, `gfx1103`, shared system RAM (not the RX 9070 XT's dedicated 16GB). User confirmed this GPU is usable with ROCm, despite not being on CLAUDE.md's explicitly-cited officially-supported list — trust the user's direct knowledge of their own system over the doc's caution here.
- **D-08:** Phase 1's success criterion #3 ("real audio, verified from inside the real deployed container, not mocked") is satisfied on this LOCAL hardware: build the actual Podman container with real GPU device passthrough (`/dev/kfd`, `/dev/dri`, `--group-add keep-groups`) and verify real synthesized audio bytes come out of it, running on the local Radeon 780M.
- **D-09:** The target production VM (RX 9070 XT) will not be ready until after a release ships — re-verification on that hardware is a fast follow-up sanity check once it's available, NOT a rebuild, and NOT something Phase 1 needs to provision. The plan/verification should explicitly flag "re-verify on target VM once available" as a tracked follow-up rather than silently treating Phase 1 as fully proving the target-hardware bet.

### Repo structure & tooling
- **D-10:** Pre-split monorepo from day one — `backend/` + `frontend/` directories at repo root, even though `frontend/` stays empty until Phase 2 starts UI work. Avoids a restructuring commit later.
- **D-11:** Python tooling: `uv` for dependency/venv management, `ruff` for lint/format — per CLAUDE.md's documented stack, confirmed as-is (no deviation).

### Claude's Discretion
- Exact target chunk length within the ~500–1000 char range.
- Exact CustomVoice preset name chosen for the spike.
- Whether a single paragraph that alone exceeds the target chunk length gets further split (e.g., at a sentence boundary) or kept whole as an oversized chunk.
- Internal `backend/` folder structure (routes/services/etc.) beyond the top-level `backend/` + `frontend/` split.

</decisions>

<specifics>
## Specific Ideas

- User, verbatim, on GPU verification timing: "the target will be ready after a release is done. for now keep to the local system."
- Local GPU confirmed via direct system inspection during this discussion: AMD Radeon 780M (Phoenix/HawkPoint APU, RDNA3, `gfx1103`) — no ROCm/`rocminfo`/`rocm-smi` found installed yet at discussion time; installing/configuring ROCm for this GPU is part of Phase 1 execution.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Tech stack (governs almost every Phase 1 implementation choice)
- `CLAUDE.md` (repo root) — Full technology stack decisions: Qwen3-TTS-1.7B-CustomVoice model choice and rationale, HF Transformers + `qwen-tts` package (not vLLM), PyTorch ROCm build, FastAPI backend, ffmpeg concat demuxer for joining audio, `TTS_BACKEND=mock` dev-degradation pattern, Podman + Quadlets deployment pattern, `uv`/`ruff` tooling, and the ROCm/RDNA4 version-compatibility notes. This is the primary implementation-decisions doc for this phase.

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 1: Upload-to-Audio Spike (TTS/ROCm De-risk)" — phase goal, success criteria, requirement mapping (ING-01, ING-03, GEN-01, GEN-04, DEPL-01)
- `.planning/REQUIREMENTS.md` §Ingestion (ING-01, ING-03), §Generation & Audio (GEN-01, GEN-04), §Deployment (DEPL-01) — exact requirement text for what's in scope
- `.planning/PROJECT.md` — project vision, hardware/deployment/network constraints
- `.planning/STATE.md` §Blockers/Concerns — carried-forward risk notes: ROCm 7.2/RDNA4 support is very recent and the `qwen-tts` package is new/fast-moving (pin exact versions); Podman GPU passthrough (`/dev/kfd`, `/dev/dri`, `--group-add keep-groups`, SELinux `container_use_devices`) must be verified from inside a real deployed container, not just a manual `podman run`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
None — repo currently contains only `CLAUDE.md`. This phase establishes the initial `backend/` (and empty `frontend/`) structure.

### Established Patterns
None yet — this is the first phase. `CLAUDE.md`'s tech stack section functions as the pattern-setting document until real code exists.

### Integration Points
None yet.

</code_context>

<deferred>
## Deferred Ideas

- LLM-based interpretation of chunks into narrative/dialogue blocks — already covered by Phase 2 (CAST-03), raised during chunking discussion but confirmed out of Phase 1 scope.
- Full deployment + verification on the actual target RX 9070 XT VM — can't happen until the VM exists post-release; tracked as an explicit follow-up gate rather than scoped into this phase's plan.

</deferred>

---

*Phase: 01-upload-to-audio-spike-tts-rocm-de-risk*
*Context gathered: 2026-07-09*
