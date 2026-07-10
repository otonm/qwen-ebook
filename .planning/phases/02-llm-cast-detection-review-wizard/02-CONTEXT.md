# Phase 2: LLM Cast Detection & Review Wizard - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Given an uploaded text (.txt from Phase 1, .epub new in this phase), the app analyzes it with the xAI Grok API to auto-detect the cast of characters (narrator + speaking characters, with inferred age/gender/personality) and splits the text into ordered narration/dialogue segments, each tagged with a suggested speaker and voice instructions. The user reviews and corrects the LLM-suggested cast in a dedicated wizard — rename, merge, edit descriptions, assign a voice (preset or free-text instructions) — with instant per-character voice preview, pre-generated as soon as a voice is assigned.

This phase introduces real persistence (SQLModel/SQLite) and the first frontend work (React/Vite per STACK.md). It does NOT include: the full editable segment table (TBL-01..04, Phase 3), bulk row actions, per-row on-demand regeneration, project save/reopen beyond what the wizard flow itself needs, or VoiceDesign (custom voice generation) — all deferred.

</domain>

<decisions>
## Implementation Decisions

### Persistence
- **D-01:** Introduce real SQLModel/SQLite persistence in this phase (not in-memory/throwaway state) — one `projects.db` with `Project`, `Character`, `Segment` tables per STACK.md's plan. Phase 3 (PERS-01/02) extends this schema rather than replacing a Phase-2-only stopgap.
- **D-02:** Schema covers only what Phase 2's wizard needs: `Project` (source text, filename, analysis status), `Character` (name, description, voice preset/instructions, preview audio path), `Segment` (order, character, text, voice instructions). No Phase 3 fields (generation status, content-hash cache key, audio cache path) added speculatively — Phase 3 adds those via migration when it has its own discussion.
- **D-03:** Cast/segment analysis runs as a background asyncio task, not a blocking request. Upload creates the `Project` row immediately (status: analyzing) and returns; a background task runs the Grok call(s) and pushes progress via SSE (`fastapi.sse.EventSourceResponse`, same mechanism STACK.md already planned for TTS progress).
- **D-04:** Add an `LLM_BACKEND=mock` env flag mirroring Phase 1's `TTS_BACKEND=mock` pattern — returns canned cast/segment JSON so dev/tests don't hit the real Grok API or incur cost. Gate the real `xai-sdk` import behind this flag, same as `qwen-tts`.

### Chunking & Cross-Chunk Cast Reconciliation
- **D-05:** Prefer single-shot analysis: estimate the text's token count and, if it fits within a safety margin, send the whole text to Grok in one call — no chunking, no cross-chunk reconciliation needed for the common case (most single novels fit grok-4.3's 1M-token window).
- **D-06:** Safety margin is ~50% of the context window reserved for input text; the remaining ~50% is headroom for the cast+segment JSON output (which scales with book length) plus the model's own reasoning space. Concretely: text estimated over ~500K tokens triggers the multi-chunk fallback path.
- **D-07:** Multi-chunk fallback (oversized texts only) reuses Phase 1's paragraph-chunker as the base unit, grouped up to a per-call size under the same budget logic. Each subsequent chunk's Grok call is given: (a) the full running resolved cast list (name + description — cheap, cast lists are small), and (b) the last 20 segments already resolved ([character]/text pairs) for narrative continuity context.
- **D-08:** The LLM is prompted to auto-resolve confident character matches across chunks (e.g. "the old man" → existing "Marcus") rather than always emitting a new character entry. The wizard's merge tool (WIZ-02) remains the safety net for cases the LLM gets wrong — it is not the primary reconciliation mechanism, just the fallback.

