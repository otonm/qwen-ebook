---
created: 2026-07-14T00:00:00Z
title: Cast Review wizard stop control and layout
area: ui
files:
  - frontend/src/components/CastWizard.tsx
  - frontend/src/components/CharacterCard.tsx
  - frontend/src/components/SegmentPreview.tsx
---

## Problem

Surfaced during Phase 4 (immediate-cancellation) real-hardware testing.
Three related gaps in the Cast Review wizard step (before the main
project screen):

1. `CharacterCard.tsx`'s wizard-side character-preview button has no
   Stop control at all — explicitly deferred from Phase 4 per CONTEXT.md
   D-04 ("not raised as in-scope for Phase 4"). When this preview queue
   holds the app-wide single-flight generation lock, there is currently
   no way to interrupt it anywhere in the UI — twice required a manual
   backend/tts service restart during Phase 4 testing to unblock.
2. `CastWizard.tsx`'s layout: the left column (character cards) stretches
   to full window height instead of sizing to its content, while segments
   render on the right — a pre-existing layout issue, unrelated to
   cancellation.
3. `SegmentPreview.tsx` (the wizard's right-panel, read-only segment
   table) has zero generate-all/stop capability today — confirmed via
   code read, not a regression.

## Solution

TBD. User's idea for (3): replace a "generate all" trigger with a stop
button and track per-segment generation progress on the left (character
side), mirroring the main `SegmentTable.tsx`'s per-row generate/stop
pattern already built in Phase 4. Candidate for Phase 7 (the planned
4-call-site button unification pass) or a dedicated follow-up phase —
not previously scoped there either, since Phase 7 was scoped as
"unify 4 existing implementations," and (1)/(3) here are missing
capabilities, not just inconsistent styling.
