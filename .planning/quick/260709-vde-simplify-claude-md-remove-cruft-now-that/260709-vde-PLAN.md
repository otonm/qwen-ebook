---
phase: quick
plan: 260709-vde
type: execute
wave: 1
depends_on: []
files_modified: [CLAUDE.md]
autonomous: true
requirements: [DOC-CLEANUP]
must_haves:
  truths:
    - "A developer can read CLAUDE.md's stack section in under a minute"
    - "Stack section is a concise current-stack reference, not a research writeup"
    - "Guardrails (What NOT to use) survive as a condensed list"
    - "Constraints and Core Value are preserved unchanged"
  artifacts:
    - path: "CLAUDE.md"
      provides: "Condensed project + current-stack reference"
      contains: "### Current stack"
  key_links: []
---

<objective>
Simplify `CLAUDE.md`. Phase 1 is built and the stack decisions are made and
reflected in the code, so the file no longer needs to read like a research
document with confidence ratings, alternatives tables, and citation lists.
Collapse the ~85-line Technology Stack block into a short current-stack
reference plus a condensed guardrail list.

Purpose: A CLAUDE.md a developer skims in under a minute, not a research doc.
Output: A rewritten `CLAUDE.md` (Project block untouched, Stack block condensed).
</objective>

<execution_context>
@/home/oton/.claude/plugins/cache/gsd-plugin/gsd/4.0.4/workflows/execute-plan.md
@/home/oton/.claude/plugins/cache/gsd-plugin/gsd/4.0.4/templates/summary.md
</execution_context>

<context>
@CLAUDE.md

# Scope note — read before editing
# The physical CLAUDE.md on disk is ONLY 102 lines: two GSD-managed blocks —
#   - `<!-- GSD:project-start ... -->` ... `<!-- GSD:project-end -->` (lines 1-17): Project, Core Value, Constraints
#   - `<!-- GSD:stack-start source:research/STACK.md -->` ... `<!-- GSD:stack-end -->` (lines 19-102): the verbose Technology Stack
# The sections named in the task description that are NOT in the physical file
# (Conventions, Architecture, Project Skills, GSD Workflow Enforcement, Developer
# Profile) are injected by GSD/harness tooling at runtime, not stored in this
# file. "Keep them as-is" is satisfied by not touching the file's tail — there is
# nothing to delete for them here. Do NOT add or recreate those sections.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Condense the Technology Stack block in CLAUDE.md</name>
  <files>CLAUDE.md</files>
  <action>
Leave the Project block (lines 1-17, `GSD:project-start` .. `GSD:project-end`)
exactly as-is — Project, Core Value, and Constraints stay verbatim.

Replace everything BETWEEN the stack markers (currently lines 20-101, i.e. all
content after `<!-- GSD:stack-start source:research/STACK.md -->` and before
`<!-- GSD:stack-end -->`) with the condensed reference below. KEEP both marker
comment lines intact so the block stays GSD-recognizable.

Drop entirely: the "Recommended Stack / Core Technologies" prose table with
confidence ratings, "Supporting Libraries", "Development Tools" prose,
"Alternatives Considered", "Version Compatibility", and "## Sources". Fold the
survivors into one current-stack table + a condensed "What NOT to use" list.

New content between the markers:

## Technology Stack

Stack is decided and reflected in the code. This is a quick reference — the full
research writeup (rationale, alternatives, sources, confidence) lives in
`.planning/` (`research/STACK.md`).

### Current stack

