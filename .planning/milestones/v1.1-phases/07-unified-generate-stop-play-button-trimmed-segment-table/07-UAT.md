---
status: complete
phase: 07-unified-generate-stop-play-button-trimmed-segment-table
source: [07-01-SUMMARY.md, 07-02-SUMMARY.md, 07-03-SUMMARY.md, 07-04-SUMMARY.md, 07-05-SUMMARY.md]
started: 2026-07-16T08:00:00Z
updated: 2026-07-16T08:20:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Segment table layout — 3 editable columns, no Status column
expected: Segment table shows exactly 3 editable content columns (Narrator | Voice Instructions | Text), no Status column; row button is amber/red/green Generate/Stop/Play.
result: pass
coverage_id: 07-05/D1

### 2. Segment row button cycles amber → red → green and plays audio
expected: Clicking a segment row's amber "Generate Preview" turns it red "Stop Generation" while generating, then green "Play" when done; clicking green Play plays the generated audio.
result: pass
coverage_id: 07-05/D2

### 3. Editing segment text reverts button to amber
expected: Editing a segment's Text or Voice Instructions reverts that row's button to amber "Generate Preview" — no separate status badge anywhere.
result: pass
coverage_id: 07-05/D3

### 4. ConfigPanel character preview row follows same pattern
expected: Each character preview row in the Config panel has the same Generate/Stop/Play button; editing the character's voice reverts it to amber.
result: pass
coverage_id: 07-05/D4

### 5. CastWizard card preview with working Stop; column sizes to content
expected: CharacterCard preview control in the Cast wizard uses the same button with a working mid-flight Stop; the character-card column sizes to content instead of stretching full height.
result: pass
coverage_id: 07-05/D5

### 6. Batch "Generate All" cycles states and plays joined output
expected: Batch "Generate All" button cycles amber → red → green and green Play plays the joined output; Download stays a separate blue button.
result: pass
coverage_id: 07-05/D6

### 7. Regenerate with existing output shows red Stop, never stale green Play
expected: Re-running Generate All on a project that already has a completed joined output shows red "Stop Generation" during the entire re-run — never green Play (which would play the stale file).
result: pass
coverage_id: 07-05/D7

### 8. Batch control precedence under real timing (07-03 D2)
expected: The batch control is a single full-width button whose state follows stopping > generating > ready > idle under real timing; hidden joined-output audio never auto-plays. (Overlaps tests 6–7 — confirming those covers this.)
result: pass
coverage_id: 07-03/D2

### 9. Hook status precedence order (stopping > generating > ready > idle)
expected: useGenerateStopPlay derives GspStatus in precedence order stopping > generating > ready > idle
result: pass
source: automated
coverage_id: 07-01/D1

### 10. Single-button render matching UI-SPEC §1
expected: GenerateStopPlayButton renders exactly one Button with STATE_CLASSES/STATE_LABEL matching UI-SPEC §1
result: pass
source: automated
coverage_id: 07-01/D2

### 11. outputUrl identical to download route, no new endpoint
expected: outputUrl(projectId) returns the identical route string as downloadUrl, no new backend endpoint
result: pass
source: automated
coverage_id: 07-01/D3

### 12. Plan 01 typecheck/lint clean
expected: frontend typecheck and lint pass with the 3 new/modified files introducing no new errors
result: pass
source: automated
coverage_id: 07-01/D4

### 13. One GenerateStopPlayButton per segment row
expected: Each segment row renders exactly one GenerateStopPlayButton size="sm", no second adjacent Stop button
result: pass
source: automated
coverage_id: 07-02/D1

### 14. Status column and badge machinery removed
expected: Status column, STATUS_BADGE map, StatusBadge function, and dead imports all removed
result: pass
source: automated
coverage_id: 07-02/D2

### 15. Voice Instructions editable column added
expected: Voice Instructions editable column added between narrator and text, reusing generic EditableTextCell
result: pass
source: automated
coverage_id: 07-02/D3

### 16. generationLocked consumed as prop
expected: generationLocked is consumed as a prop, not re-derived via useGenerationLock
result: pass
source: automated
coverage_id: 07-02/D4

### 17. Plan 02 typecheck/lint/build clean
expected: frontend typecheck, lint, and build all pass with no new issues from this plan's edits
result: pass
source: automated
coverage_id: 07-02/D5

### 18. CharacterPreviewRow single unified button
expected: CharacterPreviewRow renders exactly one GenerateStopPlayButton; hasAudio maps from preview_audio_path; playback and per-row error paragraph preserved
result: pass
source: automated
coverage_id: 07-03/D1

### 19. Character edit reverts button via reactive hasAudio
expected: Editing a character's fields reverts the button to amber idle via the hook's reactive hasAudio prop read
result: pass
source: automated
coverage_id: 07-03/D3

### 20. CharacterCard unified button with working Stop
expected: CharacterCard renders exactly one GenerateStopPlayButton driven by useGenerateStopPlay, gaining a working Stop control
result: pass
source: automated
coverage_id: 07-04/D1

### 21. Shared poll ceiling replaces local 60000ms constant
expected: Local hardcoded 60000ms poll ceiling gone; GENERATION_POLL_CEILING_MS used exclusively via shared hook
result: pass
source: automated
coverage_id: 07-04/D2

### 22. CastWizard xl:items-start layout fix
expected: CastWizard outer flex container gains xl:items-start; SegmentPreview.tsx unchanged
result: pass
source: automated
coverage_id: 07-04/D3

### 23. Plan 04 typecheck/build/lint clean
expected: frontend typecheck and build pass; scoped lint on the two modified files clean
result: pass
source: automated
coverage_id: 07-04/D4

## Summary

total: 23
passed: 23
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
