---
phase: 02-llm-cast-detection-review-wizard
plan: 03
subsystem: api
tags: [xai-sdk, grok, structured-output, asyncio, sqlite, prompt-engineering]

requires:
  - phase: 02-llm-cast-detection-review-wizard/02-01
    provides: analysis_client.analyze() mock backend, analysis_worker.run_analysis() single-shot pipeline, SSE progress registry, CastAnalysisResult/CharacterSuggestion/SegmentSuggestion schemas
provides:
  - Real xai-sdk AsyncClient wiring for analysis_client.analyze() (CAST-01/CAST-03), with system/user role separation as the prompt-injection mitigation
  - CAST_ANALYSIS_SYSTEM_PROMPT covering narrator+cast trait inference, ordered voice-tagged segments, and LLM-side cross-chunk reconciliation instructions
  - analysis_worker multi-chunk fallback (_should_chunk, _group_chunks, _run_chunked_analysis) for oversized texts, with running-cast + last-20-segment continuity and name-equality reconciliation (CAST-02)
  - Globally-ordered segments across chunks + per-chunk SSE progress events
affects: [phase-02-wizard-frontend, phase-03-segment-table]

tech-stack:
  added: []
  patterns:
    - "Lazy xai_sdk import inside a private _real_analyze() helper, only reached from the non-mock branch — mirrors tts_client.py's GPU/CPU isolation discipline for the LLM_BACKEND=mock/real switch."
    - "Reconciliation-by-exact-name-match (not fuzzy matching) is the deliberate ceiling for cross-chunk character dedup; the wizard's merge tool is the documented human safety net (ponytail-marked in code)."

key-files:
  created:
    - backend/tests/test_analysis_reconciliation.py
  modified:
    - backend/app/analysis_client.py
    - backend/app/analysis_worker.py

key-decisions:
  - "Continuity context (running_cast/recent_segments) is rendered into the SAME user() message as the book text, never the system message — keeps the prompt-injection mitigation (system/user role separation) intact while still giving Grok the D-07 continuity data."
  - "_group_chunks() operates only on chunk_paragraphs() output (already paragraph/chapter-boundary-atomic) and only ever concatenates whole atoms with a '\\n\\n' separator — never slices one — so a per-call group boundary can never fall mid-chapter (D-12) without needing any extra chapter-marker plumbing through epub_parser.py."
  - "Per-call group budget derived as ANALYSIS_TOKEN_LIMIT * 4 chars, reusing the same D-06 budget logic that gates single-shot-vs-chunk in the first place."

patterns-established:
  - "Settings-singleton test-patching: monkeypatch.setattr(module, 'settings', dataclasses.replace(settings, FIELD=...)) to swap the frozen Settings singleton per-module for a test, since individual fields can't be set directly."
  - "Faking xai_sdk via sys.modules injection (types.ModuleType) rather than real network calls or an httpx-mocking library — no new test dependency needed for a lazily-imported SDK."

requirements-completed: [CAST-01, CAST-02, CAST-03]

coverage:
  - id: D1
    description: "Real (non-mock) analyze() calls xai-sdk AsyncClient.chat.create()+parse(CastAnalysisResult), with the system prompt and book text kept in strictly separate message roles (prompt-injection mitigation, T-02-07)."
    requirement: "CAST-01"
    verification:
      - kind: unit
        ref: "backend/tests/test_analysis_reconciliation.py#test_real_backend_keeps_system_prompt_and_book_text_in_separate_roles"
        status: pass
      - kind: unit
        ref: "backend/tests/test_analysis_reconciliation.py#test_real_backend_passes_continuity_context_in_user_message_not_system"
        status: pass
    human_judgment: false
  - id: D2
    description: "CAST_ANALYSIS_SYSTEM_PROMPT instructs narrator+cast trait inference and ordered voice-tagged segment splitting (CAST-03)."
    requirement: "CAST-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_analysis_reconciliation.py#test_system_prompt_covers_required_elements"
        status: pass
    human_judgment: false
  - id: D3
    description: "Oversized texts (estimate_tokens(text) > ANALYSIS_TOKEN_LIMIT) analyze via a sequential multi-chunk fallback, with running cast + last-20-segment continuity fed to each subsequent call, exact-name reconciliation avoiding duplicate characters, globally monotonic segment order, and per-chunk SSE progress (CAST-02)."
    requirement: "CAST-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_analysis_reconciliation.py#test_should_chunk_boundary_is_strictly_greater_than_limit"
        status: pass
      - kind: unit
        ref: "backend/tests/test_analysis_reconciliation.py#test_group_chunks_never_merges_across_a_chapter_blank_line_boundary"
        status: pass
      - kind: unit
        ref: "backend/tests/test_analysis_reconciliation.py#test_run_analysis_multi_chunk_reconciles_duplicate_and_orders_segments_globally"
        status: pass
      - kind: unit
        ref: "backend/tests/test_analysis_reconciliation.py#test_run_analysis_multi_chunk_emits_per_chunk_sse_progress"
        status: pass
    human_judgment: false
  - id: D4
    description: "REQUIRED post-execution manual UAT: with a real XAI_API_KEY and LLM_BACKEND=grok, POST a short public-domain chapter and eyeball the returned cast/segments for sane traits + correct speaker tags (prompt-wording quality, Open Question 1)."
    verification: []
    human_judgment: true
    rationale: "Requires a live, paid XAI_API_KEY and a real Grok network call — cannot run in this mock-backend-only execution session, and the plan explicitly scopes this as subjective human judgment on prompt wording quality, not something a pytest assertion can encode. This gates the PHASE, not this plan's own automated verification (see 02-03-PLAN.md 'Prompt-quality validation')."

