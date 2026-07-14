---
status: resolved
trigger: |
  when a text file is loaded and analyzed, a lot of information is lost
  (sometimes the whole narration). rework this process. the llm call should
  produce a "script" from the original text that includes hints about the
  speaker (narrator, character), how the line should be spoken (narration,
  excited, sad, angry, getting angrier during speaking, ...) and the text to
  be spoken. the text formatting can be removed or adapted, however no
  content should get lost. tweak the llm call, reduce the temperature,
  require fixed output structure.
created: 2026-07-14
updated: 2026-07-14
---

# Debug Session: llm-analysis-content-loss

## Symptoms

- **Expected behavior**: Every unit of source text (all narration and all
  dialogue) survives cast/segment analysis. Formatting can be normalized or
  dropped, but no sentence/paragraph of content should be omitted from the
  resulting `segments` list.
- **Actual behavior**: A meaningful fraction of the source text goes
  missing from the persisted segments after LLM analysis — user reports
  sometimes entire narration blocks are absent.
- **Error messages**: None — silent. No exception, no `status=error` on the
  project, no warning in backend logs correlating with the loss (ruled out:
  the only existing loss-related log line is
  `dropping segment for unknown character_name` in
  `app/analysis_worker.py::_persist_result`, which is a different,
  already-logged failure mode — not silent).
- **Timeline**: Unknown / not established whether this is inherent to the
  original prompt design or a regression. Treat as long-standing until
  evidence says otherwise.
- **Reproduction**: Not isolated to single-shot vs. chunked analysis path —
  user has seen it (or suspects it) on both. Both paths call the same
  `app/analysis_client.py::analyze()` / `_real_analyze()` /
  `CAST_ANALYSIS_SYSTEM_PROMPT`.

## Relevant code (gathered by orchestrator before delegation)

- `backend/app/analysis_client.py` — builds `CAST_ANALYSIS_SYSTEM_PROMPT`,
  calls OpenRouter chat-completions with `response_format: json_schema`
  (strict) against `CastAnalysisResult.model_json_schema()`. No
  `temperature` key is set in the request payload (provider default
  applies). No explicit instruction in the prompt requiring 100% text
  coverage / forbidding paraphrase-or-drop.
- `backend/app/schemas.py` — `CastAnalysisResult` / `SegmentSuggestion` /
  `CharacterSuggestion` Pydantic models; this is also the literal JSON
  schema sent to the LLM as `response_format`.
- `backend/app/analysis_worker.py` — orchestrates single-shot vs. chunked
  (`_should_chunk` on `ANALYSIS_TOKEN_LIMIT`) analysis;
  `_run_chunked_analysis` groups `chunk_paragraphs()` output via
  `_group_chunks` up to a char budget and calls `analyze()` per group with
  running-cast/recent-segments continuity context; `_persist_result` writes
  characters + segments, skipping (and logging) any segment whose
  `character_name` doesn't match a known cast member.

## User's proposed direction (not yet a confirmed root cause — investigate first)

1. Rework the LLM call to produce a "script": explicit speaker (narrator /
   character), a delivery/emotion hint (narration, excited, sad, angry,
   escalating mid-line, etc.), and the verbatim text to be spoken.
2. Formatting may be normalized/removed, but no content may be dropped.
3. Reduce `temperature` on the OpenRouter call.
4. Require a fixed output structure (already using strict JSON schema —
   confirm whether "fixed structure" means something beyond that, e.g.
   forcing the model to echo/account for full text coverage).

## Current Focus

