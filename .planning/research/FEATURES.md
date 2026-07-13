# Feature Research

**Domain:** AI multi-voice ebook-to-audiobook / narration tools
**Researched:** 2026-07-09
**Confidence:** MEDIUM-HIGH

## Landscape Surveyed

**Open-source ebook/text-to-audiobook pipelines (closest analogues to this project):**
- [prakharsr/audiobook-creator](https://github.com/prakharsr/audiobook-creator) — LLM character identification + gender/age inference, LLM speaker attribution per line, Kokoro/Orpheus TTS, emotion-tag addition. No documented human review step before generation.
- [DrewThomasson/VoxNovel](https://github.com/DrewThomasson/VoxNovel) — per-character voice actors, includes a "Manual Speaker Assignment Correction Tool" (color-coded text view, checkbox-select lines, bulk-reassign via dropdown, per-line regeneration).
- [Xerophayze/TTS-Story](https://github.com/Xerophayze/TTS-Story) — web-based multi-voice TTS studio, closest architectural analogue: per-speaker voice dropdowns with gender/language filters and inline preview, chunk-level review/regeneration ("editing one chunk triggers regeneration" without full re-synthesis), job queue with per-chunk progress, library of past outputs.
- [psdwizzard/chatterbox-Audiobook](https://github.com/psdwizzard/chatterbox-Audiobook) — multi-voice parsing, automatic chapter detection/organization, batch voice normalization.
- [aedocw/epub2tts](https://github.com/aedocw/epub2tts), [zeropointnine/tts-audiobook-tool](https://github.com/zeropointnine/tts-audiobook-tool), [richardr1126/openreader](https://github.com/richardr1126/openreader) — adjacent single/limited-voice or read-along tools; establish table-stakes baseline (format support, export, sentence-level sync) rather than multi-voice differentiation.

**Commercial tools (feature ceiling, not necessarily targets):**
- [ElevenReader / ElevenLabs Audiobooks](https://elevenlabs.io/audiobooks) — automatic character detection + voice assignment from a manuscript, natural-language voice design ("warm, husky British narrator..."), 800+ preset voices, offline downloads.
- [Play.ht](https://play.ht/) — PlayDialog multi-speaker conversational model, per-paragraph voice assignment, visual timeline editor with SSML-level pacing/emphasis control.

These confirm the domain pattern this project already follows: **LLM-driven cast detection + per-segment voice assignment + multi-voice TTS + join to one file**, with the differentiator being *how much control and efficiency* the human reviewer gets over that pipeline.

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Ebook/text upload (.txt, .epub) | Baseline input for every tool surveyed; epub is the dominant "owned ebook" format | LOW-MEDIUM | epub parsing (extract reading-order text, strip markup/footnotes) is fiddlier than .txt; already scoped in PROJECT.md |
| LLM-based character/cast detection with inferred traits | Every multi-voice tool in this space (audiobook-creator, VoxNovel, ElevenLabs) does this; it's the core value prop, not optional | HIGH | Age/gender/personality inference from context; must handle unnamed/minor characters gracefully (e.g., "Guard 1") |
| Text segmentation into narration vs. dialogue with speaker tags | Required before any multi-voice synthesis can happen; every tool has an internal representation of this (VoxNovel's quotes+speaker, TTS-Story's `[speaker]` tags) | HIGH | Misattribution is common (VoxNovel built a whole correction tool because of it) — review step is not optional |
| Human review/correction of cast + speaker assignment before final audio | VoxNovel and TTS-Story both ship dedicated correction UIs; audiobook-creator's lack of one is a known gap in that project, not a model to copy | MEDIUM | This is the crux of "minimal manual editing" — LLM proposes, human disposes |
| Per-character voice assignment (dropdown/picker) | Universal — every tool maps character → voice | LOW | Already scoped as Narrator dropdown column |
| Voice preview (listen before assigning) | Standard in TTS-Story, Play.ht, ElevenLabs — users won't commit a voice to 40 lines blind | LOW-MEDIUM | Cheap to add: synthesize a short sample line per candidate voice |
| Batch/background generation with progress indicator | All surveyed tools process asynchronously with a progress/queue UI (TTS-Story job queue, chatterbox batch jobs) — synthesis of a full book takes minutes-to-hours | MEDIUM | Already scoped as right-side "live conversion progress" panel |
| Joining segments into one continuous output file | Universal end product across every tool surveyed | LOW | ffmpeg concat / pydub; already scoped |
| Re-listen/playback of generated audio in-app | Users need to QA before calling it done; standard in every reviewed tool with a web UI | LOW | Simple `<audio>` player per segment + full file |
| Project persistence (reopen a long-running project later) | Full novels take non-trivial wall-clock time; TTS-Story's job/library system and this project's own requirement both assume you don't do this in one sitting | MEDIUM | Not clearly documented in most OSS competitors (a genuine gap in the ecosystem) — treat as required, not assumed-solved by prior art |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|--------------------|------------|-------|
| Unified spreadsheet-style table (Narrator + Voice Instructions + Text in one editable grid) | Most competitors split cast-review and segment-review into separate wizard screens (VoxNovel) or hide segment text entirely (audiobook-creator). A flat, always-editable table is faster for iterative personal tuning — see one row, fix it, move on | MEDIUM | Aligns directly with PROJECT.md's core value ("minimal manual editing") |
| Free-text "voice instructions" blended with character presets | Qwen TTS (and similarly Play.ht's timeline, ElevenLabs' Voice Design) supports natural-language style direction; combining a small preset library with LLM-authored per-segment instructions covers one-off/minor characters without requiring a dedicated voice per character | MEDIUM | Directly avoids the need for large preset voice libraries or voice cloning |
| Segment-level incremental regeneration with content-hash caching | TTS-Story and VoxNumber both support "regenerate this one thing," but neither documents automatic hash-based skip-if-unchanged. For a *self-hosted GPU* pipeline (real compute cost per segment, no cloud API cost ceiling to hide behind), avoiding redundant re-synthesis on every edit is a meaningful efficiency win | MEDIUM-HIGH | See "Incremental Regeneration" section below |
| Self-hosted Qwen TTS on local GPU, zero per-request cost | Every commercial competitor (ElevenLabs, Play.ht) is metered/cloud SaaS; every OSS competitor still typically calls cloud APIs for the *best* voices even if local models are an option. Fully local synthesis + Tailscale-only exposure is a privacy/cost differentiator specific to this project's constraints | HIGH (already a project constraint, not new scope) | ROCm/AMD support is the main technical risk, not a feature-design one |
| Character cast editing (merge/rename/re-describe) feeding voice instructions | VoxNovel supports bulk reassignment of already-split lines; extending that to editing the *cast entry itself* (so "Bob"/"Robert"/"the old man" resolve to one character with one consistent voice) closes a gap none of the surveyed OSS tools document well | MEDIUM | Important because LLM chunk-by-chunk analysis of long novels *will* produce duplicate/inconsistent character names (see Long-Text Handling below) |
| Cost/usage visibility for the LLM analysis step | Not observed in any competitor UI, but meaningful here because analysis of a full novel via a paid cloud LLM (xAI/Grok) has a real, variable cost per project | LOW | Small value-add: show estimated/actual token spend per project |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Multi-user accounts / login / RBAC | "Feels incomplete" without auth, copied reflexively from SaaS templates | Adds a whole auth subsystem, session management, and access-control surface for a tool with exactly one user on a private Tailscale network — pure overhead with zero benefit | Tailscale network membership *is* the access control (already correctly scoped as Out of Scope in PROJECT.md) |
| Cloud sync / multi-device sync | "What if I want to edit from my phone and laptop?" | Introduces conflict resolution, remote storage, and a sync protocol for a single physical deployment that's already reachable from any device via Tailscale + browser | Just open the same Tailscale URL from any device — no separate sync layer needed |
| Native mobile app | Audiobook consumption is a mobile use case, so it feels natural to want an app | A full native (or even PWA-wrapped) app is a huge scope increase (build pipelines, app store policies, offline storage) for a tool whose *creation* workflow is inherently desktop/table-editing-oriented | Web UI works fine over Tailscale in a mobile browser for occasional checks; actual listening happens via the exported MP3/WAV in any podcast/music player, not inside this app |
| Real-time audio streaming/preview while generating | Feels more "modern"/responsive than batch-then-download | Requires streaming TTS output, partial-file playback, and a much more complex generation pipeline; none of the reviewed OSS competitors (VoxNovel, audiobook-creator, TTS-Story) do this either — they're all batch-job UIs | Progress bar + per-segment "done" state, listen to segments as they complete individually (already effectively achievable once segment audio exists on disk) |
| Voice cloning from user-recorded audio samples | ElevenLabs/VoxNovel(XTTS) both offer it and it *sounds* like the natural next step from "assign a voice" | Entirely separate feature surface: recording/upload UX, consent/quality requirements, a different model path, and it doesn't serve the stated goal (turning already-owned text into passable narration) | The preset-voice + free-text voice-instructions approach already covers character variety without needing cloned voices |
| SSML / fine-grained audio timeline editor (Play.ht-style) | Looks powerful, gives "professional" pacing/emphasis control | Massive UI/UX surface (waveform editing, per-word timing) that competes with the actual differentiator (fast table-based iteration); users of a personal tool will just re-word the "Voice Instructions" text and regenerate instead | Free-text voice instructions + full segment regeneration loop is already an acceptable substitute at personal-use quality bar |
| Automatic chapter markers / M4B audiobook container output | "Real" audiobooks have chapters; chatterbox-audiobook does this | Requires audiobook-specific metadata handling, a different container/muxing step, and chapter-boundary detection logic — real complexity for a feature the user didn't ask for (already correctly deferred in PROJECT.md) | Plain MP3/WAV for v1, exactly as scoped; revisit only if chapter navigation becomes a real pain point during actual commute/workout listening |
| Emotion-tag markup layer (separate from voice instructions) | audiobook-creator ships a distinct "emotion tag addition" LLM pass | Redundant machinery: this project's per-segment free-text "Voice Instructions" field already lets the LLM (or the user) express emotion/delivery directly, without inventing and maintaining a separate tag vocabulary/parser | Fold emotion/delivery guidance into the existing Voice Instructions text column — one mechanism, not two |
| Full git-like version history / diff of every edit | Spreadsheet-style editing invites "what if I want to undo 5 edits ago" | Real version control (storage growth, diff UI, branching semantics) is disproportionate for a personal tool; no competitor in this space offers it | Keep it simple: regenerate-on-edit with the previous segment audio retained until the next successful regenerate (cheap "last good" fallback), not full history |
| Usage analytics / telemetry dashboards | Common in commercial products; feels "complete" | Nobody but the single user will ever see this data; building collection/storage/visualization for it is pure waste | Skip entirely; if debugging is needed, plain logs are sufficient |

## Feature Dependencies

```
Ebook/text upload (.txt/.epub)
    └──requires──> Text extraction/normalization (strip epub markup, reading order)
                       └──feeds──> LLM cast detection (chunked for long texts)
                                       └──feeds──> LLM segmentation (narration/dialogue split, tied to detected cast)
                                                       └──feeds──> Cast review UI (merge/rename/edit/voice-assign)
                                                       └──feeds──> Segment table UI (Narrator/Instructions/Text)

Voice preview
    └──requires──> TTS engine available at review time (not just at final generation)

Per-segment TTS generation
    └──requires──> Finalized segment table (speaker + instructions + text per row)
    └──enables──> Segment-level incremental regeneration (content-hash caching)
                       └──requires──> Per-segment audio file storage keyed by row id + content hash
                       └──enables──> Fast rejoin (audio concat only, no re-synthesis) on any single-row edit

Project persistence (save/reopen)
    └──requires──> Durable storage of: source text, cast, segment table, per-segment audio + hashes, final joined file

Character cast merge/rename
    └──enhances──> LLM cast detection (corrects cross-chunk duplicate-character artifacts on long novels)

Cost/usage visibility ──enhances──> LLM cast detection & segmentation (helps decide chunk size / model choice)

Real-time streaming preview ──conflicts──> Segment-level incremental regeneration + simple batch job model
    (streaming implies a fundamentally different generation architecture; not worth combining with the caching-based approach)
```

### Dependency Notes

- **Segment table UI requires LLM segmentation, which requires LLM cast detection:** the pipeline is strictly sequential for a first pass on a new project — you cannot show a sensible Narrator dropdown before characters exist, and you cannot split text into segments without knowing who's talking.
- **Incremental regeneration requires per-segment audio storage keyed by content hash:** without persisting individual segment audio files (not just the final joined file) and a hash of `(text, speaker, voice instructions)` per segment, there is no way to detect "this row is unchanged, skip it" — this is the single most load-bearing architectural decision from the Features research and should land early in the roadmap.
- **Character cast merge/rename enhances LLM cast detection:** because long novels must be analyzed in chunks (see below), the LLM will sometimes emit the same character under different names/descriptions in different chunks. A merge UI is not a nice-to-have polish item — it is the mechanism that makes chunked long-text analysis usable at all.
- **Real-time streaming conflicts with the caching/regeneration model:** these are architecturally different approaches to "give the user audio quickly." This project should commit to the batch + cache model (matches PROJECT.md's explicit Out of Scope decision) rather than attempting both.

## Long-Text Handling (Full Novels)

**LLM analysis (cast detection + segmentation):**
A full novel (roughly 80k-120k+ words, ~150k-250k+ tokens) will typically exceed what can be reliably processed as a single structured-extraction pass, even against large context windows — long-context models are known to become less reliable at exhaustive extraction tasks (missing entities, drifting formatting) as input grows, independent of the raw context-window ceiling (MEDIUM confidence, general LLM long-context behavior, not novel-specific benchmarked). The domain-standard mitigation observed in chunking-strategy literature is:

- Process the text in **overlapping chunks** (commonly 10-20% overlap between chunks) so no character introduction or dialogue is cut at a boundary with zero context.
- Carry a **running "known cast so far" summary** into each subsequent chunk's prompt, so the LLM extends/reuses existing characters instead of re-inventing them under new names.
- Run a **reconciliation/merge pass** after all chunks are processed to deduplicate characters that still ended up split across chunks (e.g., "Bob" in chunk 1 vs. "Robert" in chunk 5) — this is exactly what the Character cast merge/rename UI (differentiator, above) exists to make cheap to fix when the automated reconciliation isn't perfect.
- Chunk boundaries should prefer natural structure (chapter/section breaks) over arbitrary word counts where the source format provides it (epub gives you chapter boundaries for free; .txt does not).

**TTS generation (per-segment length limits):**
Cloud TTS engines vary widely and set a hard ceiling per API call: OpenAI TTS caps at 4096 characters/request (confirmed, [OpenAI community docs](https://community.openai.com/t/tts-with-more-than-4096-characters/591842)); Google Cloud TTS caps around 5000 bytes per request, with reports of much lower practical limits (~500-600 characters) for higher-quality Neural2 voices ([Google Cloud TTS quotas](https://cloud.google.com/text-to-speech/quotas)). Qwen3-TTS's own hard input-length ceiling is **not clearly documented** (LOW confidence) — Qwen3-TTS reports being able to synthesize 10+ minutes of stable long-form speech in one generation ([Qwen3-TTS technical writeup](https://medium.com/data-science-collective/high-quality-long-form-tts-with-qwen3-open-weight-models-cdd6e3d00df0)), suggesting it is more generous than legacy cloud engines, but this should be verified empirically against the specific self-hosted model/checkpoint before relying on it.

Practical implication for this project: because segments are already defined at the narration-paragraph / dialogue-turn granularity (not "one segment per chapter"), most individual rows will naturally fall well under any of these limits. The remaining risk is a single very long narration paragraph in a source text — the app should defensively **cap segment length and split oversized rows on sentence boundaries** (never mid-sentence) before sending to TTS, using a conservative default (e.g., a few hundred characters, tunable) until real limits are confirmed against the deployed Qwen TTS build, then rejoin the sub-chunks back into one row's audio before the row-level "regenerate this row" semantics apply.

**Confidence:** MEDIUM overall for chunking strategy (well-established RAG/long-context pattern, not novel-specific benchmark), LOW for Qwen3-TTS's exact per-request limit (should be validated during implementation, not assumed).

## Incremental Regeneration & Caching Pattern

Evidence from TTS-Story ("editing one chunk triggers regeneration" without reprocessing the whole project) and VoxNovel ("regenerate specific lines if they came out weird") confirms row/segment-level regeneration is an established pattern in this exact domain, matching PROJECT.md's stated requirement. Neither project's public documentation describes the caching mechanism in detail, so the following is a synthesized recommendation (MEDIUM confidence, standard software-engineering pattern applied to this domain, not directly sourced):

- Compute a **content hash per segment** over the tuple `(narrator/character id, voice instructions text, segment text, voice/model version)`.
- Persist each segment's audio file **individually** (not only the final joined output), keyed by segment id + its hash.
- On any edit to a row, only that row's hash changes → mark it dirty → regenerate only that row's audio.
- **Rejoin is a separate, cheap step** (audio concatenation, not re-synthesis) that runs after any regeneration, using the current set of per-segment audio files in table order.
- Because hashing includes the voice/model version, a future model or voice-config change can invalidate and regenerate exactly the affected segments rather than requiring a blanket "regenerate everything," even though a full-project regenerate should remain available as an explicit user action.
- This pattern also naturally gives "resume an interrupted generation" for free — on reopening a project, any segment whose hash already has a matching cached audio file doesn't need to be regenerated, whether the app was closed intentionally or crashed mid-run.

## MVP Definition

### Launch With (v1)

Matches PROJECT.md's Active requirements; research confirms these are the correct, non-negotiable table-stakes set for this domain.

- [ ] .txt/.epub upload — the baseline input every competitor supports
- [ ] LLM cast detection with age/personality/gender inference, chunked with cross-chunk cast continuity for long texts
- [ ] LLM text segmentation into narration/dialogue with per-segment suggested speaker + voice instructions
- [ ] Cast review step (rename/merge/edit descriptions/assign+preview voice) before segment generation — closes the exact gap that made VoxNovel build a correction tool
- [ ] Editable segment table (Narrator dropdown / Voice Instructions / Text)
- [ ] Per-row TTS generation via self-hosted Qwen TTS
- [ ] Content-hash-based per-segment caching so editing one row only regenerates that row, then rejoins
- [ ] Ordered audio concatenation into one MP3/WAV
- [ ] Project save/reopen (source text, cast, segments, cached segment audio, joined output)
- [ ] Progress indicator during batch generation

### Add After Validation (v1.x)

- [ ] Voice preview (listen to a candidate voice/instruction before committing) — cheap, high value, but not required to validate the core loop
- [ ] Bulk row operations (select multiple segments, reassign speaker in one action) — valuable once real novels surface repetitive misattribution patterns, as VoxNovel's design implies
- [ ] Cost/usage visibility for the LLM analysis step — nice-to-have once real per-project cost data exists to make it meaningful
- [ ] "Last good" segment audio fallback if a regenerate produces an unusable result

### Future Consideration (v2+)

- [ ] Chapter markers / M4B export — only if plain MP3 playback in the user's actual listening app turns out to be annoying without chapter navigation
- [ ] Voice cloning from personal recordings — a genuinely separate feature; revisit only if the preset+instructions approach proves insufficient for a specific character
- [ ] PDF input — deferred per PROJECT.md; epub/txt cover the near-term use case

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|----------------------|----------|
| LLM cast detection + segmentation | HIGH | HIGH | P1 |
| Cast review/edit UI | HIGH | MEDIUM | P1 |
| Editable segment table | HIGH | MEDIUM | P1 |
| Per-row TTS generation | HIGH | HIGH | P1 |
| Content-hash caching + partial regeneration | HIGH | MEDIUM-HIGH | P1 |
| Audio concatenation/rejoin | HIGH | LOW | P1 |
| Project save/reopen | HIGH | MEDIUM | P1 |
| Long-text chunking with cross-chunk cast continuity | HIGH (only for full novels) | HIGH | P1 |
| Voice preview | MEDIUM | LOW | P2 |
| Bulk row reassignment | MEDIUM | LOW-MEDIUM | P2 |
| Cost/usage visibility | LOW-MEDIUM | LOW | P2 |
| Chapter markers / M4B | LOW (for stated use case) | MEDIUM-HIGH | P3 |
| Voice cloning | LOW (for stated use case) | HIGH | P3 |

**Priority key:** P1 = must have for launch, P2 = should have, add when possible, P3 = nice to have, future consideration

## Competitor Feature Analysis

| Feature | audiobook-creator | VoxNovel | TTS-Story | Our Approach |
|---------|--------------------|----------|-----------|--------------|
| Cast/speaker review before final generation | Not documented (gap) | Yes — color-coded text + checkbox/dropdown bulk reassign | Yes — per-speaker dropdown with preview | Yes — dedicated cast review step, plus ongoing edits via the segment table itself |
| Segment/line-level regeneration | Not documented | Yes — "regenerate specific lines" | Yes — chunk regen without full reprocess | Yes, plus explicit content-hash caching to make it deterministic and skip unchanged rows |
| Unified editable table (speaker + instructions + text together) | No (separate pipeline stages) | No (separate correction tool, then TTS step) | Partial (per-speaker settings, not a flat per-line grid) | Yes — single spreadsheet-like table is the primary editing surface |
| Long-text/full-novel chunking strategy | Batches for LLM steps, no documented cross-chunk cast reconciliation | Not clearly documented | Sentence-aware chunking for TTS, not addressing LLM analysis chunking | Chunked LLM analysis with running known-cast context + explicit merge UI for cross-chunk duplicates |
| Self-hosted GPU TTS | Yes (Kokoro/Orpheus) | Yes (XTTS, voice cloning) | Yes (multiple local engines) | Yes (Qwen TTS on AMD/ROCm) — consistent with ecosystem norm of local-first OSS tools |
| Project persistence | Not documented | Not documented | Partial (jobs.db + library) | Explicit first-class requirement — this is where this project should be more deliberate than the ecosystem baseline |

## Sources

- [prakharsr/audiobook-creator (GitHub)](https://github.com/prakharsr/audiobook-creator) — MEDIUM confidence (README-derived, no independent verification of behavior)
- [DrewThomasson/VoxNovel (GitHub)](https://github.com/DrewThomasson/VoxNovel) — MEDIUM confidence
- [Xerophayze/TTS-Story (GitHub)](https://github.com/Xerophayze/TTS-Story) — MEDIUM confidence
- [psdwizzard/chatterbox-Audiobook (GitHub)](https://github.com/psdwizzard/chatterbox-Audiobook) — LOW-MEDIUM confidence (search-summary only, not fetched directly)
- [aedocw/epub2tts](https://github.com/aedocw/epub2tts), [zeropointnine/tts-audiobook-tool](https://github.com/zeropointnine/tts-audiobook-tool), [richardr1126/openreader](https://github.com/richardr1126/openreader) — LOW confidence (listed, not deep-fetched; used only to confirm table-stakes baseline)
- [ElevenLabs Audiobooks](https://elevenlabs.io/audiobooks), [ElevenReader](https://elevenreader.io/) — MEDIUM confidence
- [Play.ht](https://play.ht/) — MEDIUM confidence (aggregator-sourced, not official docs directly fetched)
- [OpenAI TTS 4096-character limit discussion](https://community.openai.com/t/tts-with-more-than-4096-characters/591842) — HIGH confidence (official community/support thread)
- [Google Cloud Text-to-Speech quotas](https://cloud.google.com/text-to-speech/quotas) — HIGH confidence (official docs)
- [Qwen3-TTS technical report](https://arxiv.org/html/2601.15621v1), [Qwen3-TTS long-form TTS writeup](https://medium.com/data-science-collective/high-quality-long-form-tts-with-qwen3-open-weight-models-cdd6e3d00df0) — LOW-MEDIUM confidence (no explicit max-input-length figure found; flagged as a gap to validate during implementation)
- [Alibaba Cloud Model Studio Qwen-TTS docs](https://www.alibabacloud.com/help/en/model-studio/qwen-tts) — checked directly, does not state a text-length limit (only a 1,600-token instruction-length limit)
- General chunking-strategy sources (RAG-oriented, applied by analogy to LLM novel analysis): [Weaviate chunking strategies](https://weaviate.io/blog/chunking-strategies-for-rag), [Firecrawl chunking strategies 2026](https://www.firecrawl.dev/blog/best-chunking-strategies-rag) — MEDIUM confidence (general LLM pattern, not novel/character-extraction-specific)

---
*Feature research for: AI multi-voice ebook-to-audiobook / narration tools*
*Researched: 2026-07-09*

---

# v1.1 Milestone Addendum: Generation-Control UX & Config Panel

**Domain:** Generation-control UX (single generate/cancel/play button) and config-panel controls for a self-hosted TTS audiobook tool
**Researched:** 2026-07-13
**Confidence:** MEDIUM (web/UX-pattern sources, cross-checked across multiple independent write-ups; no primary vendor docs apply here since this is a UI/UX pattern question, not a library API question)

## Existing App Context (from codebase, not research — grounds the recommendations below)

- `frontend/src/hooks/useGenerationLock.ts` polls `GET /generation-status` every 1.5s and exposes a single app-wide boolean: **only one generation (a segment, a character preview, or a batch run, in ANY project) may be in flight at a time**, backend-enforced. Every generate-triggering control already consumes this (`SegmentTable.tsx`, `CharacterCard.tsx`, `ConfigPanel.tsx`).
- `SegmentTable.tsx`'s `GeneratePlayButton` already does generate/play double-duty on one icon button (comment: `TBL-04`), but has no color coding and no "stop" state — it's disabled (not stoppable) while `generationLocked` is true and it isn't the row generating.
- `ConfigPanel.tsx`'s batch "Stop" button (`handleStop` → `cancelBatchGeneration`) is explicitly **best-effort, not immediate**: the visible copy is *"Stops before the next segment — the segment currently generating may still finish."* This is a real, already-shipped constraint of the backend cancellation mechanic — there is no per-inference-call kill switch today.
- `STATUS_BADGE` in `SegmentTable.tsx` is a separate `Badge` column mapping `GenerationStatus` (`pending/queued/generating/complete/error`) to label+icon+variant. The milestone drops this column and folds its meaning into button color.

This context is the load-bearing constraint for everything below: the milestone's "click kills it immediately" promise for the red Stop state is a **UX/product requirement that is not yet backed by matching backend behavior** — flagged as a pitfall, not solved here (out of scope for this research file, in scope for the phase that builds it).

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Button label changes with state (icon + text, not icon alone) | NN/g's state-switch research: icon-only or color-only state changes are the #1 cause of user confusion in state-switch controls (their WebEx mute case study: red already meant something else, so red alone didn't communicate "muted"). Users need color **and** text **and** icon to agree. | LOW | Already partially true here (`GeneratePlayButton` swaps icon); milestone adds color + explicit verb label ("Generate Preview" / "Stop Generation" / "Play"). |
| Button synchronously disables/locks before any network call fires | Standard "lock-before-request" pattern — disabling on `.then()` or on a query-library's `isPending` flag leaves a window where a fast double-click fires two requests. This app already has a *global* lock (`useGenerationLock`) for cross-control races, but each button's *own* click handler needs the same synchronous guard against back-to-back clicks on itself before the poll/prop update lands. | LOW | `handleClick` in `GeneratePlayButton` already sets `isGenerating` before `await` — keep this shape when adding the stop state; don't regress it. |
| Any edit invalidating the audio visibly reverts the control to "stale/idle" | Confirmed existing product decision (GEN-03, invalidate-not-regenerate). The button-color scheme's yellow state IS the visual carrier for "stale" now that the badge column is gone — this is table stakes for the whole redesign to make sense, not optional polish. | LOW | Backend already flips `generation_status` back to `pending` on edit; frontend just needs to read that into the yellow state, no new backend logic. |
| Download button appears only once the artifact actually exists, pre-filled with the configured filename | Carbon Design System's export pattern and general web convention: don't show a Download affordance for a file that doesn't exist yet, and don't force the user to retype a name that's already known (project's `output_path`/editable filename field). | LOW | Filename is already a planned config-panel field (v1.1 target); Download button just needs to gate on `project.output_path` truthiness, mirroring how `ConfigPanel.tsx` already gates the "Output File" row (`project.output_path ? ... : "Not generated yet"`). |
| Stop control gives instant visual feedback even if the actual kill is delayed | Standard cancel-affordance microcopy pattern: disable-and-relabel ("Stopping…") immediately on click regardless of how long the backend actually takes to honor it, so the user isn't left wondering if the click registered. | LOW | Directly reusable: `ConfigPanel.tsx` already has this exact shape (`isCancelling` state, spinner) for the batch Stop — extend the pattern to per-row/per-character, don't reinvent it. |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| One consistent 3-state color button reused identically across row/character/batch scopes | Most batch-job UIs (rendering queues, image-gen tools) use *different* controls per scope (icon button for items, labeled button for the whole batch) — unifying the visual language so "yellow/red/green means the same thing everywhere in this app" is a genuine differentiator for a single-user tool where the user will build muscle memory fast. Low cost here because the app already centralizes state through `generationLocked` + `GenerationStatus`. | MEDIUM | The differentiator is *consistency*, not novelty — do not invent a 4th state or per-scope variant; that would undo the value. |
| Plain-language model-size labels in the model dropdown (not raw model IDs) | uxpatterns.dev's model-selector pattern: label by tradeoff ("Faster, lower VRAM" vs "Higher quality") rather than raw identifiers like `1.7B`/`0.6B`. Since this app already surfaces `TTS_MODEL_DISPLAY_NAME` as a single fixed string today, switching to a tradeoff-labeled dropdown is a small but real UX upgrade over just listing two SKUs. | LOW | Keep the actual size in parentheses for a technical single user (`Higher quality (1.7B)` / `Faster (0.6B)`) — full plain-language-only labeling is overkill for a one-person tool per PROJECT.md's "no multi-tenant/simple audience" framing. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Making the Stop button *look* instant by optimistically clearing `generating` state client-side before the backend confirms | Feels more responsive; "the spinner should stop the instant I click Stop" | Creates a lying UI: the GPU call is still running (backend stop is best-effort, "may still finish"), so if the button flips to yellow/idle immediately, a second click could re-trigger generation while the old inference is still occupying the GPU/lock — reintroducing exactly the double-generate race this milestone is trying to eliminate | Show a transitional "Stopping…" label (disabled) between the click and the backend actually confirming cancellation via the lock/status poll — same pattern already used for `isCancelling` in `ConfigPanel.tsx`; extend, don't bypass |
| A 4th button color/state for "queued" (batch item waiting its turn, distinct from "generating") | The old `STATUS_BADGE` map had `queued` as a real enum value | Milestone brief explicitly cycles only 3 states (yellow/red/green) and folds `queued` into "not yet generating" — adding a 4th visual state contradicts the stated simplification goal and re-introduces the ambiguity being removed | Treat `queued` as part of the yellow "idle/stale" state until the row's own generation actually starts (i.e. `generation_status === "generating"` is the only trigger for red) |
| True hard-kill of the in-flight Qwen TTS inference call (interrupting the GPU mid-forward-pass) to make Stop *literally* immediate | The milestone's copy says "click kills it immediately" | This is a backend/infra problem (interrupting a synchronous HF `transformers` generate() call cleanly), not a UX pattern — no amount of button design solves it, and the existing Stop already documents itself as "stops before the next segment." Conflating the UX fix with a backend rewrite risks scope creep into a much harder problem for a single-GPU personal tool. | Scope this phase to *UX-level* immediacy (instant disable + relabel + fast lock-status poll so "generating" flips to "idle" as soon as the current segment's call actually returns) and flag the literal-mid-inference-kill as a separate, harder backend problem if the user later finds "stops before next segment" unacceptable in practice |
| Auto-download the joined file the moment it's ready (no click required) | "Save the user a click once it's done" | Browsers block/flag unsolicited downloads as intrusive, and for a long unattended batch run the user may not be at the browser when it finishes — an unexpected auto-download either gets blocked by the browser or silently fills a Downloads folder with no context | Blue "Download" button that appears once ready and stays there; user-initiated, matches the Carbon export pattern and the app's existing pattern of user-triggered rather than auto-fired actions (consistent with the GEN-03 "no auto-regenerate on edit" decision) |

## Feature Dependencies

```
[generationLocked (existing global lock)]
    └──gates──> [Yellow "Generate Preview" state's clickability]
    └──gates──> [Batch "Generate All" disabled state]
                       (unchanged by this milestone — reuse as-is)

[GenerationStatus enum: pending/queued/generating/complete/error]
    └──maps-to──> [3-color button state]
                       pending/queued  → yellow
                       generating      → red
                       complete        → green
                       error           → yellow (treated as "needs regen", not a 4th color)

[Per-row/per-character/batch Stop click]
    └──requires──> [existing cancelBatchGeneration-style backend endpoint, extended to per-row/per-character scope]
                       └──constrained-by──> [current best-effort-only cancellation semantics]

[Config panel model-size dropdown]
    └──conflicts-with──> [generationLocked being active]
                       (switching models mid-generation would be undefined —
                       disable the dropdown while any generation is in flight,
                       same guard already used elsewhere in ConfigPanel)

[Blue "Download" button]
    └──requires──> [project.output_path populated, i.e. join already completed]
    └──enhances──> [existing joined-output flow — no new backend join logic needed]

[Green "Play" for joined file]
    └──requires──> [same output_path as Download]
    └──reuses──> [existing <audio> play/pause pattern from GeneratePlayButton/CharacterCard]
```

### Dependency Notes

- **Button color state requires the `GenerationStatus` enum, not a new client-side status model.** The backend enum already distinguishes every state the button needs; this is a rendering change (`STATUS_BADGE` → button variant), not a new data model.
- **The 3-state button conflicts with, and must respect, the existing `generationLocked` app-wide single-flight lock.** Yellow "Generate Preview" must stay non-clickable (or route to a disabled/locked visual) whenever `generationLocked` is true and this particular row/character isn't the one running — exactly the existing `isDisabled = isRowGenerating || (!hasAudio && generationLocked)` logic in `GeneratePlayButton`, extended with the red state instead of a spinner-and-disable.
- **Stop enhances but does not replace the lock.** The lock still prevents a *second* generation from starting; Stop is about ending the *first* one early. These are two different mechanisms and both need to keep working together — don't let adding Stop weaken the existing race protection.
- **Model-size dropdown conflicts with an in-flight generation** — switching the resident model while a generation is running is undefined behavior for a single-VRAM-budget load-on-demand setup (PROJECT.md: "only one resident in VRAM at a time"). The dropdown should reuse `generationLocked` as its own disabled-condition, the same dependency every other generate-triggering control already has.

## MVP Definition

### Launch With (v1.1, per PROJECT.md milestone scope)

- [ ] 3-column segment table (Narrator / Voice Instructions / Text), Status badge column removed — table-stakes simplification, zero new backend work
- [ ] Single 3-state color button (yellow/red/green) applied identically to per-row, per-character-preview, and batch Generate All — table stakes for this milestone's stated goal; reuses existing `GenerationStatus`/`generationLocked` machinery
- [ ] Edit-invalidates-to-yellow behavior wired to the color button (already backend-supported via GEN-03) — table stakes, no new logic
- [ ] Config panel: model-size dropdown (1.7B/0.6B, disabled while `generationLocked`), output-format dropdown (FLAC/MP3/Opus, WAV dropped), editable output-filename text field — table stakes per milestone brief
- [ ] Blue Download + green Play for the joined output file, gated on `output_path` existing — table stakes per milestone brief

### Add After Validation (v1.x)

- [ ] Plain-language tradeoff labels on the model dropdown ("Higher quality" / "Faster") instead of just size numbers — nice differentiator, trivial to add once the dropdown exists, not required for the milestone's stated goal
- [ ] "Stopping…" transitional label distinct from the steady-state red, if user testing shows the red→idle transition on Stop feels laggy given the best-effort backend cancellation — only build if the existing pattern (already shipped in `ConfigPanel.tsx`'s `isCancelling`) proves insufficient once extended to per-row scope

### Future Consideration (v2+)

- [ ] True mid-inference hard-kill of the GPU call (vs. today's stop-before-next-segment) — genuinely hard backend problem (interrupting a synchronous `transformers.generate()` call), explicitly out of scope for a UX-pattern milestone; revisit only if the best-effort stop proves unacceptable in real use
- [ ] Auto-play or auto-download on batch completion — anti-feature per research above; keep user-triggered

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| 3-color generate/stop/play button (all 3 scopes) | HIGH | MEDIUM (mostly rendering + wiring existing state, but touches 3 components) | P1 |
| Drop Status badge column, trim table to 3 columns | MEDIUM | LOW | P1 |
| Model-size dropdown | MEDIUM | LOW (frontend) / MEDIUM (backend: load-on-demand swap logic already implied by PROJECT.md, may be partly built) | P1 |
| Output-format dropdown (FLAC/MP3/Opus) | MEDIUM | LOW | P1 |
| Editable output filename | LOW-MEDIUM | LOW | P1 |
| Download + Play for joined file | HIGH | LOW (mostly reuses existing patterns) | P1 |
| Plain-language model labels | LOW | LOW | P2 |
| "Stopping…" transitional microstate | LOW | LOW | P3 |
| True immediate GPU-call kill | MEDIUM | HIGH | P3 (v2+) |

**Priority key:**
- P1: Must have for this milestone (matches PROJECT.md's stated v1.1 target features exactly)
- P2: Should have, cheap to add once P1 lands
- P3: Nice to have / explicitly deferred to a future milestone

## Sources

- [State-Switch Controls: The Infamous Case of the "Mute" Button — NN/G](https://www.nngroup.com/articles/state-switch-buttons/) — icon+label+color state legibility guidance, MEDIUM confidence (authoritative UX research org, cross-checked)
- [Cancel vs Close: Design to Distinguish the Difference — NN/G](https://www.nngroup.com/articles/cancel-vs-close/)
- [Button UX Design: Best Practices, Types and States — UX Planet](https://uxplanet.org/button-ux-design-best-practices-types-and-states-647cf4ae0fc6)
- [How to design nondestructive cancel buttons — LogRocket Blog](https://blog.logrocket.com/ux-design/how-to-design-nondestructive-cancel-buttons/)
- [Model Selector Pattern — UX Patterns for Developers](https://uxpatterns.dev/patterns/ai-intelligence/model-selector) — plain-language labeling / progressive disclosure for model choice, MEDIUM confidence
- [AI UX Patterns | Parameters — ShapeofAI.com](https://www.shapeof.ai/patterns/parameters)
- [Carbon Design System — Export pattern](https://carbondesignsystem.com/community/patterns/export-pattern/) — download-when-ready/editable-filename pattern, MEDIUM confidence
- [How best to prevent double button clicks and duplicate/parallel mutations — TanStack/query Discussion #10041](https://github.com/TanStack/query/discussions/10041) — lock-before-request race-condition pattern, MEDIUM confidence
- [Preventing Double Form Submission — The Art of Web](https://www.the-art-of-web.com/javascript/doublesubmit/)
- Codebase inspection (HIGH confidence, primary source): `frontend/src/hooks/useGenerationLock.ts`, `frontend/src/components/SegmentTable.tsx`, `frontend/src/components/ConfigPanel.tsx` — existing `generationLocked`, `GenerationStatus`, best-effort batch Stop, and `GeneratePlayButton` generate/play double-duty pattern this milestone extends

---
*Feature research addendum for: Generation-control UX and config-panel capabilities, Qwen Ebook Narrator v1.1*
*Researched: 2026-07-13*
