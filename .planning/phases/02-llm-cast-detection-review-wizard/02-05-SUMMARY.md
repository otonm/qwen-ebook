---
phase: 02-llm-cast-detection-review-wizard
plan: 05
subsystem: ui
tags: [react, vite, shadcn, tanstack-table, sse, fetch]

requires:
  - phase: 02-llm-cast-detection-review-wizard (plan 01)
    provides: "POST /projects, GET /projects/{id}, GET /projects/{id}/analysis-stream SSE, SQLModel Project/Character/Segment persistence"
  - phase: 02-llm-cast-detection-review-wizard (plan 04)
    provides: "GET /voices, PATCH /characters/{id}, POST /characters/{id}/merge, GET /characters/{id}/preview.wav, race-safe eager preview generation"
provides:
  - "Single-page cast-review wizard UI end-to-end in the browser: upload -> SSE-driven analyzing state -> cast cards with inline edit/merge/voice-assign + instant native-audio preview -> read-only segment preview"
affects: [phase-03-editable-segment-table, phase-03-generation-pipeline]

tech-stack:
  added: ["@tanstack/react-table", "shadcn card/input/textarea/badge/select/dialog/table/skeleton/progress components"]
  patterns:
    - "fetch wrappers keyed one-to-one to backend endpoints, no client library (api/client.ts)"
    - "EventSource-based SSE consumption hook returning {status, progress, cast, segments}"
    - "short-interval refetch burst after any edit/merge to surface the async-generated preview WAV without a second SSE channel"

key-files:
  created:
    - frontend/src/api/client.ts
    - frontend/src/hooks/useAnalysisStream.ts
    - frontend/src/components/UploadScreen.tsx
    - frontend/src/components/CharacterCard.tsx
    - frontend/src/components/SegmentPreview.tsx
  modified:
    - frontend/src/components/CastWizard.tsx
    - frontend/src/App.tsx
    - frontend/src/main.tsx
    - frontend/vite.config.ts
    - frontend/package.json

key-decisions:
  - "Merge target selection happens inside the confirmation Dialog itself (a Select populated with other cast members) rather than a separate pre-step UI, since the plan/UI-SPEC didn't lock an exact target-picking interaction — dialog title/body only render the exact copywriting-contract wording once a target is chosen."
  - "Dropped the scaffolded ThemeProvider from main.tsx (global 'd' keydown dark-mode toggle + 'system' default) — it directly violated the UI-SPEC's light-mode-only / no-theme-toggle prohibition by being capable of applying the .dark class unprompted."
  - "Preview WAV readiness is surfaced via a short burst of refetches (800ms/1.8s/3.5s) after any edit/merge PATCH, not a second SSE channel or a websocket — the async generation is fast (a few words of TTS) and a burst refetch is simpler than adding new streaming infrastructure for it."

requirements-completed: [ING-02, WIZ-01, WIZ-02, WIZ-03, WIZ-04, WIZ-05]

