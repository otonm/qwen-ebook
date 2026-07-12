---
phase: 03-editable-table-full-generation-pipeline-persistence-deployment
plan: 02
subsystem: ui
tags: [fastapi, sqlmodel, tanstack-table, radix-ui, shadcn, react]

requires:
  - phase: 03-01
    provides: Segment generation_version/character_id fields, editable SegmentTable, patchSegment/generateSegment client wrappers, merge_character ownership-validation precedent
provides:
  - POST /segments/bulk-reassign (BulkReassignRequest, cross-project ownership guard)
  - bulkReassignSegments() client wrapper
  - Checkbox row selection (header select-all + per-row) on SegmentTable
  - 48px bulk-action toolbar reassigning narrator across selected rows in one request
affects: [03-03, 03-04, 03-05]

tech-stack:
  added: ["shadcn checkbox primitive (radix-ui)"]
  patterns:
    - "Radix Checkbox onCheckedChange passes a boolean/'indeterminate', not a DOM event — wire via table.toggleAllRowsSelected(!!value)/row.toggleSelected(!!value), not the getToggleXSelectedHandler() event-shaped handlers"
    - "Bulk endpoints reject the whole request on any cross-project id (merge_character's project_id-match discipline, applied to a list instead of a single id)"

key-files:
  created:
    - frontend/src/components/ui/checkbox.tsx
  modified:
    - backend/app/main.py
    - backend/tests/test_generation.py
    - frontend/src/api/client.ts
    - frontend/src/components/SegmentTable.tsx

key-decisions:
  - "Bulk reassign only bumps generation_version to mark rows stale — it does not auto-trigger regeneration (unlike patch_segment). Batch regen is plan 03-03's scope per the plan's explicit instruction."
  - "Toolbar's 'refresh the table' is a local optimistic update (each selected segment's character_id/character_name patched via the existing onSegmentChange callback) rather than a full project refetch — reuses the prop ProjectScreen already wires up, no new prop threading needed."

patterns-established:
  - "Pattern 2 (checkbox row selection): getRowId: (s) => s.id + rowSelection state + a toolbar gated on selectedIds.length > 0"

requirements-completed: [TBL-03]

coverage:
  - id: D1
    description: "POST /segments/bulk-reassign reassigns all listed segments' narrator in one request and bumps generation_version on each"
    requirement: "TBL-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_bulk_reassign_updates_all_rows"
        status: pass
      - kind: unit
        ref: "backend/tests/test_generation.py#test_bulk_reassign_bumps_generation_version"
        status: pass
    human_judgment: false
  - id: D2
    description: "Bulk-reassign rejects a request whose target character belongs to a different project than the segments, changing nothing"
    requirement: "TBL-03"
    verification:
      - kind: unit
        ref: "backend/tests/test_generation.py#test_bulk_reassign_rejects_cross_project"
        status: pass
    human_judgment: false
  - id: D3
    description: "User can check per-row/header-select-all checkboxes; a toolbar appears above the table with 1+ rows selected and reassigns the selected rows' narrator via a confirm button"
    requirement: "TBL-03"
    verification:
      - kind: automated_ui
        ref: "frontend build (tsc -b && vite build) + grep confirms getRowId and bulkReassignSegments wired in SegmentTable.tsx/client.ts"
        status: pass
      - kind: manual_procedural
        ref: "Visual/interactive check of checkbox column + toolbar appearance/disappearance in a running dev server"
        status: unknown
    human_judgment: true
    rationale: "Build success and grep confirm the wiring compiles and calls the right functions, but actual toolbar appearance/disappearance and reassignment against a live table were not exercised in a browser this session — no UI checkpoint was reached (plan is fully autonomous, no checkpoint task)."

duration: ~15min
completed: 2026-07-12
status: complete
---

# Phase 3 Plan 2: Bulk Row Selection + Narrator Reassignment Summary

**Checkbox row selection (header select-all + per-row) with a 48px bulk-action toolbar that reassigns narrator across selected segments in one validated POST /segments/bulk-reassign request, rejecting cross-project tampering.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-12T11:44:00+02:00
- **Completed:** 2026-07-12T11:59:00+02:00
- **Tasks:** 2
- **Files modified:** 4 (+1 new)