duration: N/A (session interrupted by a provider quota reset mid-Task-1; resumed and completed in a follow-up turn)
completed: 2026-07-10
status: complete
---

# Phase 02 Plan 03: Real Grok Analysis + Multi-Chunk Reconciliation Summary

**Real xai-sdk `chat.parse(CastAnalysisResult)` wiring with role-separated system/user messages, plus a multi-chunk fallback that re-supplies the running cast + last-20 segments to each subsequent Grok call so oversized books reconcile repeat characters by name instead of duplicating them.**

## Performance

- **Duration:** Not reliably trackable — this execution was interrupted mid-Task-1 by a provider session-limit error and resumed in a follow-up turn; all work in this SUMMARY reflects the final, fully-verified state.
- **Completed:** 2026-07-10
- **Tasks:** 2/2
- **Files modified:** 2 (+1 new test file)

## Accomplishments
- `analysis_client.analyze()`'s non-mock branch now does real xai-sdk work: `AsyncClient(api_key=...)`, `chat.create(model=..., messages=[system(CAST_ANALYSIS_SYSTEM_PROMPT)])`, `chat.append(user(...))`, `await chat.parse(CastAnalysisResult)` — no manual `model_validate_json` re-check.
- `CAST_ANALYSIS_SYSTEM_PROMPT` instructs narrator+cast detection with inferred age/gender/personality traits, ordered voice-tagged narration/dialogue segments, and cross-chunk name-reuse reconciliation when continuity context is supplied.
- `analysis_worker.py` gained `_should_chunk`, `_group_chunks`, and a `_run_chunked_analysis` path: oversized texts get chunked via `chunk_paragraphs()`, grouped up to a per-call char budget, analyzed sequentially with growing running-cast/recent-segments continuity, and persisted with globally monotonic segment ordering.
- Cross-chunk character reconciliation is exact-name-match only (deliberately, per D-08 — the LLM is prompted to reuse names, the wizard's merge tool is the human safety net for anything it misses).
- SSE now emits a `{"stage": "chunk", "n", "total"}` progress event per chunk group during the fallback path.

## Task Commits

Each task was committed atomically:

1. **Task 1: Real xai-sdk analyze() + cast/segment system prompt** - `ede4957` (feat)
2. **Task 2: Multi-chunk fallback with running-cast + last-20-segment reconciliation** - `7ae444c` (feat)

**Plan metadata:** `[this commit]` (docs: SUMMARY.md)

_Note: Both tasks were developed with implementation + tests verified together in one working session (not a strict separate RED-then-GREEN commit pair) — see "TDD Gate Compliance" below._

## Files Created/Modified
- `backend/app/analysis_client.py` - `CAST_ANALYSIS_SYSTEM_PROMPT`, `_build_continuity_block`, `_real_analyze`, updated `analyze()` dispatch
- `backend/app/analysis_worker.py` - `_should_chunk`, `_group_chunks`, `_persist_result`, `_run_chunked_analysis`, updated `run_analysis()` dispatch
- `backend/tests/test_analysis_reconciliation.py` - Task 1 (system prompt content, role separation, fake-xai_sdk parse() usage) + Task 2 (chunk boundary, chapter-safe grouping, multi-chunk reconciliation e2e, SSE progress) tests

## Decisions Made
- Continuity context is rendered as plain text and prepended to the book text inside the single `user()` message (never the system message) — keeps the T-02-07 prompt-injection mitigation intact.
- `_group_chunks()` treats `chunk_paragraphs()` output as atomic and only ever concatenates whole elements — this satisfies "never merge across a chapter blank-line boundary" (D-12) without any new chapter-marker plumbing, because `epub_parser.py` already collapses all intra-chapter whitespace to single spaces, so the only `"\n\n"` boundaries chunk_paragraphs() ever sees in EPUB-derived text are real chapter breaks.
- Per-call group budget = `ANALYSIS_TOKEN_LIMIT * 4` chars, reusing the same D-06 budget logic that gates the single-shot-vs-chunk decision.
- Reconciliation is exact-name-match only (`# ponytail:` comment in `_persist_result`) — no fuzzy-matching machinery, per the plan's explicit prohibition and D-08's "LLM does the reconciling, wizard merge tool is the safety net" design.

## Deviations from Plan

None — plan executed as written. One process note: this execution was interrupted mid-Task-1 by a provider session-limit error before any commit existed; on resume, the uncommitted working-tree state (already-implemented and test-verified) was inspected via `git diff`/`git status`, confirmed correct, and then split into the two atomic per-task commits described above rather than being redone from scratch.

## TDD Gate Compliance

Both tasks in this plan carry `tdd="true"` at the task level (plan-level frontmatter is `type: execute`, not `type: tdd`, so the strict plan-level RED-then-GREEN gate enforcement doesn't apply here). Due to the session interruption, implementation and tests for each task were already written and mutually verified together before the first commit landed, rather than committed as a separate failing-test commit followed by a passing-implementation commit. Each task's single commit (`ede4957`, `7ae444c`) bundles its test additions and implementation together, verified together via `LLM_BACKEND=mock uv run pytest tests/test_analysis_reconciliation.py` and `uv run ruff check .` before commit. No functional gap: acceptance criteria for both tasks are met and independently testable.

## Issues Encountered
- **Provider session-limit interruption mid-Task-1:** the agent was terminated before any commit existed. On resume, `git status`/`git diff` confirmed the uncommitted `analysis_client.py`/`analysis_worker.py`/test-file changes were intact and correct; work continued from that state rather than restarting.
- **Test self-collision:** an early version of `test_real_backend_passes_continuity_context_in_user_message_not_system` used `"Marcus"` as its example character name, which collided with the system prompt's own worked example ("the old man" matching an existing "Marcus") — the assertion that the system message excludes the continuity-context name was failing on the prompt's own wording, not a real bug. Fixed by renaming the test's example character to `"Captain Reyes"`.
- **Test aliasing bug:** the multi-chunk reconciliation test initially asserted against a live reference to `analysis_worker`'s internal `running_cast`/`recent_segments` lists, which get mutated in place after each `analyze()` call returns — the assertion saw the *final* post-loop state instead of the state at call time. Fixed by snapshotting (`list(...)`) inside the fake `analyze()` at call time.

## User Setup Required

None for the automated portion of this plan (`LLM_BACKEND=mock` requires no external service).

**Required before treating cast-detection as validated (phase-level UAT, not this plan's automated gate):** a real `XAI_API_KEY` (from console.x.ai) and `LLM_BACKEND=grok`/non-mock, to run the manual smoke test described in 02-03-PLAN.md's "Prompt-quality validation" section — POST a short public-domain chapter and eyeball the cast/segment quality, iterating `CAST_ANALYSIS_SYSTEM_PROMPT` wording if needed. This was **not performed** in this session (no live API key available to the executor) and is tracked as coverage item D4 (`human_judgment: true`) above.

## Next Phase Readiness
- The analysis pipeline (mock and real) is now feature-complete for CAST-01/02/03: single-shot and multi-chunk paths both persist reconciled characters and globally-ordered segments, with SSE progress for both.
- Blocker/concern carried forward: the D4 manual UAT (real-key prompt-quality smoke test) is still outstanding — should be run with a real `XAI_API_KEY` before the cast-detection differentiator is considered validated, per the phase's own gating requirement.
- No other blockers for the remaining Phase 02 plans (wizard frontend work).

---
*Phase: 02-llm-cast-detection-review-wizard*
*Completed: 2026-07-10*

## Self-Check: PASSED

All created/modified files and both task commits (`ede4957`, `7ae444c`) verified present on disk / in git history.