```yaml
reasoning_checkpoint:
  hypothesis: >
    CAST_ANALYSIS_SYSTEM_PROMPT tells the model to derive a dialogue
    segment's voice_instructions from the surrounding narration (dialogue
    tag / action beat, e.g. "she said, her voice calm but firm" ->
    voice_instructions="calm but firm"), but never instructs it to ALSO
    keep that same narration sentence as its own Narrator segment. The
    model treats "extract the delivery cue" as license to consume and
    discard the underlying narration text, so dialogue-adjacent narration
    (attribution tags, action beats) is silently dropped from `segments`
    while narration blocks *between* dialogue exchanges survive intact.
    Secondary contributing factors: no explicit "100% content coverage"
    instruction anywhere in the prompt, and no temperature control (so
    sampling variance can additionally invite paraphrasing).
  confirming_evidence:
    - "Real (LLM_BACKEND=openrouter, real OPENROUTER_API_KEY, model
      x-ai/grok-4.3) single-shot analyze() call against a 1469-char,
      7-paragraph sample: segment_chars/source_chars ratio = 0.71 (29%
      content loss) despite EVERY quoted dialogue line surviving intact
      (0/6 dialogue markers missing)."
    - "Diffing segments against source line-by-line: 100% of the missing
      content is narration immediately adjacent to a quote — e.g. 'said
      Daniel, leaning against the doorway with his arms crossed.',
      'Daniel sighed and stepped further into the small room, the wind
      rattling the glass behind him.', 'Marion replied, and for the first
      time that evening, the corner of her mouth lifted into something
      like a smile.' — all absent from segments[].text, while their
      substance reappears as that dialogue segment's voice_instructions
      (e.g. 'casual and lightly exasperated', 'sighing, with mild
      irritation', 'quietly, with a small smile')."
    - "Narration blocks NOT adjacent to a quote (e.g. the opening
      lighthouse paragraph, the storm-clouds paragraph) survived at 100%
      — confirms the loss is specifically tied to the
      dialogue-tag-becomes-voice_instructions behavior, not a general
      summarization tendency or a chunking artifact."
    - "Reproduced on the SINGLE-SHOT path alone (text well under
      ANALYSIS_TOKEN_LIMIT=500_000 tokens / budget_chars=2_000_000, so
      _should_chunk() is false and _group_chunks is never invoked) — rules
      out chunk-grouping size as the dominant cause; both single-shot and
      chunked paths share analyze()/CAST_ANALYSIS_SYSTEM_PROMPT so the fix
      applies uniformly per the user's direction."
  falsification_test: >
    If the loss were instead caused by chunk-group size or by a max_tokens
    truncation of the JSON response, a small single-shot call (no chunking,
    small enough to never approach any output-token ceiling) would NOT show
    a ratio this low, and the missing spans would not correlate 1:1 with
    "narration text whose content reappears in an adjacent
    voice_instructions field." Both predictions were falsified: loss
    occurred well below chunking thresholds, and every dropped span maps
    directly onto a sibling segment's voice_instructions content.
  fix_rationale: >
    Root cause is a prompt-design gap, not a schema or parsing bug: the
    schema/response_format is already strict/complete, so the fix is
    entirely in CAST_ANALYSIS_SYSTEM_PROMPT (explicit 100%-coverage
    contract + explicit "dialogue tags/action beats still get their own
    Narrator segment even when they inform voice_instructions" rule) plus
    a low temperature (reduce sampling-variance-driven paraphrase risk, per
    user's explicit ask) and a cheap coverage-ratio warning in
    analysis_worker.py as a regression tripwire (this bug produced zero
    errors/warnings anywhere in the existing pipeline).
  blind_spots: >
    Only tested one short sample (1 real API call, one model
    x-ai/grok-4.3, default OpenRouter provider). Have not yet tested the
    chunked path with a real key, nor a much longer document, nor verified
    the fixed prompt closes the gap by re-running the same real-key repro
    after the change (planned next). Provider-side max_tokens truncation
    was not directly ruled out via API response inspection (only inferred
    absent from symptoms: truncated/invalid JSON would raise a parse
    exception and set project.status="error", which the user did not
    report) — not chased further per the "primary fix is prompt/temperature,
    not chunk re-tuning" guidance, since evidence already explains the loss
    mechanism without invoking truncation.
```

- next_action: NEW SYMPTOM from human verification (2026-07-15): user
  uploaded a longer real text. Per-paragraph content preservation now
  works ("properly interpreted" — the per-segment fix holds), BUT the
  segment table itself stops partway through the source text ("cut short"),
  specifically in the middle of the document, not at the very start. This
  is a DIFFERENT failure mode than the original ticket (segments present
  are apparently correct; the tail of the document is simply missing
  entirely, not paraphrased/absorbed). Reopen investigation focused on:
  (a) whether this longer text crosses `_should_chunk()`'s threshold and
  goes through `_run_chunked_analysis` — most likely yes, given the
  original repro sample (which stayed single-shot) did NOT show this
  symptom; (b) whether the chunked loop is silently truncated by an
  unhandled exception in `analyze()`/`_real_analyze()` on one of the later
  groups (e.g. a max_tokens/context-length response truncation producing
  invalid JSON that fails `CastAnalysisResult.model_validate_json()`) —
  this was flagged as an untested blind spot in the prior resolution
  ("Provider-side max_tokens truncation was not directly ruled out"); (c)
  whether such an exception is silently swallowed somewhere rather than
  properly setting `project.status="error"` with `error_detail`, since the
  user did not report seeing an error — check `run_analysis`'s try/except
  in analysis_worker.py (it should catch and set status=error+error_detail
  on ANY exception in `_run_chunked_analysis`, so first confirm via the
  actual project's DB row / backend logs whether status is in fact
  "error" with an informative error_detail that the frontend just isn't
  surfacing prominently, vs. a genuine silent early-return); (d) whether
  the new, longer/more prescriptive system prompt (added by the prior fix)
  increased per-call output size enough to push a normal-sized chunk group
  over a completion-token ceiling that previously had headroom — i.e. the
  content-loss fix itself may have a truncation regression as a side
  effect. Reproduce with a real longer document (multi-chunk) and a real
  key, inspect the actual OpenRouter HTTP response body/finish_reason for
  truncated groups, and check the target project's status/error_detail in
  the DB before forming a new hypothesis.