## Accomplishments
- `POST /segments/bulk-reassign`: validates every segment id's `project_id` against the target character's `project_id` before applying anything (mirrors `merge_character`'s ownership discipline), reassigns `character_id`, and bumps `generation_version` per row to mark cached audio stale.
- `SegmentTable` gained a leading checkbox column (header select-all + per-row) using `getRowId: (s) => s.id` so selection survives row-order changes, plus a 48px toolbar that appears only when 1+ rows are selected.
- Toolbar confirm action calls `bulkReassignSegments`, then locally updates each affected row (character_id/character_name) via the existing `onSegmentChange` callback and clears selection — non-destructive, no confirmation dialog, matching the UI-SPEC copywriting contract.

## Task Commits

1. **Task 1: Failing test + bulk-reassign endpoint with cross-project ownership validation** - `1498927` (test, RED) then `e4bc8bd` (feat, GREEN)
2. **Task 2: Checkbox column + bulk-action toolbar in SegmentTable** - `bfb7595` (feat)

**Plan metadata:** pending (this commit)

## Files Created/Modified
- `backend/app/main.py` - `BulkReassignRequest`, `POST /segments/bulk-reassign`
- `backend/tests/test_generation.py` - three bulk-reassign tests (updates all rows, bumps version, rejects cross-project)
- `frontend/src/api/client.ts` - `bulkReassignSegments()` wrapper
- `frontend/src/components/ui/checkbox.tsx` - shadcn primitive (new, `npx shadcn add checkbox`)
- `frontend/src/components/SegmentTable.tsx` - select column, `rowSelection` state, `BulkReassignToolbar`

## Decisions Made
- Bulk reassign deliberately does not fire an auto-regenerate background task the way `patch_segment` does — it only bumps `generation_version` to mark rows stale, per the plan's explicit "do NOT auto-synthesize here" instruction (batch regen is 03-03's job).
- The toolbar's "refresh" is a local optimistic update through the existing `onSegmentChange` prop rather than a new full-refetch prop threaded through `ProjectScreen` — smallest change that satisfies the requirement without growing the component API.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Radix Checkbox `onCheckedChange` callback signature mismatch with research pattern's cited handlers**
- **Found during:** Task 2 (checkbox column implementation)
- **Issue:** The plan's `<read_first>` research pattern (03-RESEARCH.md Pattern 2) cites `onCheckedChange={table.getToggleAllRowsSelectedHandler()}`, which is TanStack's native-`<input type="checkbox">`-shaped handler (reads `event.target.checked`). shadcn's `Checkbox` wraps Radix UI's `CheckboxPrimitive.Root`, whose `onCheckedChange` prop passes a `boolean | "indeterminate"` value directly, not a change event — using the cited handler as-is would silently no-op or throw on `event.target` access.
- **Fix:** Wired both the header and per-row checkboxes via `onCheckedChange={(value) => table.toggleAllRowsSelected(!!value)}` / `onCheckedChange={(value) => row.toggleSelected(!!value)}` instead — functionally identical selection behavior, adapted to Radix's boolean-based callback.
- **Files modified:** frontend/src/components/SegmentTable.tsx
- **Verification:** `npm run build` succeeds; selection state (`rowSelection`) is TanStack-table-managed either way, so the toggle-method approach produces the same `getRowId`-keyed selection map the toolbar reads.
- **Committed in:** `bfb7595` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary correctness fix — the plan's cited pattern targets a different checkbox primitive shape than what UI-SPEC mandated (shadcn/Radix `checkbox`). No scope creep; same TBL-03 behavior delivered.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
`POST /segments/bulk-reassign` and the checkbox/toolbar UI are in place and build/test-clean. The toolbar's confirm action and appearance/disappearance were not exercised in a live browser this session (D3 above) — worth a quick visual pass before/at Phase 3 sign-off, but nothing blocks 03-03 (batch generation), which can build on `generation_version` bumps from this endpoint the same way it already does from `patch_segment`.

---
*Phase: 03-editable-table-full-generation-pipeline-persistence-deployment*
*Completed: 2026-07-12*

## Self-Check: PASSED

All created/modified files verified present on disk; all three task commits (`1498927`, `e4bc8bd`, `bfb7595`) verified present in git log.
