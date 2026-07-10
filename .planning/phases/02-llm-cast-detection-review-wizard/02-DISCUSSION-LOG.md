# Phase 2: LLM Cast Detection & Review Wizard - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-10
**Phase:** 2-llm-cast-detection-review-wizard
**Areas discussed:** Persistence scope, Chunking & cross-chunk cast reconciliation, EPUB parsing scope, Wizard flow & voice preview UX

---

## Persistence scope

| Option | Description | Selected |
|--------|-------------|----------|
| Real SQLModel now | Build the actual Project/Character/Segment tables now per STACK.md's schema plan; Phase 3 extends rather than replaces throwaway state | ✓ |
| In-memory/JSON file for Phase 2 only | Cast+segments held in a per-project JSON scratch file or server memory during the wizard flow | |
| You decide | | |

**User's choice:** Real SQLModel now

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 2 fields only | Project/Character/Segment fields the wizard actually needs; no Phase 3 columns guessed at ahead of time | ✓ |
| Pre-add Phase 3 placeholder fields | Add status/content-hash/audio-path columns now even though nothing populates them yet | |
| You decide | | |

**User's choice:** Phase 2 fields only

| Option | Description | Selected |
|--------|-------------|----------|
| Background task + SSE progress | Upload creates the Project row immediately (status: analyzing) and returns; background asyncio task runs chunk-by-chunk Grok calls, progress via SSE | ✓ |
| Synchronous blocking call | Upload endpoint blocks until all chunks are analyzed | |
| You decide | | |

**User's choice:** Background task + SSE progress

| Option | Description | Selected |
|--------|-------------|----------|
| Add LLM_BACKEND=mock | Mirrors TTS_BACKEND=mock; canned cast/segment JSON so dev/tests don't hit real Grok API | ✓ |
| Always call real Grok API | No mock path to maintain, but costs money/network every dev run | |
| You decide | | |

**User's choice:** Add LLM_BACKEND=mock
**Notes:** Directly mirrors the established Phase 1 TTS_BACKEND=mock convention documented in CLAUDE.md.

---

## Chunking & cross-chunk cast reconciliation

| Option | Description | Selected |
|--------|-------------|----------|
| Single-shot when it fits | Estimate token count; if under a safety margin, send the whole text in one Grok call | ✓ (with caveat) |
| Always chunk (reuse Phase 1's chunker) | Always split into paragraph-based chunks, always run reconciliation loop | |
| You decide | | |

**User's choice:** "single shot, but with a large safety margin, giving large amounts of space to the llm for thinking and computing."
**Notes:** User confirmed single-shot-first but emphasized the margin needs to be generous, not tight — informed D-06 (~50% of context reserved for input).

| Option | Description | Selected |
|--------|-------------|----------|
| Full cast list each time | Complete resolved cast (name + description) as context on every chunk call | ✓ (extended) |
| Cast list + last chunk's tail text | Full cast list plus last ~1-2 paragraphs of previous chunk | |
| You decide | | |

**User's choice:** "cast list + last 20 pieces ([character] text, [narrator] text, ...) for context"
**Notes:** User's answer extended the "recommended" option — full cast list plus the last 20 already-resolved segments (character-tagged), not raw paragraph tail text.

| Option | Description | Selected |
|--------|-------------|----------|
| LLM auto-resolves confident matches | Prompt instructs Grok to reuse existing cast entries when confident; wizard merge tool is the safety net | ✓ |
| Everything to the wizard, no LLM merging | Grok always returns per-chunk detections as-is; user does all reconciliation manually | |
| You decide | | |

**User's choice:** LLM auto-resolves confident matches

| Option | Description | Selected |
|--------|-------------|----------|
| ~50% of context for input text | Text token estimate must be under ~500K tokens to go single-shot; remaining ~500K headroom for output+reasoning | ✓ |
| Fixed input cap regardless of window size | Pick a fixed token number rather than a percentage | |
| You decide | | |

**User's choice:** ~50% of context for input text

---

## EPUB parsing scope

| Option | Description | Selected |
|--------|-------------|----------|
| Heuristic skip of obvious non-content | Skip spine items that look like front/back matter using short-text/filename-id/nav-landmark signals | ✓ |
| Send everything, let LLM sort it out | No pre-filtering; pass full reading-order text to Grok | |
| You decide | | |

**User's choice:** Heuristic skip of obvious non-content

| Option | Description | Selected |
|--------|-------------|----------|
| Strip footnote markers + linked note text | Detect EPUB footnote conventions and drop both marker and note body | ✓ |
| Strip markers only, keep note text inline | Remove inline marker but leave footnote text wherever it appears in reading order | |
| You decide | | |

**User's choice:** Strip footnote markers + linked note text

| Option | Description | Selected |
|--------|-------------|----------|
| Preserve chapter boundaries | Extract text per spine item, keep chapter breaks as natural chunk/analysis boundaries | ✓ |
| Flatten to one text stream | Concatenate all chapters, reuse Phase 1's paragraph chunker verbatim | |
| You decide | | |

**User's choice:** Preserve chapter boundaries

| Option | Description | Selected |
|--------|-------------|----------|
| Skip broken chapter, warn, continue | One malformed chapter shouldn't block the rest of the book | |
| Reject whole upload on any parse failure | Fail fast and loud rather than silently producing an incomplete audiobook | ✓ |
| You decide | | |

**User's choice:** Reject whole upload on any parse failure
**Notes:** User explicitly went against the "recommended" option here — deliberate quality-over-completeness call.

---

## Wizard flow & voice preview UX

| Option | Description | Selected |
|--------|-------------|----------|
| Single-page list | All detected characters shown at once, inline rename/merge/edit/voice-assign | ✓ |
| Step-by-step wizard | One character reviewed at a time with next/back | |
| You decide | | |

**User's choice:** Single-page list

| Option | Description | Selected |
|--------|-------------|----------|
| Read-only segment preview in Phase 2 | Show segmented text as a simple read-only list below/alongside the cast wizard | ✓ |
| No segment view in Phase 2 | Phase 2 UI is cast-wizard only | |
| You decide | | |

**User's choice:** Read-only segment preview in Phase 2

| Option | Description | Selected |
|--------|-------------|----------|
| Pre-fill from LLM description | Auto-generate starting voice-instructions + best-guess preset from inferred description | ✓ |
| Blank default, user opts in | Character starts with neutral preset and empty instructions | |
| You decide | | |

**User's choice:** Pre-fill from LLM description

| Option | Description | Selected |
|--------|-------------|----------|
| Defer VoiceDesign to later | Phase 2 ships CustomVoice preset + free-text instructions only | ✓ |
| Wire in VoiceDesign now as a third option | Wizard offers preset, preset+instructions, or full VoiceDesign generation | |
| You decide | | |

**User's choice:** Defer VoiceDesign to later

---

## Claude's Discretion

- Exact background-task/SSE wiring shape (task registry, endpoint naming, event payload schema).
- Precise token-estimation method for the single-shot-vs-chunk threshold (must respect the ~50% input budget).
- Exact heuristic thresholds for EPUB non-narrative-section skipping and footnote pattern detection.
- Voice-preview generation trigger wiring (eager generation on voice assignment, reusing Phase 1's `tts_client.synthesize()`).
- Internal SQLModel field naming and API request/response shapes.

## Deferred Ideas

- VoiceDesign (custom voice generation) — deferred past Phase 2, revisit only if instruction-steering proves insufficient.
- Phase 3's full editable segment table (inline edit, bulk reassign, per-row generate/preview) — out of Phase 2's boundary.
- Phase 3's generation-status/content-hash caching schema fields — not added speculatively in Phase 2.