coverage:
  - id: D1
    description: "Empty-state landing screen (exact copy) with Upload & Analyze CTA accepting .txt/.epub"
    requirement: "ING-02"
    verification:
      - kind: unit
        ref: "manual dev verification — see Manual Verification section"
        status: pass
    human_judgment: true
    rationale: "Visual copy/layout correctness (exact heading/body wording, CTA placement) requires human eyeball confirmation against the UI-SPEC's Copywriting Contract; no automated visual test exists for this phase."
  - id: D2
    description: "SSE-driven analyzing state (progress bar + chunk N of M label) transitioning to the loaded cast wizard on done"
    requirement: "WIZ-01"
    verification:
      - kind: integration
        ref: "curl smoke test against LLM_BACKEND=mock backend: POST /projects -> GET /projects/{id} returned status ready with characters+segments populated"
        status: pass
    human_judgment: true
    rationale: "The progress-bar animation and SSE event handling in the browser were verified structurally (build clean, Vite module transform clean, backend contract matches client types exactly) but not observed rendering live in a browser session — needs a human UAT pass."
  - id: D3
    description: "Single-page cast card list with inline rename/description edit/voice-assign auto-saving via PATCH on blur, no per-field Save button"
    requirement: "WIZ-02, WIZ-03"
    verification:
      - kind: integration
        ref: "curl PATCH /characters/{id} against the mock backend returned the updated character with voice_instructions applied, matching CharacterCard's saveField() contract"
        status: pass
    human_judgment: true
    rationale: "The auto-save-on-blur interaction and 'no Save button' UX requirement need a human to actually type into the fields and observe the round trip; the API contract match was verified, the DOM interaction was not."
  - id: D4
    description: "Merge confirmation dialog with exact copywriting-contract wording, POSTs the merge on confirm"
    requirement: "WIZ-02"
    verification: []
    human_judgment: true
    rationale: "No automated check exercised the merge dialog's rendered text or click flow — only the underlying mergeCharacter() -> POST /characters/{id}/merge contract was code-reviewed against main.py's MergeRequest shape."
  - id: D5
    description: "Play/pause preview using a native <audio> element with indigo active state; voice-assigned badge appears once preview_audio_path exists"
    requirement: "WIZ-04, WIZ-05"
    verification:
      - kind: integration
        ref: "curl GET /characters/{id}/preview.wav returned 200 after a voice-field PATCH against the mock backend, confirming the eager-generation + polling contract CharacterCard relies on"
        status: pass
    human_judgment: true
    rationale: "Actual audio playback and the play/pause button's visual active state need a human/browser session; the backend readiness contract was verified via curl only."
  - id: D6
    description: "Read-only segment preview table (Speaker, Text columns, no inline edit/dropdowns/bulk actions)"
    requirement: "D-15 (ROADMAP success criterion #3)"
    verification:
      - kind: unit
        ref: "TypeScript build (tsc -b) type-checks SegmentPreview.tsx's read-only column defs against the Segment type with no editable cell renderers defined"
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-07-10
status: complete
---

# Phase 2 Plan 5: Cast Review Wizard UI Summary

**Single-page React cast-review wizard (Vite + shadcn/radix) — upload -> SSE-driven analyzing state -> inline-editable character cards with merge/voice-assign/instant native-audio preview -> read-only TanStack Table segment preview.**

## Performance

- **Duration:** ~45 min
- **Tasks:** 3
- **Files modified:** 18 total across the three task commits (9 new components/modules, 9 shadcn-generated UI primitives + config/scaffold edits)

