---
phase: 06-config-panel-output-format-filename-download
plan: 02
subsystem: ui
tags: [react, typescript, shadcn, radix-ui, fetch]

requires:
  - phase: 06-config-panel-output-format-filename-download
    provides: "Plan 01's PATCH /projects/{id} (format validation + filename sanitization) and GET /projects/{id}/download (FileResponse with Content-Type/Content-Disposition)"
provides:
  - "client.ts: Project.output_filename field, patchProjectConfig(id, body), downloadUrl(id)"
  - "ConfigPanel.tsx: editable Output Format Select (FLAC/MP3/Opus), editable Output Filename Input with live .{format} suffix, blue Download button"
affects: [06-03-integration]

tech-stack:
  added: []
  patterns:
    - "React 'adjusting state on prop change' render-time pattern (compare current prop to a lastSynced-state variable, setState conditionally during render) instead of useEffect+setState, to satisfy the react-hooks/set-state-in-effect lint rule already enforced in this codebase"
    - "Button asChild wrapping a native <a href download> for a server-driven file download — no fetch/blob JS path, matches previewUrl/segmentAudioUrl's URL-string helper pattern"

key-files:
  created: []
  modified:
    - frontend/src/api/client.ts
    - frontend/src/components/ConfigPanel.tsx

key-decisions:
  - "The Download anchor's `download` attribute is built from `project.output_filename ?? project.filename.replace(/\\.[^.]+$/, \"\")` + `.${project.output_format}` — never a literal \"output\" fallback — so the browser-saved filename always matches the server's D-05 derived stem, satisfying the plan's explicit prohibition"
  - "Filename re-seed uses React's render-time 'adjusting state on prop change' pattern (a lastSyncedFilename state variable compared each render) rather than a useEffect, because this repo's eslint config enforces react-hooks/set-state-in-effect and a useEffect calling setState synchronously in its body fails that rule"

requirements-completed: [CFG-06, CFG-07, CFG-08]

coverage:
  - id: D1
    description: "Output Format is an editable Select (FLAC/MP3/Opus, no WAV) bound to project.output_format; onValueChange PATCHes and refreshes"
    requirement: "CFG-06"
    verification:
      - kind: other
        ref: "cd frontend && npx tsc --noEmit && npm run build (both clean)"
        status: pass
    human_judgment: true
    rationale: "Visual/behavioral acceptance (dropdown renders correctly, PATCH fires on selection, value persists after refresh) is deferred to Plan 03's human-verify checkpoint per this plan's own <verification> section — no frontend test harness exists in this repo to assert it automatically."
  - id: D2
    description: "Output Filename is an editable Input that PATCHes on blur (not per keystroke) and re-seeds its draft from the server-sanitized value, with a static .{output_format} suffix beside it"
    requirement: "CFG-07"
    verification:
      - kind: other
        ref: "cd frontend && npx tsc --noEmit && npm run build (both clean)"
        status: pass
    human_judgment: true
    rationale: "Same as D1 — blur-commit timing and server-echo re-seeding require driving the real input in a browser; deferred to Plan 03's human-verify checkpoint."
  - id: D3
    description: "A primary/blue Download control renders as a native <a href download> when project.output_path exists, and a disabled button with a tooltip otherwise; the download filename matches the server's D-05 derived stem"
    requirement: "CFG-08"
    verification:
      - kind: other
        ref: "cd frontend && npx tsc --noEmit && npm run build (both clean); grep confirms downloadUrl is used as an <a href> via Button asChild, no fetch/blob in the download path"
        status: pass
    human_judgment: true
    rationale: "Downloading a real file and confirming the saved filename requires clicking the anchor in a browser; deferred to Plan 03's human-verify checkpoint."

duration: 5min
completed: 2026-07-15
status: complete
---

# Phase 6 Plan 02: Config Panel Output Format, Filename & Download UI Summary

**Turned the two read-only Output Format / Output File rows in ConfigPanel.tsx into a live-PATCHing Select and Input, and added a blue Download `<a>` button wired to the Plan 01 backend — all through two new client.ts helpers, `patchProjectConfig` and `downloadUrl`.**

## Performance

- **Duration:** ~5 min (first commit 11:14:51, last commit 11:16:59, UTC+2)
- **Started:** 2026-07-15T11:14:51+02:00
- **Completed:** 2026-07-15T11:16:59+02:00
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `Project` interface gains `output_filename: string | null`; the stale "output_format is a fixed server setting" comment is corrected to reflect it's now a per-project PATCHable choice
- `patchProjectConfig(id, { output_format?, output_filename? })` added to client.ts, mirroring `patchCharacter`'s PATCH-then-`parseJsonOrThrow` shape against `/projects/{id}`
- `downloadUrl(id)` added, returning the `/projects/{id}/download` URL string (same "return the string, let the browser fetch it" pattern as `previewUrl`/`segmentAudioUrl`)
- ConfigPanel's Output Format `ConfigField` replaced with a `Select` (FLAC/MP3/Opus, no WAV) that PATCHes and calls `onRefresh()` on change — no disabled/spinner state, since this PATCH claims no generation lock
- ConfigPanel's Output File `ConfigField` replaced with a Filename `Input` + a static `.{output_format}` suffix span; commits on blur only, re-seeds `filenameDraft` from `project.output_filename` whenever the server value changes
- A blue (`variant="default"`) Download `Button` added below the Generate All/Stop stack: renders `asChild` wrapping `<a href={downloadUrl(project.id)} download={...}>` when `project.output_path` exists, disabled with a `title` tooltip otherwise

