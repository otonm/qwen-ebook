---
phase: 06-config-panel-output-format-filename-download
plan: 03
subsystem: testing
tags: [uat, human-verify, ffmpeg, sanitization, tailscale]

requires:
  - phase: 06-config-panel-output-format-filename-download
    provides: "Plan 01's PATCH /projects/{id} + GET /projects/{id}/download + 3-way ffmpeg dispatch; Plan 02's editable Format Select, Filename Input, and Download button"
provides:
  - "Human acceptance sign-off for CFG-06/07/08: format selection, filename sanitization, and download all verified end-to-end on the real deploy target (host `tts`, RX 9070 XT, https://tts.pigeon-bearded.ts.net)"
  - "Confirmed the backend container's ffmpeg build includes flac/libmp3lame/libopus (resolves the STATE.md libopus blocker)"
  - "sanitize_filename now replaces path separators (/, \\, :) with underscores instead of only keeping the rightmost path segment"
affects: []

tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - backend/app/main.py
    - backend/tests/test_project_config.py

key-decisions:
  - "UAT step 2 surfaced that the plan 06-01 sanitizer behavior (drop everything before the last path separator, i.e. `my/test:book.wav` -> `book`) was not what the user wanted. Decision made during UAT: replace path separators with underscores instead, so `my/test:book.wav` -> `my_test_book`. Applied inline as a Rule 1 auto-fix (bug: sanitizer didn't match desired product behavior) rather than deferred, since it directly blocked UAT step 2's stated expected outcome."
  - "The backend image was stale relative to the code being verified (missing the PATCH/download routes and codec dispatch) and was rebuilt + the qwen-ebook-backend.service restarted as a checkpoint pre-flight step, not treated as a plan deviation since it's routine deploy hygiene."

requirements-completed: [CFG-06, CFG-07, CFG-08]

coverage:
  - id: D1
    description: "Output Format dropdown shows exactly FLAC/MP3/Opus (no WAV) and selecting a format updates the filename suffix live"
    requirement: "CFG-06"
    verification:
      - kind: manual_procedural
        ref: "UAT steps 1 and 3 on https://tts.pigeon-bearded.ts.net"
        status: pass
    human_judgment: true
    rationale: "Real browser dropdown interaction and live suffix update; no frontend test harness in this repo."
  - id: D2
    description: "Output Filename sanitizes illegal characters and path separators on blur, dropping the extension"
    requirement: "CFG-07"
    verification:
      - kind: manual_procedural
        ref: "UAT step 2 on https://tts.pigeon-bearded.ts.net; backend/tests/test_project_config.py::test_patch_project_config_sanitizes_filename (a_b_mybook expectation)"
        status: pass
    human_judgment: true
    rationale: "UAT step 2 revealed the shipped sanitizer behavior didn't match the desired product behavior (drop-prefix vs replace-with-underscore); fixed inline and re-verified live against the running service before sign-off."
  - id: D3
    description: "Generate All produces output, the blue Download button enables, and the downloaded file has the correct extension, codec, and plays"
    requirement: "CFG-08"
    verification:
      - kind: manual_procedural
        ref: "UAT steps 4-7 on https://tts.pigeon-bearded.ts.net, including ffprobe format_name spot-check on the .opus download"
        status: pass
    human_judgment: true
    rationale: "Real file download, codec inspection, and audio playback in a browser/media player; not automatable in this repo's test suite."

# Metrics
duration: N/A (human-verify checkpoint plan)
completed: 2026-07-15
status: complete
---

# Phase 6 Plan 3: Human-Verify Format/Filename/Download End-to-End Summary

**All 7 UAT steps passed on the real deploy target after fixing the filename sanitizer to replace path separators with underscores instead of truncating to the last path segment**

## Performance

- **Duration:** N/A (checkpoint plan — spans a human-verify pause)
- **Completed:** 2026-07-15
- **Tasks:** 1/1
- **Files modified:** 2 (fix applied during UAT)