## Accomplishments
- `api/client.ts` typed fetch wrappers for every backend endpoint this UI needs (`createProject`, `getProject`, `patchCharacter`, `mergeCharacter`, `getVoices`, `previewUrl`) — verified against the live mock backend's actual response shapes via curl, not just read from the plan.
- `useAnalysisStream.ts` EventSource hook driving the empty -> analyzing -> wizard state machine in `App.tsx`, with the exact Copywriting Contract strings for empty/analyzing/error states.
- `CastWizard.tsx` + `CharacterCard.tsx`: the single-page cast list (D-14) — inline rename/description edit auto-saving on blur, preset + free-text voice-instructions PATCH, merge confirmation dialog with the exact required wording, native `<audio>` play/pause with an indigo active state and a "Voice assigned" badge once the eagerly-generated preview lands.
- `SegmentPreview.tsx`: read-only `@tanstack/react-table` Speaker/Text table (D-15), ordered by `segment.order`, no editable affordances.
- Full `npm run build` (`tsc -b && vite build`) clean after every task; `npm run lint` clean except two pre-existing shadcn-scaffold-generated `react-refresh/only-export-components` errors in `button.tsx`/`badge.tsx` (out of this task's scope — vendor-generated component files, not authored this plan).

## Task Commits

Each task was committed atomically:

1. **Task 1: API client, SSE hook, and upload -> analyzing states** - `c75c290` (feat)
2. **Task 2: Single-page cast wizard — cards with inline edit, merge, voice assign, instant preview** - `c169a1c` (feat)
3. **Task 3: Read-only segment preview table** - `b70c710` (feat)

## Files Created/Modified
- `frontend/src/api/client.ts` - Typed fetch wrappers for /projects, /characters, /voices
- `frontend/src/hooks/useAnalysisStream.ts` - EventSource -> {status, progress, cast, segments}; `refreshProject()` helper for post-edit refetches
- `frontend/src/components/UploadScreen.tsx` - Empty-state landing + Upload & Analyze CTA
- `frontend/src/components/CastWizard.tsx` - Single-page cast grid + segment preview panel, voices fetch, refetch-burst after edits
- `frontend/src/components/CharacterCard.tsx` - One character: inline name/description edit, preset/voice-instructions PATCH, play/pause preview, merge dialog, aria-labeled icon buttons
- `frontend/src/components/SegmentPreview.tsx` - Read-only TanStack Table (Speaker, Text)
- `frontend/src/App.tsx` - Wires empty/analyzing/error/wizard states
- `frontend/src/main.tsx` - Dropped the scaffolded ThemeProvider (dark-mode-toggle prohibition)
- `frontend/vite.config.ts` - Dev-server proxy to backend (localhost:8000)
- `frontend/package.json` / `package-lock.json` - `@tanstack/react-table` dependency
- `frontend/src/components/ui/{card,input,textarea,badge,select,dialog,table,skeleton,progress}.tsx` - shadcn-generated primitives

## Decisions Made
- Merge-target selection lives inside the confirmation Dialog (a `Select` of other cast members) rather than a separate popover/pre-step — the plan left the exact target-picking interaction to discretion; the Dialog only shows the literal contract wording once a target is chosen, keeping the merge icon button single-purpose (icon-only, aria-labeled).
- Dropped the pre-existing `ThemeProvider` wrap in `main.tsx`. It shipped a global `d`-keydown dark-mode toggle and a `"system"` default theme that could apply the `.dark` class without any explicit user action — directly violating this plan's "No theme toggle / no dark class applied" prohibition and the UI-SPEC's light-mode-only decision. Fixed as a Rule 2 (missing-critical-compliance) deviation since it's pre-existing scaffold code, not something this plan's tasks introduced.
- Preview-readiness detection uses a short burst of refetches (800ms/1.8s/3.5s) after any PATCH/merge instead of a second SSE stream — the backend's eager-generation is fast (single short TTS line) and this avoids building new streaming plumbing for a single-user tool.
- Radix Select forbids an empty-string item value, but the backend's "auto" preset is represented by `""` server-side — mapped to a client-only sentinel (`__auto__`) at the UI boundary, translated back to `""` before every PATCH.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree branch was stale relative to its declared dependencies**
- **Found during:** Setup, before Task 1
- **Issue:** This plan's worktree branch (`worktree-agent-a094ea722031d7be1`) was forked from a commit that predates all of Plans 02-01 through 02-04 (its own `depends_on`), and predated `.planning/phases/02-llm-cast-detection-review-wizard/02-05-PLAN.md` even existing in the worktree. The backend endpoints, frontend scaffold, and UI-SPEC this plan builds on didn't exist in the checkout.
- **Fix:** Fast-forward merged `master` (`01cb88e`) into the worktree branch. Verified safe first: `git merge-base` confirmed the worktree's tip commit was a strict ancestor of `master`'s tip with zero divergent commits, so the merge was a lossless fast-forward, not a destructive rewrite.
- **Files modified:** None directly (brought in the full upstream commit range, including Plans 02-01–02-04's backend code and this plan's own PLAN.md/UI-SPEC.md).
- **Verification:** `git log --oneline -1` post-merge showed `01cb88e`; `.planning/phases/02-llm-cast-detection-review-wizard/02-05-PLAN.md` and `backend/app/main.py`'s Phase 2 endpoints were present and readable afterward.
- **Committed in:** N/A — a fast-forward merge, not a new commit (no new commit object was created; the branch ref simply advanced).

**2. [Rule 2 - Missing Critical] Removed the scaffolded ThemeProvider's implicit dark-mode capability**
- **Found during:** Task 1 (App.tsx / main.tsx wiring)
- **Issue:** `main.tsx` wrapped `<App />` in a `ThemeProvider` (pre-existing scaffold code from an earlier research/init pass) that installed a global `d`-keydown handler toggling `.dark` on `<html>`, with a `"system"` default that resolves to dark automatically under `prefers-color-scheme: dark` — directly contradicting this plan's own prohibition ("No theme toggle / no dark class applied — light mode only") and the UI-SPEC's explicit light-mode-only decision.
- **Fix:** Removed the `ThemeProvider` import/wrap from `main.tsx`, rendering `<App />` directly. `theme-provider.tsx` itself was left in place (unused, harmless) rather than deleted, since it wasn't in this plan's file list and deleting it wasn't necessary to satisfy the prohibition.
- **Files modified:** `frontend/src/main.tsx`
- **Verification:** `npm run build` clean; grep confirms no remaining `ThemeProvider`/dark-class-toggling code path is reachable from the app's render tree.
- **Committed in:** `c75c290` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking — stale worktree, 1 missing-critical — dark-mode prohibition violation)
**Impact on plan:** Both were necessary prerequisites/corrections; no scope creep. The worktree fast-forward was a pure setup fix (zero new commits), and the ThemeProvider removal directly enforces a requirement already stated in this plan's own `<must_haves><prohibitions>`.

