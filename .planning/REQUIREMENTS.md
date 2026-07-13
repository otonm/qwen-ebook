# Requirements: Qwen Ebook Narrator

**Defined:** 2026-07-13
**Core Value:** Given a long text, produce a natural-sounding, multi-character narrated audio file with minimal manual editing — the LLM does the heavy lifting of casting and segmenting, the user just fine-tunes.

## v1.1 Requirements

Requirements for the "Generation UX & Config Rework" milestone. Each maps to roadmap phases.

### Generation Control (GEN)

- [ ] **GEN-06**: User can stop a currently-generating segment's audio and have the in-flight GPU inference interrupted immediately, not merely queued to finish
- [ ] **GEN-07**: User can stop a currently-generating character voice preview and have it interrupted immediately
- [ ] **GEN-08**: User can stop a running "Generate All" batch and have the in-flight segment's generation interrupted immediately, not just prevented from starting the next one
- [ ] **GEN-09**: Each per-row segment audio control is a single button that shows yellow "Generate Preview" when idle or stale, red "Stop Generation" while generating, and green "Play" once audio exists
- [ ] **GEN-10**: Each character preview control follows the same yellow/red/green generate/stop/play pattern as segments
- [ ] **GEN-11**: The "Generate All" control follows the same yellow/red/green generate/stop/play pattern; once the joined output file is ready it additionally shows a green "Play" (in-browser preview of the joined file)
- [ ] **GEN-12**: Any edit that invalidates a segment's or character's cached audio visibly reverts its control back to the yellow "Generate Preview" state (single visual source of truth — no separate status indicator)

### Config Panel (CFG)

- [ ] **CFG-04**: User can choose between two Qwen TTS model sizes per project — 1.7B ("higher quality") and 0.6B ("faster") — loaded on demand (only one resident in VRAM at a time)
- [ ] **CFG-05**: When the 0.6B model is selected, the UI warns the user that free-text voice-instruction steering is not supported by that checkpoint
- [ ] **CFG-06**: User can choose the output audio format: FLAC, MP3, or Opus (WAV is dropped as an option)
- [ ] **CFG-07**: User can set a custom output filename before generating the final file
- [ ] **CFG-08**: User can download the finished, joined audio file via a blue "Download" button once generation completes

### Segment Table (TBL)

- [ ] **TBL-05**: The segment table shows exactly 3 editable columns — Narrator, Voice Instructions, Text — with the separate Status badge column removed (state is now conveyed by the GEN-09 button alone)

## Out of Scope

Explicitly excluded from v1.1. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Hard-kill of GPU work beyond what `StoppingCriteria` achieves (e.g. process-level force-kill) | Research (ARCHITECTURE.md/PITFALLS.md) flags this as a materially harder backend problem; `StoppingCriteria`-based interruption is the scoped mechanism for GEN-06/07/08 |
| Auto-download or auto-play on generation completion | Anti-feature — regresses the project's established "user-triggered, never auto-fire" precedent (GEN-03) |
| A 4th "queued" button state | Milestone explicitly scopes to 3 states (yellow/red/green); queued folds into yellow |
| A 3rd TTS model size or arbitrary model list | Only the 1.7B/0.6B CustomVoice pair is in scope |
| WAV as an output format | Explicitly dropped per user decision in favor of FLAC/MP3/Opus |

## Traceability

Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| GEN-06 | TBD | Pending |
| GEN-07 | TBD | Pending |
| GEN-08 | TBD | Pending |
| GEN-09 | TBD | Pending |
| GEN-10 | TBD | Pending |
| GEN-11 | TBD | Pending |
| GEN-12 | TBD | Pending |
| CFG-04 | TBD | Pending |
| CFG-05 | TBD | Pending |
| CFG-06 | TBD | Pending |
| CFG-07 | TBD | Pending |
| CFG-08 | TBD | Pending |
| TBL-05 | TBD | Pending |

**Coverage:**
- v1.1 requirements: 13 total
- Mapped to phases: 0 (pending roadmap)
- Unmapped: 13 ⚠️ (resolved by roadmapper)

---
*Requirements defined: 2026-07-13*
*Last updated: 2026-07-13 after initial v1.1 definition*
