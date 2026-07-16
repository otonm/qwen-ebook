---
phase: 07
slug: unified-generate-stop-play-button-trimmed-segment-table
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-16
---

# Phase 07 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| browser → backend HTTP | Buttons dispatch to already-existing, already-validated generate/cancel/download endpoints; no new endpoints in this phase | Server-issued project/character/segment IDs, generation triggers, audio bytes (single-user Tailscale boundary) |
| operator → running app | Plan 05 was manual verification only; no code change | None |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-07-01 | Tampering | outputUrl / downloadUrl string builder | low | accept | Pure template over server-issued project.id, no user free-text; Tailscale boundary | closed |
| T-07-02 | Information Disclosure | joined-output audio route | low | accept | Reuses Phase-6-vetted /projects/{id}/download route; no new data exposed | closed |
| T-07-SC | Tampering | npm/pip/cargo installs | n/a | accept | Phase adds zero new packages — no supply-chain surface | closed |
| T-07-03 | Tampering | SegmentTable controls cell | low | accept | Re-routes existing validated generate/cancel calls through one button; no new input or endpoint | closed |
| T-07-04 | Information Disclosure | deleted Status column | low | accept | Removing a read-only badge exposes no data | closed |
| T-07-05 | Tampering | batch status derivation | medium | mitigate | isSelfRunning-before-hasOutput precedence enforced (ConfigPanel.tsx:305-311 ternary: isCancelling → isSelfRunning → hasOutput → idle); human-verified via UAT test 7 (regenerate-with-existing-output shows red Stop, never stale green Play) | closed |
| T-07-06 | Information Disclosure | joined-output audio element | low | accept | Reuses Phase-6-vetted download route; Tailscale access boundary | closed |
| T-07-07 | Denial of Service | CharacterCard Stop / double-trigger | low | mitigate | CharacterCard swapped wholesale to shared useGenerateStopPlay hook (CharacterCard.tsx:86) + GenerateStopPlayButton, which disables itself while status === "stopping" (GenerateStopPlayButton.tsx:61) — double-cancel/double-POST race guarded | closed |
| T-07-08 | Tampering | CastWizard layout class | low | accept | Pure presentational Tailwind class change (xl:items-start); no data or endpoint surface | closed |
| T-07-09 | Repudiation | verification sign-off | low | accept | Sign-off recorded in 07-05-SUMMARY.md; single-user tool, no further audit requirement | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-07-01 | T-07-01 | Server-issued IDs only; single trusted user behind Tailscale | plan author (07-01-PLAN.md) | 2026-07-16 |
| R-07-02 | T-07-02 | Existing vetted route, no new data path | plan author (07-01-PLAN.md) | 2026-07-16 |
| R-07-03 | T-07-SC | Zero new dependencies in phase | plan author (07-01-PLAN.md) | 2026-07-16 |
| R-07-04 | T-07-03 | No new input or endpoint surface | plan author (07-02-PLAN.md) | 2026-07-16 |
| R-07-05 | T-07-04 | Read-only badge removal, no data exposure | plan author (07-02-PLAN.md) | 2026-07-16 |
| R-07-06 | T-07-06 | Existing vetted route, Tailscale boundary | plan author (07-03-PLAN.md) | 2026-07-16 |
| R-07-07 | T-07-08 | Presentational class change only | plan author (07-04-PLAN.md) | 2026-07-16 |
| R-07-08 | T-07-09 | Single-user tool; SUMMARY sign-off suffices | plan author (07-05-PLAN.md) | 2026-07-16 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-16 | 10 | 10 | 0 | Claude (/gsd-secure-phase, L1 grep-depth + UAT evidence) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-16