| Area | Choice | Notes |
|------|--------|-------|
| TTS model | Qwen3-TTS-12Hz-1.7B-CustomVoice (HF, Apache 2.0) | Preset + free-text `instruct` steering, no voice cloning. VoiceDesign variant is the fallback for description-only voices. |
| TTS runtime | `qwen-tts` pip pkg on `transformers`, `attn_implementation="sdpa"` | Pin exact versions — new, fast-moving package. |
| GPU runtime | PyTorch ROCm 7.2 build (`gfx1201` / RX 9070 XT) | Match container ROCm family to host driver. |
| Language | Python 3.12 | |
| Backend | FastAPI (>=0.135 for native SSE) | One process owns upload, Grok calls, EPUB parse, TTS queue, ffmpeg join, SQLite. |
| Persistence | SQLModel + one SQLite `projects.db` | `Project`/`Character`/`Segment` tables; audio referenced by path, not blobbed. |
| LLM | `xai-sdk` (AsyncClient), Grok `grok-4.3`, Pydantic structured output | One shared Pydantic schema across LLM output, DB, and API. |
| EPUB parse | `ebooklib` + `beautifulsoup4` + `lxml` (`recover=True`) | Filter by reading order; expect malformed XHTML. |
| Audio join | system `ffmpeg` via `subprocess`, concat demuxer | Not the concat filter, not pydub. |
| Progress push | `fastapi.sse.EventSourceResponse` | One-way server->client; not WebSockets. |
| Container | Podman + Quadlets (systemd units) | GPU passthrough: `/dev/kfd`, `/dev/dri`, `--group-add keep-groups`. |
| Tooling | `uv` (deps/venv), `ruff` (lint/format) | |
| Dev without GPU | `TTS_BACKEND=mock` returns a placeholder WAV | Gate the real `qwen-tts` import behind the flag. |

### What NOT to use

- **Qwen3-TTS Base (voice cloning)** as the default voice path — speaker-encoder path is unreliable on ROCm. Use CustomVoice.
- **vLLM / vLLM-Omni** — RDNA4 kernels still experimental; no throughput need for a single-user tool. Use plain Transformers + `sdpa`.
- **`flash-attn`** — CUDA-only. Use `attn_implementation="sdpa"`.
- **Docker / docker-compose** — project requires Podman. Use Podman + Quadlets.
- **Kubernetes** — out of scope. Use Podman + Quadlets.
- **Celery / Redis / any task queue** — one GPU, one user. Use an in-process asyncio worker + a `status` column in SQLite.
- **Multi-tenant auth** — Tailscale is the access boundary; no auth layer.
- **pydub** for the production join path — unmaintained; call ffmpeg directly.

Note: the stack markers are kept, so a future GSD project-sync could re-expand
this block from `research/STACK.md` and clobber the condensation. That is
acceptable for now; if it recurs, raise removing the `source:` marker with the
user rather than deciding it here.
  </action>
  <verify>
    <automated>cd /var/home/oton/Documents/Projects/qwen-ebook && grep -q "### Current stack" CLAUDE.md && ! grep -q "Alternatives Considered" CLAUDE.md && ! grep -q "^## Sources" CLAUDE.md && ! grep -qi "confidence)" CLAUDE.md && grep -q "GSD:stack-end" CLAUDE.md && grep -q "GSD:project-start" CLAUDE.md && [ "$(wc -l < CLAUDE.md)" -lt 60 ]</automated>
  </verify>
  <done>CLAUDE.md's stack block is a short current-stack table + condensed "What NOT to use" list; Alternatives Considered, Sources, and confidence ratings are gone; both GSD marker pairs and the untouched Project block remain; file is well under 60 lines.</done>
</task>

</tasks>

<verification>
- `CLAUDE.md` Project block (lines through `GSD:project-end`) is byte-identical to before.
- Stack block condensed: no "Alternatives Considered", no "## Sources", no "confidence)" ratings, no per-library prose paragraphs.
- Both GSD marker pairs still present.
- A skim read of the whole file takes under a minute.
</verification>

<success_criteria>
- `CLAUDE.md` is under 60 lines.
- Contains `### Current stack` and a condensed `### What NOT to use`.
- Constraints and Core Value unchanged.
- No research-writeup cruft (alternatives, sources, confidence ratings).
</success_criteria>

<output>
Create `.planning/quick/260709-vde-simplify-claude-md-remove-cruft-now-that/260709-vde-SUMMARY.md` when done
</output>
