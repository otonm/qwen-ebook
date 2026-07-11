# Phase 3: Editable Table, Full Generation Pipeline, Persistence & Deployment - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-11
**Phase:** 3-editable-table-full-generation-pipeline-persistence-deployment
**Areas discussed:** Real-hardware validation, Project list, Bulk row selection, Regeneration trigger

---

## Real-hardware validation

Surfaced before the question: the production RX 9070 XT VM (assumed by `STATE.md`/`PROJECT.md` to not exist yet) is actually the exact machine this session has been running against, and Phase 1's D-09 GPU re-verification checklist was already closed out on it (commit `1ce34aa`, 2026-07-10) — real non-silent WAV confirmed end-to-end.

| Option | Description | Selected |
|--------|-------------|----------|
| Re-run + validate early, build against it | Start the phase by bringing the real pod up (`bash deploy/run-local.sh`), confirm it still works, then develop/test the generation pipeline against real audio where practical | ✓ |
| Mock-first, real-hardware check at the end | Build the whole pipeline against `TTS_BACKEND=mock`, only bring up the real pod for a final check | |
| Don't touch deployment/GPU this phase | Treat DEPL-02/real-GPU as a separate follow-up outside Phase 3's plan | |

**User's choice:** "option one and update your documentation/instructions to properly mirror the current actuall state of the project"
**Notes:** User also explicitly asked for the stale "VM doesn't exist yet" documentation to be corrected — done in this session: `STATE.md` Blockers/Concerns and `PROJECT.md` Active requirements + Key Decisions table updated to reflect the real, already-verified GPU/VM state.

---

## Project list

| Option | Description | Selected |
|--------|-------------|----------|
| Add a simple project list screen | A screen listing saved projects (filename, date, status) to pick from and reopen | ✓ |
| Keep single-slot resume only | No project list — localStorage keeps remembering just the most recent project, same as Phase 2 | |

**User's choice:** "Add a simple project list screen (Recommended)"
**Notes:** None given beyond selecting the recommended option.

---

## Bulk row selection

| Option | Description | Selected |
|--------|-------------|----------|
| Checkbox column + toolbar action | Checkbox per row + header "select all," action bar appears above the table when rows are selected | ✓ |
| Shift/ctrl-click range select | Spreadsheet-style click + shift-click / ctrl-click, then right-click or toolbar action | |

**User's choice:** "Checkbox column + toolbar action (Recommended)"
**Notes:** None given beyond selecting the recommended option.

---

## Regeneration trigger

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-regenerate on blur | Matches Phase 2's autosave-on-blur pattern — edit a cell, click away, that row's audio regenerates automatically in the background | ✓ |
| Mark stale, regenerate on demand | Editing just flags the cached audio as stale; user clicks the row's generate button to actually regenerate | |

**User's choice:** "Auto-regenerate on blur (Recommended)"
**Notes:** None given beyond selecting the recommended option.

---

## Claude's Discretion

- Project list screen's navigation placement/entry point.
- Batch-vs-per-row-edit interleaving behavior during concurrent generation — flagged for real-hardware testing given it's one of the untested-against-real-GPU gaps.
- Exact content-hash implementation and what "voice/model version" concretely means with only one TTS model in scope.
- Exact SSE/polling event schema for live progress (CFG-03).
- Internal schema additions for generation status + cache key/path storage (deferred by Phase 2's D-02 to this phase).
- CFG-01's "model" field: real dropdown vs. fixed display value.

## Deferred Ideas

- VoiceDesign custom voice generation — already deferred past Phase 2 (D-17), not revisited here.
- Full git-like edit history / diff — already out of scope per REQUIREMENTS.md, not revisited here.
