---
phase: 03-editable-table-full-generation-pipeline-persistence-deployment
plan: 04
subsystem: api
tags: [fastapi, sqlmodel, sqlite, react, tanstack]

requires:
  - phase: 03-01
    provides: Project.created_at column, existing Project SQLModel table
  - phase: 03-03
    provides: ProjectScreen 70/30 SegmentTable+ConfigPanel layout, useGenerationStream
provides:
  - "GET /projects list endpoint (id/filename/status/created_at, newest first) over the existing Project table, no schema change"
  - "ProjectListScreen: card rows with filename/date/status badge/Open action, persistent New Project CTA, skeleton loading, empty-state + load-failure copy"
  - "App.tsx routes ProjectListScreen as the root/landing screen when no active projectId; ready-view header gains a persistent '← Projects' back link"
affects: [03-05]

tech-stack:
  added: []
  patterns:
    - "Project-status badge (analyzing/ready/error) mirrors SegmentTable's STATUS_BADGE prescriptive icon/color vocabulary at project granularity — no new semantic colors invented"
    - "In-memory StaticPool sqlite engine swapped in via monkeypatch for a genuinely-empty-DB test, since the shared projects.db persists rows across the whole test module"

key-files:
  created:
    - frontend/src/components/ProjectListScreen.tsx
  modified:
    - backend/app/main.py
    - backend/tests/test_generation.py
    - frontend/src/api/client.ts
    - frontend/src/App.tsx

key-decisions:
  - "Project already had a created_at column (added in plan 03-01, ahead of RESEARCH.md Pattern 6's assumption it was still missing) — no schema change needed for this plan, confirming 03-01-SUMMARY's claim that Phase 3's columns were fully front-loaded"
  - "Landing area with no active project is a separate in-memory LandingView toggle ('list' | 'upload'), not folded into the localStorage-backed projectId state — a mid-upload refresh should land back on the project list, not resume the upload form"
  - "test_list_projects_empty swaps app.main.engine for a throwaway StaticPool in-memory sqlite engine (monkeypatch) rather than asserting against the real shared projects.db, which already has rows from earlier tests in the same module/process"

patterns-established: []

requirements-completed: [PERS-01, PERS-02]

coverage:
  - id: D1
    description: "GET /projects lists saved projects (filename, date, status) ordered newest-first, over the existing Project table with no schema change"
    requirement: "PERS-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_list_projects_returns_saved_projects"
        status: pass
      - kind: unit
        ref: "backend/tests/test_generation.py#test_list_projects_empty"
        status: pass
    human_judgment: false
  - id: D2
    description: "ProjectListScreen is the app's landing screen; opening a project sets the active projectId and resumes exactly where it was left; New Project starts the upload flow; empty list shows the 'No projects yet' empty state"
    requirement: "PERS-02"
    verification:
      - kind: automated_ui
        ref: "frontend build (tsc -b && vite build) + grep confirms listProjects() called in ProjectListScreen and ProjectListScreen rendered in App.tsx"
        status: pass
    human_judgment: true
    rationale: "Build success and grep confirm the screen compiles and is wired as the landing route, but the actual card layout, status badges, empty-state/load-failure copy, and the reopen-then-resume flow were not exercised in a live browser this session — no UI checkpoint was reached for this autonomous task."
  - id: D3
    description: "Auto-save holds by construction — every segment/character edit already commits immediately via PATCH endpoints, no separate Save mechanism needed"
    requirement: "PERS-01"
    verification: []
    human_judgment: true
    rationale: "This is a confirmation of prior phases' existing PATCH-on-blur behavior (03-01/03-02), not new code to unit-test in this plan — documented via an inline comment in App.tsx per the plan's explicit instruction; no new automated coverage was added because there is no new behavior to cover."

duration: ~10min
completed: 2026-07-12
status: complete
---

# Phase 3 Plan 4: Project List / Reopen Flow Summary

**GET /projects list endpoint plus a new ProjectListScreen landing route in App.tsx — the app now opens on a list of saved projects (filename/date/status) instead of straight into the upload form, and PERS-01 auto-save-by-construction is confirmed rather than rebuilt.**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2 (both auto)
- **Files modified:** 5 (1 new: `ProjectListScreen.tsx`)

## Accomplishments
- `GET /projects`: a thin read-only list endpoint (id/filename/status/created_at, newest first) over the existing `Project` table — `created_at` already existed from plan 03-01's schema front-load, so no migration was needed here.
- `ProjectListScreen`: fetches the list on mount, renders each project as a card row (filename, formatted date, status badge) with an Open action, a persistent "New Project" CTA, a skeleton loading state, and the UI-SPEC's verbatim empty-state ("No projects yet" / "Upload a book to create your first project.") and load-failure ("Couldn't load your projects." / "Check the connection and try again.") copy.
- `App.tsx`: the project list is now the root/landing screen whenever there's no active `projectId`; a new in-memory `LandingView` toggle ('list'/'upload') routes "New Project" into the existing upload flow without touching localStorage until a project is actually created; the ready-view header (table/wizard) gained a persistent "← Projects" link that clears the active project and returns to the list.
- PERS-01 (auto-save) confirmed by construction, not rebuilt: every character/segment edit already commits on blur via the existing PATCH endpoints (03-01/03-02) — a comment in `App.tsx` documents this instead of adding a new save mechanism.

## Task Commits

1. **Task 1: Failing test + GET /projects list endpoint** - `5b935ad` (feat, RED+GREEN in one commit per plan's task grouping)
2. **Task 2: ProjectListScreen + App routing landing on the list** - `ce77197` (feat)

## Files Created/Modified
- `backend/app/main.py` - `GET /projects` (`list_projects`), inserted before `GET /projects/{project_id}`
- `backend/tests/test_generation.py` - `test_list_projects_returns_saved_projects`, `test_list_projects_empty` (isolated in-memory engine)
- `frontend/src/api/client.ts` - `listProjects()`, `ProjectSummary` type
- `frontend/src/components/ProjectListScreen.tsx` - new landing screen
- `frontend/src/App.tsx` - `LandingView` toggle, `ProjectListScreen` as root, "← Projects" header link, PERS-01 comment

## Decisions Made
- No schema change was needed — `Project.created_at` already existed from plan 03-01, ahead of what RESEARCH.md's Pattern 6 assumed when it was written.
- `test_list_projects_empty` swaps `app.main.engine` for a throwaway `StaticPool` in-memory sqlite engine via `monkeypatch`, since the real `projects.db` is shared and persistent across the whole test module (no per-test DB reset exists in this project's test infra) — the only way to genuinely exercise an empty-list response.
- Landing-with-no-project routing uses a separate in-memory `LandingView` state rather than overloading the existing localStorage-backed `projectId`, so a mid-upload page refresh correctly lands back on the project list instead of resuming a half-filled upload form.

## Deviations from Plan
None - plan executed as written (RESEARCH.md's note that `created_at` might still be missing turned out to be moot, exactly as the note itself anticipated: "If the planner instead infers 'date' from... this assumption is moot").

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
PERS-01/PERS-02 are both satisfied: the app now lands on a real project list, reopening restores exact state via the existing `GET /projects/{id}` payload, and auto-save was confirmed rather than needing new work. Plan 03-05 (deployment) has no new schema or endpoint dependency from this plan.

---
*Phase: 03-editable-table-full-generation-pipeline-persistence-deployment*
*Completed: 2026-07-12*

## Self-Check: PASSED

All created/modified files verified present on disk; both task commits (`5b935ad`, `ce77197`) verified present in git log.