## Accomplishments
- Confirmed on https://tts.pigeon-bearded.ts.net (host `tts`, RX 9070 XT): Output Format dropdown shows only FLAC/MP3/Opus, filename suffix updates live with format changes, Generate All produces output, the blue Download button enables, downloaded files have the correct extension, correct codec (ffprobe confirms `ogg` container for `.opus`), and are playable
- Confirmed old output is deleted when format changes and only the latest persists
- Resolved the STATE.md libopus blocker: confirmed the backend container's ffmpeg build includes flac, libmp3lame, and libopus
- Fixed `sanitize_filename` (backend/app/main.py) to replace path separators (`/`, `\`, `:`) with underscores rather than keeping only the text after the last separator — `my/test:book.wav` now sanitizes to `my_test_book` instead of `book`
- Rebuilt the backend container image and restarted `qwen-ebook-backend.service` to pick up both the pre-existing stale build and the sanitizer fix; re-verified live before sign-off

## Task Commits

Each task was committed atomically:

1. **Task 1: Human-verify format selection, filename, and download end-to-end** - checkpoint pause, resolved via UAT; sanitizer fix committed as `3f49822` (fix)

**Plan metadata:** (this commit) `docs(06-03): complete human-verify acceptance gate`

## Files Created/Modified
- `backend/app/main.py` - `sanitize_filename` now substitutes path separators with `_` before stripping remaining illegal characters, instead of taking only `Path(candidate).name`-equivalent rightmost segment
- `backend/tests/test_project_config.py` - Updated expected sanitized output for `a/b:my*book.mp3` from the old rightmost-segment result to `a_b_mybook`

## Decisions Made
- Filename sanitization replaces path separators with underscores (not drop-to-last-segment) — see `key-decisions` in frontmatter. This supersedes the deviation documented in 06-01-SUMMARY.md.
- Stale backend image rebuild treated as routine checkpoint pre-flight, not a plan deviation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] sanitize_filename replaced with underscore-substitution behavior**
- **Found during:** Task 1 (UAT step 2)
- **Issue:** The sanitizer shipped in plan 06-01 dropped everything up to and including the last path separator (`my/test:book.wav` -> `book`), which did not match the desired product behavior surfaced during UAT
- **Fix:** Changed `sanitize_filename` to run a `_PATH_SEPARATORS` regex substitution (`/`, `\`, `:` -> `_`) before the existing illegal-character strip, so all path segments are preserved with underscores in place of separators (`my/test:book.wav` -> `my_test_book`)
- **Files modified:** backend/app/main.py, backend/tests/test_project_config.py
- **Verification:** `backend/tests/test_project_config.py` updated and passing; ruff clean; backend image rebuilt and `qwen-ebook-backend.service` restarted; live service re-verified to return `my_test_book` for the UAT test string
- **Committed in:** `3f49822`

---

**Total deviations:** 1 auto-fixed (1 bug fix, surfaced by human UAT)
**Impact on plan:** Necessary correctness fix to match the actual desired product behavior before sign-off. No scope creep — same function, same call sites, no new endpoints or schema changes.

## Issues Encountered
- The deployed backend image was stale (missing the PATCH/download routes and codec dispatch entirely) at the start of the checkpoint. Resolved as pre-flight: rebuilt the image and restarted the service before starting UAT steps.
- STATE.md's open libopus blocker was resolved as part of pre-flight: confirmed via container inspection that ffmpeg supports flac, libmp3lame, and libopus.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
CFG-06/07/08 are fully verified against real behavior on the deploy target. Phase 6 (config panel output format/filename/download) is complete: all three plans (06-01 backend, 06-02 frontend, 06-03 human acceptance) are done and the acceptance gate passed.

---
*Phase: 06-config-panel-output-format-filename-download*
*Completed: 2026-07-15*