### EPUB Parsing (ING-02)
- **D-09:** Use `ebooklib` + `beautifulsoup4` (lxml parser, `recover=True`) per STACK.md. Extract text per spine item in reading order.
- **D-10:** Apply a heuristic skip of obvious non-narrative spine items (cover, TOC, copyright/title page, index) using simple signals: very short extracted text, filename/id hints ("cover", "toc", "copyright", "titlepage"), and EPUB3 nav landmarks where present. This is a best-effort filter, not a guarantee — ambiguous items still pass through to the LLM.
- **D-11:** Strip footnote/endnote markers and their linked note text entirely during extraction (detect `epub:type="noteref"`/`"footnote"` and common id/href-to-endnote patterns) — footnotes are not meant to be narrated aloud.
- **D-12:** Preserve EPUB chapter boundaries (spine item breaks) as first-class structure — extract per-chapter, keep chapter breaks as natural analysis/chunk boundaries (relevant mainly for the oversized-text fallback path; the common single-shot path just gets a fuller, structured text).
- **D-13:** If a specific chapter fails to parse even with `recover=True`, reject the whole upload with a clear error (do not silently skip the broken chapter and proceed with a partial book) — user explicitly chose fail-fast over partial narration.

### Wizard Flow & Voice Preview UX
- **D-14:** Single-page cast list UI — all detected characters visible at once as cards/rows with inline rename/merge/edit/voice-assign, not a step-by-step next/back wizard. Matches the app's overall spreadsheet-like editing philosophy and makes cross-character duplicate-spotting easier.
- **D-15:** Include a read-only segment preview (speaker + text, no inline edit/dropdowns/bulk actions) alongside the cast wizard in this phase's UI — satisfies ROADMAP Phase 2 success criteria #3 (text shown split into segments) without building Phase 3's full editable table early.
- **D-16:** Pre-fill each character's free-text voice instructions from the LLM's own inferred description as an editable starting default (e.g. "an elderly, gruff-voiced man, speaks slowly"), plus a best-guess preset pick — the user reviews/tweaks rather than starting from a blank field. Matches the project's core value of minimal manual editing.
- **D-17:** VoiceDesign (custom voice generation from a free-text description, for characters with no good preset match) is explicitly deferred out of this phase. Phase 2 ships CustomVoice preset + free-text instruction-steering only, keeping the same TTS surface as Phase 1's proven client. Revisit as a follow-up only if instruction-steering proves insufficient in practice.

### Claude's Discretion
- Exact background-task/SSE wiring shape (task registry, endpoint naming, event payload schema) beyond "background task + SSE progress" being the chosen pattern.
- Precise token-estimation method for the single-shot-vs-chunk decision (e.g. `tiktoken`-style estimate vs. a simpler chars/4 heuristic) — must respect the ~50%-of-context input budget from D-06.
- Exact heuristic thresholds for EPUB non-narrative-section skipping (D-10) and footnote pattern detection (D-11) — pick sensible defaults, document the heuristic's known limits inline.
- Voice-preview generation trigger wiring (WIZ-05: "as soon as a character's voice is assigned") — exact eager-generation mechanism, reusing Phase 1's `tts_client.synthesize()`.
- Internal `Character`/`Segment` SQLModel field naming and exact API request/response shapes.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Tech stack (governs almost every Phase 2 implementation choice)
- `CLAUDE.md` (repo root) — Technology stack decisions, including `xai-sdk`/Grok, SQLModel, ebooklib/beautifulsoup4/lxml, React+Vite frontend, SSE progress push.
- `.planning/research/STACK.md` — Full stack research writeup: xai-sdk usage pattern (`AsyncClient`, Pydantic structured output via `.parse()`), SQLModel schema plan (`Project`/`Character`/`Segment`), ebooklib/BeautifulSoup EPUB parsing approach and malformed-XHTML handling, React 19 + Vite + TanStack Table + shadcn/ui + Tailwind v4 frontend stack, `fastapi.sse.EventSourceResponse` for progress push, `LLM_BACKEND=mock`-equivalent dev-degradation pattern discussion, VoiceDesign as the deferred fallback path, current Grok model names/pricing/context window (grok-4.3, 1M tokens).

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 2: LLM Cast Detection & Review Wizard" — phase goal, 5 success criteria, requirement mapping (ING-02, CAST-01, CAST-02, CAST-03, WIZ-01..05).
- `.planning/REQUIREMENTS.md` §Ingestion (ING-02), §Cast & Analysis (CAST-01..03), §Cast Review Wizard (WIZ-01..05) — exact requirement text for what's in scope.
- `.planning/PROJECT.md` — project vision, core value (minimal manual editing), constraints.
- `.planning/STATE.md` §Blockers/Concerns — carried-forward risk note: cross-chunk character reconciliation strategy is a synthesized best-practice (MEDIUM confidence), not a sourced novel-specific benchmark — validate chunk-size/context-window assumptions against Grok's actual limits and real book lengths during research/planning (this discussion's D-05/D-06/D-07 set the starting approach, not a proven-correct final answer).

