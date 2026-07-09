# Phase 1: Upload-to-Audio Spike (TTS/ROCm De-risk) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 1-upload-to-audio-spike-tts-rocm-de-risk
**Areas discussed:** Chunking heuristic for plain .txt, Spike voice selection, UI surface for the spike, GPU deployment verification path, Project tooling & structure

---

## Chunking heuristic for plain .txt

| Option | Description | Selected |
|--------|-------------|----------|
| Blank-line paragraphs, merged to a target length | Split on blank lines, greedily merge to a target chunk size | (superseded by follow-up) |
| One paragraph per chunk, any length | Every paragraph is its own chunk regardless of size | |
| Fixed character budget, snapped to nearest paragraph break | Walk ~N chars, snap to nearest boundary | |

**User's choice:** "use a library that parses the text and helps split the text at boundaries. the llm call then interprets the text into chunks of narrative and speech anyway and those blocks should not be too long."

**Notes:** This introduced scope overlap with Phase 2's CAST-03 (LLM narration/dialogue segmentation). Claude flagged this and redirected — Phase 1 requirements (ING-01, ING-03, GEN-01, GEN-04, DEPL-01) don't include LLM cast/segment analysis. Confirmed as a deferred idea; Phase 1 chunking stays non-LLM.

### Follow-up: chunking library approach

| Option | Description | Selected |
|--------|-------------|----------|
| Python stdlib/regex paragraph split | No new dependency, matches ING-03 language directly | ✓ |
| NLTK/spaCy sentence tokenizer + merge | More robust to odd punctuation, adds NLP dependency | |
| You decide | Claude picks during planning/research | |

**User's choice:** "then use the stdlib for now but plan the expansion for later"

### Follow-up: chunk size / merge behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Merge greedily up to a target length (~500-1000 chars) | Accumulate paragraphs until target reached | ✓ |
| Merge up to target, but never split a paragraph | Same, but oversized single paragraphs stay whole | |
| You decide | Claude picks a sensible default length | |

**User's choice:** "Merge greedily up to a target length (~500-1000 chars)"

---

## Spike voice selection

| Option | Description | Selected |
|--------|-------------|----------|
| Single default CustomVoice preset, no instruct steering | One built-in speaker preset, plain, for every chunk | ✓ |
| Default preset + a fixed instruct string | Same preset + a fixed steering instruction | |
| You decide | Claude picks a specific preset during planning/research | |

**User's choice:** "Single default CustomVoice preset, no instruct steering"
**Notes:** Exact preset name deferred to research/planning (`get_supported_speakers()`).

---

## UI surface for the spike

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal web page: upload button + download link | Simple upload+download page | |
| API/CLI only, no web page yet | curl/CLI-driven flow, fastest to build | ✓ |
| You decide | Claude picks based on what's fastest/reliable | |

**User's choice:** "API/CLI only, no web page yet"

### Follow-up: API/CLI shape

| Option | Description | Selected |
|--------|-------------|----------|
| FastAPI endpoint (curl/Postman-driven) | Real FastAPI upload endpoint, becomes actual app skeleton | ✓ |
| Standalone Python script (no server) | `python spike.py input.txt output.mp3`, throwaway | |

**User's choice:** "FastAPI endpoint (curl/Postman-driven)"

---

## GPU deployment verification path

| Option | Description | Selected |
|--------|-------------|----------|
| Already provisioned and reachable now | Target VM exists and is ready | |
| Needs to be stood up as part of Phase 1 | Target VM/host setup is part of this phase's scope | |
| Partially ready — let me clarify | Something in between | ✓ (led to clarification) |

**User's choice:** "the target will be ready after a release is done. for now keep to the local system."

### Follow-up: how to handle the success criterion given target VM isn't ready

| Option | Description | Selected |
|--------|-------------|----------|
| Build with TTS_BACKEND=mock now; real GPU verification later | Mock end-to-end now, defer real-hardware proof | |
| Develop against local AMD/ROCm hardware if available now | Use local AMD GPU as a stand-in for the real proof | ✓ |
| Something else — let me clarify | | |

**User's choice:** "Develop against local AMD/ROCm hardware if available now (not the final VM)"

### Follow-up: what local GPU is available

Claude ran `lspci`/`glxinfo` directly on the local system per user's request ("analyze the current system directly") rather than asking another question. Found: AMD Radeon 780M integrated GPU ("Phoenix/HawkPoint" APU, RDNA3, `gfx1103`), no ROCm/`rocminfo`/`rocm-smi` installed at time of discussion.

### Follow-up: is the 780M a viable ROCm target given it's not on CLAUDE.md's cited support list

| Option | Description | Selected |
|--------|-------------|----------|
| Try ROCm + HSA_OVERRIDE_GFX_VERSION, accept it may fail | Best-effort attempt with documented spoofing fallback | |
| Build fully on mock; treat all real-GPU proof as deferred | Don't fight an unsupported iGPU | |

**User's choice (overrode both options):** "the radeon 780m is supported by rocm" — user corrected Claude's caution; accepted as authoritative (user's direct knowledge of their own system).

### Follow-up: verification target given 780M is usable

| Option | Description | Selected |
|--------|-------------|----------|
| Real audio via ROCm + Podman GPU passthrough, on local hardware | Full success criterion #3 satisfied locally; re-verify (not rebuild) on target VM later | ✓ |
| Real audio via ROCm directly (no Podman yet); containerize later | Prove TTS/ROCm first, containerize separately | |

**User's choice:** "Real audio via ROCm + Podman GPU passthrough, on local hardware"

---

## Project tooling & structure

| Option | Description | Selected |
|--------|-------------|----------|
| Single-root Python project (backend at repo root) | Simplest for backend-only spike | |
| Pre-split monorepo (backend/ + frontend/ from day one) | Avoids restructuring commit later | ✓ |
| You decide | Claude picks based on what grows cleanest | |

**User's choice:** "Pre-split monorepo (backend/ + frontend/ from day one)"

### Follow-up: Python tooling confirmation

| Option | Description | Selected |
|--------|-------------|----------|
| uv for deps/venv, ruff for lint/format (per CLAUDE.md) | Matches documented stack exactly | ✓ |
| Something different — let me specify | | |

**User's choice:** "uv for deps/venv, ruff for lint/format (as CLAUDE.md recommends)"

---

## Claude's Discretion

- Exact target chunk length within the ~500–1000 char range
- Exact CustomVoice preset name for the spike voice
- Whether an oversized single paragraph gets further split or kept whole
- Internal `backend/` folder structure beyond the top-level `backend/`/`frontend/` split

## Deferred Ideas

- LLM-based narrative/dialogue interpretation of chunks — already Phase 2 (CAST-03), raised during chunking discussion, confirmed out of Phase 1 scope
- Full deployment + verification on the actual target RX 9070 XT VM — deferred until the VM exists post-release; tracked as an explicit follow-up gate
