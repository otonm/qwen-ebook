# Deferred Items — Phase 07 Plan 04

Out-of-scope discoveries logged per execute-plan scope boundary. Not fixed here.

## Pre-existing whole-project `npm run lint` failures (unrelated to Plan 04)

`npm run lint` (whole-project ESLint) fails on files this plan does not touch:

- `frontend/src/components/ProjectListScreen.tsx:57` — `react-hooks/set-state-in-effect` error (`setError(false)` called synchronously in an effect body)
- `frontend/src/components/ui/badge.tsx:49` — `react-refresh/only-export-components` error
- `frontend/src/components/ui/button.tsx:67` — `react-refresh/only-export-components` error

Confirmed pre-existing: `git status --short` shows only `CharacterCard.tsx` modified when these errors first appeared during Task 1's verify step. `npx eslint src/components/CharacterCard.tsx` (scoped to the file this task touches) lints clean with zero problems. These three files are outside Plan 04's `files_modified` list (`CharacterCard.tsx`, `CastWizard.tsx`) and outside this plan's scope — not fixed.