### Prior phase context
- `.planning/phases/01-upload-to-audio-spike-tts-rocm-de-risk/01-CONTEXT.md` — Phase 1 decisions this phase builds directly on: paragraph-based chunker (`chunk_paragraphs`, target ~500-1000 chars) to be reused as the multi-chunk fallback's base unit; `TTS_BACKEND=mock` pattern being mirrored here as `LLM_BACKEND=mock`; repo structure (`backend/app/`, `backend/tests/`, `frontend/` currently empty).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `backend/app/chunking.py` (`chunk_paragraphs`) — paragraph-based chunker from Phase 1, reused as the base unit for the multi-chunk fallback path (D-07).
- `backend/app/tts_client.py` (`synthesize`, `tts_health`) — existing TTS client, reused for character voice-preview generation (WIZ-04/WIZ-05).
- `backend/app/config.py` (`Settings`/`load_settings`) — established typed-settings pattern (plain `os.environ.get` + dataclass, no pydantic-settings) to extend with new Grok/SQLite/`LLM_BACKEND` config values.
- `backend/app/main.py` — existing FastAPI app, upload-bounded-read helper (`_read_upload_bounded`), UUID-based server-generated filenames (path-traversal-safe pattern to reuse for new project-scoped files).

### Established Patterns
- Mock-backend-via-env-flag pattern (`TTS_BACKEND=mock`) — Phase 1 precedent this phase's `LLM_BACKEND=mock` (D-04) directly follows: gate the real SDK import behind the flag so GPU/network-less dev machines can run the full flow.
- Blocking I/O wrapped in `run_in_threadpool` — Phase 1's pattern for calling sync httpx/ffmpeg from async FastAPI handlers; the new background analysis task should follow the same non-blocking-event-loop discipline.
- Frozen dataclass `Settings` singleton, loaded once at import — extend rather than replace for new env vars.

### Integration Points
- `backend/app/main.py`'s `/projects` endpoint is the natural precedent for a new project-creation endpoint, but Phase 2 changes its shape significantly (returns immediately with a project id + analyzing status, rather than blocking until final audio) — this is a new endpoint/flow, not a drop-in extension of the existing one.
- `frontend/` is currently empty (only `.gitkeep`) — this phase does the first real frontend scaffolding (`npm create vite@latest frontend -- --template react-ts` per STACK.md's Installation section).

</code_context>

<specifics>
## Specific Ideas

- User, verbatim, on chunking: "single shot, but with a large safety margin, giving large amounts of space to the llm for thinking and computing" — informs D-05/D-06.
- User, verbatim, on cross-chunk context: "cast list + last 20 pieces ([character] text, [narrator] text, ...) for context" — informs D-07's exact continuity-context shape (last 20 segments, not last N characters of raw text).
- User explicitly chose fail-fast (reject whole upload) over partial-narration-with-warning for EPUB parse failures — a deliberate quality-over-completeness call for a personal-use tool where the user controls their own source files.

</specifics>

<deferred>
## Deferred Ideas

- VoiceDesign (custom voice generation for characters with no good preset match) — explicitly deferred past Phase 2 (D-17); revisit only if CustomVoice + instruction-steering proves insufficient.
- Phase 3's full editable segment table (TBL-01..04: inline edit, bulk reassign, per-row on-demand generate/preview) — out of this phase's boundary; Phase 2 only ships a read-only segment preview (D-15).
- Phase 3's generation-status/content-hash caching fields (GEN-02, GEN-05) — not added to the schema speculatively (D-02); Phase 3 owns that design.

### Reviewed Todos (not folded)
None — no pending todos matched this phase's scope during `cross_reference_todos`.

</deferred>

---

*Phase: 2-llm-cast-detection-review-wizard*
*Context gathered: 2026-07-10*
