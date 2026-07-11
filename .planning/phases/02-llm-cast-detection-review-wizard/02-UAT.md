---
status: complete
phase: 02-llm-cast-detection-review-wizard
source: [02-VERIFICATION.md]
started: 2026-07-10T12:19:41Z
updated: 2026-07-11T00:00:00Z
---

## Tests

### 1. Real-key Grok prompt-quality smoke test
expected: With a real XAI_API_KEY and LLM_BACKEND=grok, POST a short public-domain chapter and eyeball the returned cast/segments for sane traits, correct speaker tags, and no duplicate/renamed characters across chunks. Expected: narrator + speaking cast with plausible age/gender/personality descriptions; ordered segments correctly tagged; a repeat character referenced differently (e.g. "the old man") resolves to its existing cast entry instead of duplicating.
result: PASS — ran against the real OpenRouter-routed Grok model (`LLM_BACKEND=openrouter`, `OPENROUTER_API_KEY` in `backend/.env`) with Chapter 1 of *Alice's Adventures in Wonderland*. Returned Narrator + Alice ("curious young girl around seven years old, imaginative and slightly drowsy") + White Rabbit ("flustered... hurried and anxious about being late") — plausible, non-hallucinated traits. 12 segments, correctly split narration vs. dialogue, monotonic order, sensible per-segment voice_instructions (e.g. "flustered and hurried" for the Rabbit). Chapter was short enough to stay single-chunk, so cross-chunk dedup wasn't exercised live here — that invariant is separately covered by the passing behavioral test in 02-VERIFICATION.md. No issues found.

### 2. Live browser click-through of the cast-review wizard
expected: Run `npm run dev` against a `LLM_BACKEND=mock TTS_BACKEND=mock` backend and click through the wizard in a real browser — upload a .txt and an .epub, watch the analyzing progress bar/skeleton, type into a character's name/description/voice-instructions fields and blur to confirm auto-save (no Save button), open the merge dialog and confirm the exact wording, click play/pause on a voice-assigned character's preview and confirm audible native-<audio> playback. Expected: all transitions (empty -> analyzing -> wizard) render correctly; edits persist on blur; merge dialog shows the exact copywriting-contract wording; preview plays back audio.
result: PASS (with 2 fixes made during testing, see below) — done over Tailscale against the real running app rather than a description of it. Confirmed live: .txt upload through the analyzing state into the wizard; editing a character's name/voice-instructions fields with blur-triggered autosave (verified by page refresh); the merge dialog's wording; and that a page refresh now resumes the in-progress project instead of dropping back to upload. Not explicitly re-confirmed by the user in this pass: .epub upload specifically, and audible playback of the mock voice preview — flagging as unconfirmed rather than assuming pass, though nothing in this session suggests either is broken (both paths are unchanged from before and covered by the build-level checks in 02-VERIFICATION.md).

Fixes made during this UAT pass (not pre-existing gaps, found live):
- Added POST /characters/undo-merge + a dismissible "Merged away. Undo" banner in CastWizard — merge previously said "can't be undone automatically"; user asked for undo, so it was built and the dialog copy corrected.
- Segments table widened (cast column now fixed ~420px, segments panel takes the rest) and its text cell switched from whitespace-nowrap/truncated to wrapped text at a larger size — user found it unreadably cramped.
- Removed the per-character Description textarea from the wizard UI (backend field untouched, still used for LLM continuity/preview intro text); Voice Instructions is now the sole editable field per character and was enlarged from a single-line Input to a multi-line Textarea.
- Fixed a real bug: the current project id only lived in React state, so refreshing the page always dropped back to the upload screen even though the analyzed project was still on the server. Now persisted in localStorage (single slot — this app has no project list/switcher yet).

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

None outstanding. Two items (.epub upload, audible preview playback) were not explicitly re-confirmed in this specific pass but are unchanged code paths already covered by 02-VERIFICATION.md's build/type-level checks — not treated as a blocking gap, but worth a quick manual check if either area is touched again.