## Task Commits

Each task was committed atomically:

1. **Task 1: client.ts — Project.output_filename, patchProjectConfig(), downloadUrl()** - `0f8dc0f` (feat)
2. **Task 2: ConfigPanel.tsx — editable Format Select, Filename Input + suffix, Download button** - `e99765a` (feat)

## Files Created/Modified
- `frontend/src/api/client.ts` - `Project.output_filename`, `patchProjectConfig()`, `downloadUrl()`
- `frontend/src/components/ConfigPanel.tsx` - editable Format `Select`, Filename `Input` + suffix, Download `Button`, `handleConfigChange`/`handleFilenameBlur` handlers, `filenameDraft`/`configError`/`lastSyncedFilename` state

## Decisions Made
- **Download filename derivation:** the anchor's `download` attribute is computed as `` `${project.output_filename ?? project.filename.replace(/\.[^.]+$/, "")}.${project.output_format}` `` — matching the server's D-05 derived stem exactly, never a literal `"output"` fallback (per the plan's explicit prohibition, since same-origin browsers honor the anchor's `download` attribute over the response's `Content-Disposition`).
- **Filename re-seed via render-time state adjustment, not `useEffect`:** the plan's `<action>` prose suggested "a `useEffect` on `project.output_filename`", but this repo's eslint config (`react-hooks/set-state-in-effect`, part of the React Compiler ESLint rules already enforced elsewhere in the codebase) flags a `useEffect` that calls `setFilenameDraft` synchronously in its body. Implemented React's own documented alternative instead — a `lastSyncedFilename` state variable compared against `project.output_filename` each render, calling `setFilenameDraft`/`setLastSyncedFilename` conditionally during render rather than in an effect. Same observable behavior (re-seeds whenever the server value changes), passes `npx eslint src/components/ConfigPanel.tsx` clean.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `react-hooks/set-state-in-effect` lint violation from the plan's suggested `useEffect` re-seed pattern**
- **Found during:** Task 2 (ConfigPanel.tsx editable controls)
- **Issue:** Implementing the plan's literal suggestion (a `useEffect` on `project.output_filename` that calls `setFilenameDraft` in its body) triggers `npm run lint`'s `react-hooks/set-state-in-effect` error — a real lint gate already enforced in this codebase (confirmed via `npx eslint src/components/ConfigPanel.tsx`).
- **Fix:** Replaced the `useEffect` with React's documented "adjusting state when a prop changes" render-time pattern — a `lastSyncedFilename` state variable compared each render, updating `filenameDraft` conditionally during render instead of in a post-render effect. Identical observable behavior; no additional dependency or complexity.
- **Files modified:** `frontend/src/components/ConfigPanel.tsx`
- **Verification:** `npx eslint src/components/ConfigPanel.tsx` reports zero issues; `npx tsc --noEmit` and `npm run build` both clean.
- **Committed in:** `e99765a` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug/lint-gate fix)
**Impact on plan:** No scope creep — same D-04 echo behavior the plan specified, implemented via the codebase's already-enforced lint-compliant pattern instead of the plan's literal `useEffect` suggestion.

## Issues Encountered
- `npm install` had not yet been run in this worktree (no `node_modules/`), so the plan's `npx tsc --noEmit`/`npm run build` verify commands initially failed with "This is not the tsc command you are looking for." Ran `npm install` first (508 packages, 0 vulnerabilities) — not a deviation from plan intent, just a prerequisite the plan's verify commands implicitly assumed.
- `npm run lint` surfaced 3 pre-existing errors/warnings unrelated to this plan's files (`ProjectListScreen.tsx`'s own `set-state-in-effect`, and `react-refresh/only-export-components` in `ui/badge.tsx`/`ui/button.tsx`) — confirmed via `git diff --stat HEAD -- <those files>` showing zero changes from this plan. Out of scope per the deviation rules' scope boundary; not fixed, logged here for visibility only.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- CFG-06/CFG-07/CFG-08 are now fully wired end-to-end: the Config Panel drives format/filename entirely through Plan 01's PATCH endpoint and offers a native-download Download button once output exists.
- 06-03 (integration/human-verify) can now exercise the full flow in a browser: pick a format, rename the file, generate, and download — all three controls type-check and build cleanly, with visual/behavioral acceptance deferred to that plan's checkpoint per this plan's own `<verification>` section.
- No blockers identified for 06-03.

---
*Phase: 06-config-panel-output-format-filename-download*
*Completed: 2026-07-15*

## Self-Check: PASSED
