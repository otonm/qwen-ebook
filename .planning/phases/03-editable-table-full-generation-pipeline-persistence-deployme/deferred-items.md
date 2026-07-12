# Deferred Items — Phase 03 execution

Out-of-scope discoveries logged during plan 03-05 execution (not fixed, per
deviation-rules scope boundary — these belong to Phase 2, not this plan).

## REQUIREMENTS.md traceability gap for Phase 2

While marking Phase 3's TBL-01/02/04, GEN-02/03/05, CFG-01/02/03, DEPL-02
requirements complete during 03-05's phase wrap-up, found that Phase 2's
requirements (ING-02, CAST-01, CAST-02, CAST-03, WIZ-01, WIZ-02, WIZ-03,
WIZ-04, WIZ-05) are all still marked "Pending" in both the checkbox list and
the Traceability table, despite Phase 2 being marked "Complete" in
ROADMAP.md/STATE.md (completed 2026-07-10) and each Phase 2 plan's SUMMARY.md
declaring its requirements complete in `requirements-completed:` frontmatter.

Same root cause as the Phase 3 gap fixed in this plan's execution: an earlier
executor run did not call `gsd_run query requirements mark-complete` for
those requirement IDs. Not fixed here because it is unrelated to plan 03-05's
files/scope (deploy/, README.md) — flagging for a follow-up quick task:

```bash
node <gsd-tools>/bin/gsd-tools.cjs requirements mark-complete \
  ING-02 CAST-01 CAST-02 CAST-03 WIZ-01 WIZ-02 WIZ-03 WIZ-04 WIZ-05
```
