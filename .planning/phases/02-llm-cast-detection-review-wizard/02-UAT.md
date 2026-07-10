---
status: testing
phase: 02-llm-cast-detection-review-wizard
source: [02-VERIFICATION.md]
started: 2026-07-10T12:19:41Z
updated: 2026-07-10T12:19:41Z
---

## Current Test

number: 1
name: Real-key Grok prompt-quality smoke test
expected: |
  With a real XAI_API_KEY and LLM_BACKEND=grok, POST a short public-domain chapter and
  eyeball the returned cast/segments for sane traits, correct speaker tags, and no
  duplicate/renamed characters across chunks. Expected: narrator + speaking cast with
  plausible age/gender/personality descriptions; ordered segments correctly tagged; a
  repeat character referenced differently (e.g. "the old man") resolves to its existing
  cast entry instead of duplicating.
awaiting: user response

## Tests

### 1. Real-key Grok prompt-quality smoke test
expected: With a real XAI_API_KEY and LLM_BACKEND=grok, POST a short public-domain chapter and eyeball the returned cast/segments for sane traits, correct speaker tags, and no duplicate/renamed characters across chunks. Expected: narrator + speaking cast with plausible age/gender/personality descriptions; ordered segments correctly tagged; a repeat character referenced differently (e.g. "the old man") resolves to its existing cast entry instead of duplicating.
result: [pending]

### 2. Live browser click-through of the cast-review wizard
expected: Run `npm run dev` against a `LLM_BACKEND=mock TTS_BACKEND=mock` backend and click through the wizard in a real browser — upload a .txt and an .epub, watch the analyzing progress bar/skeleton, type into a character's name/description/voice-instructions fields and blur to confirm auto-save (no Save button), open the merge dialog and confirm the exact wording, click play/pause on a voice-assigned character's preview and confirm audible native-<audio> playback. Expected: all transitions (empty -> analyzing -> wizard) render correctly; edits persist on blur; merge dialog shows the exact copywriting-contract wording; preview plays back audio.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
