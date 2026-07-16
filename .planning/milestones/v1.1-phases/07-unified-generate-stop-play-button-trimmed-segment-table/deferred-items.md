# Deferred Items — Phase 07 Plan 04

Out-of-scope discoveries logged per execute-plan scope boundary. Not fixed here.

## Pre-existing whole-project `npm run lint` failures (unrelated to Plan 04)

`npm run lint` (whole-project ESLint) fails on files this plan does not touch:

- `frontend/src/components/ProjectListScreen.tsx:57` — `react-hooks/set-state-in-effect` error (`setError(false)` called synchronously in an effect body)
- `frontend/src/components/ui/badge.tsx:49` — `react-refresh/only-export-components` error
- `frontend/src/components/ui/button.tsx:67` — `react-refresh/only-export-components` error

Confirmed pre-existing: `git status --short` shows only `CharacterCard.tsx` modified when these errors first appeared during Task 1's verify step. `npx eslint src/components/CharacterCard.tsx` (scoped to the file this task touches) lints clean with zero problems. These three files are outside Plan 04's `files_modified` list (`CharacterCard.tsx`, `CastWizard.tsx`) and outside this plan's scope — not fixed.

## Plan 05 re-confirmation (verification checkpoint, no source files modified)

Re-ran `npm run typecheck && npm run lint && npm run build` at the start of Plan 05 (post-merge of Plans 02-04). Same three pre-existing lint errors reproduce, plus two pre-existing warnings not previously logged:

- `frontend/src/components/CastWizard.tsx:54` — `react-hooks/exhaustive-deps` warning on `timeoutsRef.current` cleanup; last touched 2026-07-10 (commit `51f8cf8a`), predates all Phase 7 commits.
- `frontend/src/components/SegmentPreview.tsx:45` and `frontend/src/components/SegmentTable.tsx:390` — React Compiler "Compilation Skipped" warnings caused by TanStack Table's `useReactTable()` API (structural incompatibility with the library, not a Phase 07 regression).

`typecheck` and `build` both pass clean. Plan 05 has `files_modified: []` (verification-only), so none of these are fixable in-scope here either — carried forward for a future cleanup pass, not blocking Phase 7 sign-off (the plan's `<verification>` block only requires the build gate to pass, and pre-existing lint noise is explicitly out of scope per the deviation rules' scope boundary).