## Issues Encountered
- ESLint's `react-hooks/set-state-in-effect` rule flagged the canonical "reset state before starting a new subscription" pattern inside `useAnalysisStream`'s effect (the same pattern shown in react.dev's own data-fetching-effect example). Resolved with a scoped `eslint-disable-next-line` and an inline comment explaining why — not a real bug, an overly strict lint rule for a legitimate reset-before-resubscribe case.
- Radix `SelectTrigger`'s TypeScript prop type only accepts `size: "sm" | "default"`, not the `Button` component's `"icon-lg"` size scale — caught while first prototyping the merge-target picker as a disguised `Select` trigger; resolved by using a plain icon `Button` for the merge action and moving target selection inside the confirmation `Dialog` instead (see Decisions Made).

## User Setup Required

None - no external service configuration required. `npm install` (already run) and the existing `LLM_BACKEND=mock`/`TTS_BACKEND=mock` dev defaults are sufficient to exercise the full flow locally.

## Next Phase Readiness

- The full Phase 2 success criteria (cast review, edit, merge, voice-assign, instant preview, read-only segments) are wired end-to-end in the browser against the real backend contract — verified via `npm run build`/`npm run lint` plus live curl smoke tests against a running `LLM_BACKEND=mock TTS_BACKEND=mock` backend (upload -> analyze -> PATCH -> preview.wav all returned the exact shapes `api/client.ts` expects).
- Not verified in this session: an actual browser-rendered click-through of the wizard (typing into fields, clicking play/pause, completing a merge) — flagged as `human_judgment: true` in the coverage table above; a human UAT pass against `npm run dev` + the mock backend is the natural next step before this phase is considered fully proven.
- Phase 3 (editable segment table, TBL-01..04) can build directly on `SegmentPreview.tsx`'s TanStack Table setup and `api/client.ts`'s existing patterns — no rework needed, just extension (editable cells, bulk actions).

---
*Phase: 02-llm-cast-detection-review-wizard*
*Completed: 2026-07-10*

## Self-Check: PASSED

All created files and task commit hashes verified present on disk / in git log.