## Evidence

- timestamp: 2026-07-14T00:00:00Z
  checked: Real OpenRouter call via `app.analysis_client.analyze()`
  (LLM_BACKEND=openrouter, real key from backend/.env, model
  x-ai/grok-4.3) against a 253-word / 1469-char sample (narrator + 2
  characters, 6 dialogue lines each with a dialogue tag/action beat).
  found: segment_chars/source_chars = 1040/1469 = 0.71. All 6 quoted
  dialogue lines present verbatim. All 5 missing spans are narration
  immediately adjacent to a quote (dialogue tags / action beats), and each
  missing span's substance reappears as the adjacent dialogue segment's
  `voice_instructions` (e.g. "sighing, with mild irritation" absorbing
  "Daniel sighed and stepped further into the small room, the wind
  rattling the glass behind him."). Narration blocks not adjacent to a
  quote were preserved at 100%.
  implication: Confirms the hypothesis directly — this is a systematic,
  mechanistic prompt-design gap (dialogue-tag/action-beat text is being
  "consumed" into voice_instructions instead of ALSO being kept as its own
  Narrator segment), not random sampling noise or a chunking-size effect.
  Root cause CONFIRMED.

- timestamp: 2026-07-14T00:00:00Z
  checked: `_should_chunk()`/`_group_chunks()` math with default settings
  (ANALYSIS_TOKEN_LIMIT=500_000 -> budget_chars=2_000_000) against the
  repro sample (1469 chars) and against realistic single-book uploads.
  found: The repro sample (and the vast majority of realistic single-file
  uploads) never crosses `_should_chunk()`'s threshold, so `_run_chunked_
  analysis`/`_group_chunks` never executes for them — the single-shot path
  alone reproduces the full-size content loss.
  implication: Chunk-group sizing is not the dominant contributor; the
  fix must live in the shared CAST_ANALYSIS_SYSTEM_PROMPT/analyze() layer
  used by both paths, not in chunk-size tuning (matches user's stated
  direction). Noted per the task's "if it looks suspicious, note it" —
  not chased further, no re-tuning of CHUNK_TARGET_LEN/ANALYSIS_TOKEN_LIMIT
  planned.

- timestamp: 2026-07-14T00:00:00Z
  checked: `app/voices.py::merge_instructions` and every consumer of
  `SegmentSuggestion.voice_instructions` / `Segment.voice_instructions`
  (grepped app/main.py, app/analysis_worker.py, app/cache_key.py).
  found: `merge_instructions(base, delivery)` already strips/skips empty
  parts and works identically whether `delivery` (a narration segment's
  voice_instructions) is "" or non-empty — no caller anywhere assumes
  narration's voice_instructions is always exactly "". The only place that
  literal contract is stated is the prompt text and the Field description
  in schemas.py; both are prompt-facing, not code-enforced.
  implication: Safe to relax "narration voice_instructions MUST be empty
  string" to "empty by default, optionally a short tonal hint" without
  touching voices.py, cache_key.py, or main.py — no schema/field type
  change needed either, just wording. Confirms this can be a docs/prompt-
  only change per the ponytail smallest-diff constraint.

## Eliminated

- hypothesis: The content loss is dominated by (or requires) the chunked
  multi-call path (`_run_chunked_analysis`/`_group_chunks` handing the
  model an overly large multi-paragraph group).
  evidence: Real-key repro reproduced the loss on the single-shot path
  alone, with a sample far below any chunking threshold at default
  settings — chunking was never invoked.
  timestamp: 2026-07-14T00:00:00Z

## Resolution

- root_cause: `CAST_ANALYSIS_SYSTEM_PROMPT` (backend/app/analysis_client.py)
  instructs the model to derive a dialogue segment's `voice_instructions`
  from the surrounding narration (dialogue tags / action beats) but never
  instructs it to ALSO retain that same narration text as its own Narrator
  segment, and never states an explicit "100% of source text must survive
  into segments" contract. The model reasonably treats "extract the
  delivery cue" as consuming the underlying sentence, silently dropping it
  from the output. No temperature was set (provider default), and no
  coverage check existed anywhere in the pipeline to catch this class of
  loss, so it was completely silent (no exception, no warning, no
  project.status="error").
- fix: |
    1. backend/app/analysis_client.py — rewrote CAST_ANALYSIS_SYSTEM_PROMPT:
       explicit "every word must survive into segments" framing, a
       COMPLETENESS IS MANDATORY clause requiring 100% source-text coverage
       (formatting/whitespace may normalize, content may not), and a
       CRITICAL clause explicitly forbidding dialogue tags/action beats
       from being "consumed" into voice_instructions instead of also being
       kept as their own Narrator segment. Relaxed the
       narration-voice_instructions-MUST-be-empty rule to
       empty-by-default-but-optional-tonal-hint (narration can now carry
       delivery hints too, per the user's ask), matching the unified
       hint-category framing in the trigger. Added module-level
       `_ANALYSIS_TEMPERATURE = 0.2` and wired `"temperature"` into the
       `_real_analyze` OpenRouter payload (was previously unset/provider
       default).
    2. backend/app/schemas.py — updated `SegmentSuggestion.voice_instructions`
       Field description (part of the literal JSON schema sent to the LLM)
       to match: no longer says narration "MUST be empty string", now
       states delivery text must never substitute for including the
       underlying scene/action text in `text`.
    3. backend/app/analysis_worker.py — added
       `_check_content_coverage(project_id, source_text, result)`: a
       log-only warning (not a hard fail) when
       `sum(len(s.text)) / len(source_text) < 0.85`, called after every
       `analyze()` call on both the single-shot (`run_analysis`) and
       chunked (`_run_chunked_analysis`, per-group) paths — a regression
       tripwire so any future silent content loss leaves a log trace
       instead of nothing.
    No schema/type changes were needed (voice_instructions stays a plain
    `str` on both SegmentSuggestion and Segment) — verified via grep that
    no consumer (`app/voices.py::merge_instructions`, `app/main.py`,
    `app/cache_key.py`) assumes narration's voice_instructions is always
    exactly `""`, so relaxing that contract required no code changes
    outside the prompt/description text.
- verification: |
    Real-key (LLM_BACKEND=openrouter, real OPENROUTER_API_KEY, model
    x-ai/grok-4.3) re-run of the EXACT SAME repro used to confirm the root
    cause:
    - Single-shot path: coverage ratio 0.71 -> 0.98. All previously-missing
      dialogue tags/action beats ("said Daniel, leaning against the
      doorway...", "Daniel sighed and stepped further into the small
      room...", "Marion replied, and for the first time that evening...",
      "Daniel finally said, his earlier irritation gone...") now present
      verbatim as their own Narrator segments, in correct source order,
      alongside the dialogue segments that derive voice_instructions from
      them. All 6 quoted dialogue lines still present.
    - Chunked path (forced via ANALYSIS_TOKEN_LIMIT=1/CHUNK_TARGET_LEN=250
      against a real DB + real OpenRouter calls, multiple sequential
      analyze() calls with running_cast/recent_segments continuity):
      status=ready (no error), coverage ratio 0.98, 3 characters correctly
      reconciled with zero duplicates across chunk boundaries, 19 segments
      in correct global order. Confirms the fix applies uniformly to both
      paths as intended (they share analyze()/CAST_ANALYSIS_SYSTEM_PROMPT).
    - `cd backend && uv run ruff check .` — all checks passed (E501 line
      length fixed after initial prompt rewrite).
    - `uv run pytest tests/ -m "not integration"` — 100 passed, 2
      integration tests correctly deselected (no live pod). No test
      changes were needed — the mock backend's canned narrator
      voice_instructions="" behavior (test_analysis_pipeline.py's
      assertion that some segments have empty and some have non-empty
      voice_instructions) is untouched since _mock_analyze is independent
      of the prompt/real-backend changes.
    Residual note (not a content-loss regression, logged for completeness):
    one segment in the single-shot run grouped a short dialogue line and
    its trailing attribution into a single Narrator-tagged segment instead
    of splitting them ('"I've been told," Marion replied, and for the
    first time...' as one Narrator segment rather than a Marion dialogue
    segment + separate Narrator segment). This is a segmentation
    granularity/attribution nuance, not content loss (nothing was
    dropped, ratio 0.98) — the same run's chunked-path re-test split this
    exact line correctly, consistent with normal LLM sampling variance
    rather than a systematic prompt gap. Given the project's design (user
    reviews/edits the segment table before generation), left as-is —
    matches the "smallest correct fix for the reported symptom" scope; not
    chased further.
- files_changed:
    - backend/app/analysis_client.py
    - backend/app/schemas.py
    - backend/app/analysis_worker.py

## Round 2: "stops in the middle" on longer real documents (2026-07-15)

Human verification of round 1 surfaced a NEW symptom: on a longer real
upload, per-paragraph content was correctly preserved (round 1 holds), but
the segment table itself stopped partway through the middle of the source
text. Investigated by continuing this session (orchestrator worked inline
after a spawned session-manager agent hit the account's weekly API rate
limit mid-investigation and was restarted manually):

- root_cause: `ANALYSIS_TOKEN_LIMIT` (backend/app/config.py) defaulted to
  500,000 — sized off the model's ~1M-token *context* window, not its much
  smaller completion/output ceiling. Real-key testing found the actual
  completion-token ceiling is far smaller and unrelated to context size: a
  ~110K-char single call hit `finish_reason="length"` at ~68K completion
  tokens, and even well below that (~30K chars) the model sometimes
  self-truncated (`finish_reason="stop"` but only ~60% coverage) on this
  long, repetitive verbatim-transcription task. Because `_should_chunk()`
  almost never triggered at the old limit, most real documents were sent
  as one oversized single-shot call the model could not reliably complete
  — silently, since a truncated/incomplete-but-valid JSON response is not
  an exception.
- fix: |
    1. backend/app/config.py — dropped `ANALYSIS_TOKEN_LIMIT` default from
       500_000 to 6_000 tokens (a 24_000-char per-call budget via
       `_group_chunks`), comfortably under both observed failure points, so
       real documents now actually get chunked instead of sent as one call
       the model can't reliably complete.
    2. backend/app/analysis_worker.py — promoted the round-1 log-only
       coverage tripwire into an enforced gate: new `_analyze_with_retry()`
       retries a chunk's `analyze()` call up to 3 times when coverage falls
       below 85%, and raises (which `run_analysis`'s existing try/except
       turns into `project.status="error"` + an informative
       `error_detail`) if it never recovers — turning silent
       under-generation into either a real retry-driven fix or a loud,
       diagnosable failure, never a quietly truncated success. Wired into
       both the single-shot and per-chunk call sites.
- verification: |
    Real-key (LLM_BACKEND=openrouter, model x-ai/grok-4.3) test against a
    ~50K-char synthetic multi-paragraph document (well over the new
    24K-char chunk budget, forcing the chunked path): completed with
    `status=ready`, and the LAST segment's text exactly matched the
    source's true final sentence — confirming the document was processed
    to completion, not cut off. (This same run also surfaced Round 3's bug,
    below — coverage looked complete at the tail but total content was
    inflated ~3x.)
- files_changed:
    - backend/app/config.py
    - backend/app/analysis_worker.py

## Round 3: cross-chunk continuity-context duplication (2026-07-15)

Round 2's real-key verification (a ~50K-char, 2-3-chunk document) reached
the true end of the source (no cut-off — round 2 confirmed fixed), but
total segment text came out to ~3x the source's character count, with
individual lines repeated up to ~190 times.

- root_cause: `_build_continuity_block()` (analysis_client.py) prepends the
  running cast + last-20 resolved segments into the SAME user message as
  each subsequent chunk's new source text, separated only by a `"---"`
  marker and a plain-language label. Round 1's new "100% of the input must
  survive into segments" instruction didn't scope itself to only the new
  chunk text — nothing told the model the continuity block was reference-
  only and must not itself be re-emitted as segments. On later chunks, the
  model treated "reproduce everything in this message" as covering the
  continuity block too, re-emitting already-persisted segments as new
  ones — compounding across every subsequent chunk. (A related, distinct
  provider-side issue was found in the same test run: on at least one
  chunk, the OpenRouter response was malformed/un-parseable — 1120 Pydantic
  validation errors, each list element containing a stringified
  `{"completionState": ...}` wrapper instead of the expected object —
  consistent with the model degrading near the completion-token ceiling
  round 2 also diagnosed. `_analyze_with_retry()` only retried on
  low-coverage-but-valid results, not on `analyze()` itself raising, so
  this single bad sample failed the whole chunk instead of getting a
  retry.)
- fix: |
    1. backend/app/analysis_client.py — `CAST_ANALYSIS_SYSTEM_PROMPT`'s
       completeness rule now explicitly states it applies only to the text
       under a new `"=== TEXT TO CONVERT ==="` marker, and that content
       appearing only in the continuity block must never be re-emitted as
       a segment. `_build_continuity_block()` now labels itself
       reference-only ("Do NOT create segments for anything in this
       block...") and ends with the `"=== TEXT TO CONVERT ==="` marker
       instead of a bare `"---"`.
    2. backend/app/analysis_worker.py — `_analyze_with_retry()` now also
       catches `ValidationError`/`httpx.HTTPError` from `analyze()` itself
       and retries (same bounded 3-attempt budget), instead of failing the
       chunk on a single malformed-response sample. Only raises after
       attempts are exhausted, with the last error included in the message.
- verification: |
    Real-key test against a ~36K-char, less pathologically-repetitive
    synthetic document (still long enough to force 2 chunks at the new
    24K-char budget): `status=ready`, coverage ratio 1.0 (35,781/35,783
    chars — effectively exact), last segment exactly matches the source's
    true tail, completed in ~2.5 minutes (vs. ~7-12 min and either massive
    duplication or an outright validation-error failure pre-fix on
    comparable inputs). Remaining segment-text duplicates in the output
    were cross-checked against the source and found to mirror the source's
    OWN repeated paragraphs (a deliberate property of the synthetic test
    text), not model-introduced duplication.
    `cd backend && uv run ruff check .` — clean. `uv run pytest tests/ -m
    "not integration"` — 100 passed (one pre-existing test's `fake_analyze`
    fixture updated from `text[:20]` to `text` after the new coverage gate
    correctly started rejecting its truncated canned output;
    `_mock_analyze` similarly changed from a first-3-paragraphs cap to
    covering all paragraphs, for the same reason — mock mode must satisfy
    the same completeness contract the coverage gate now enforces).
    Both real-key test projects created during this round's verification
    (and the leftover ones from round 2) were deleted from the live app
    afterward — verification artifacts, not real user data.
    NOTE: the backend Podman image had to be rebuilt
    (`podman build -f backend/Containerfile.backend -t
    localhost/qwen-ebook-backend:dev .`) and the `qwen-ebook-backend`
    service restarted between each round — the running container was
    serving a stale pre-fix image for the first post-round-2 verification
    attempt, which gave a misleading result (a run against literally the
    old, unfixed code) before this was caught and corrected.
- files_changed:
    - backend/app/analysis_client.py
    - backend/app/analysis_worker.py

## Overall status

Round 1 (per-paragraph content loss), round 2 (mid-document truncation on
long inputs), and round 3 (cross-chunk continuity duplication +
malformed-response retry gap) are all fixed and verified with real-key
end-to-end tests. `ruff check` clean, full test suite green (100 passed).
Minor residual (not content loss, not chased further per project's
review/edit-table design): occasional narration-lead-in + dialogue-quote
segmentation granularity imprecision (e.g. `"X said finally. \"quote...\""`
landing in one Narrator-tagged segment instead of splitting) — consistent
with ordinary LLM sampling variance, first noted in round 1.

Human-confirmed on the deployed app (2026-07-15): "segment generation and
classification works now." Session resolved.

(A related, separately-scoped fix landed in the same working session but
outside this ticket's root cause: `logging.basicConfig()` was never called
anywhere in the app, so every module's `logger.info()`/`logger.warning()`
call — including the ones added by this fix — silently went nowhere.
Fixed in backend/app/main.py + backend/app/config.py (new `LOG_LEVEL`
setting, `httpx`/`httpcore` pinned to WARNING to prevent API-key leakage
via header logging at DEBUG), and `deploy/qwen-ebook-backend.container`
now sets `LOG_LEVEL=DEBUG`. Not part of files_changed above since it's an
unrelated observability gap, not a content-loss fix.)
