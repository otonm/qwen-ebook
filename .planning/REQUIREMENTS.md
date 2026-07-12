# Requirements: Qwen Ebook Narrator

**Defined:** 2026-07-09
**Core Value:** Given a long text, produce a natural-sounding, multi-character narrated audio file with minimal manual editing — the LLM does the heavy lifting of casting and segmenting, the user just fine-tunes.

## v1 Requirements

### Ingestion

- [x] **ING-01**: User can upload a plain text (.txt) file as the source for a new project
- [ ] **ING-02**: User can upload an EPUB (.epub) file as the source for a new project, with chapter/reading-order text extracted and markup/footnotes stripped
- [x] **ING-03**: Long source texts are chunked on natural structural boundaries (chapter/paragraph) for LLM analysis rather than arbitrary token counts

### Cast & Analysis

- [ ] **CAST-01**: Uploaded text is analyzed by an LLM accessed via OpenRouter (default model `x-ai/grok-4.3`), which detects the cast of speaking characters (including the narrator) and infers descriptive traits (age, gender, personality) from context
- [ ] **CAST-02**: For long texts requiring multi-chunk analysis, the running resolved cast list is re-supplied as context to each subsequent chunk to minimize duplicate/renamed characters
- [ ] **CAST-03**: Text is split into ordered narration/dialogue segments, each tagged with a suggested speaker and per-segment voice instructions (e.g. "narrates in a soothing voice", "gaining confidence")

### Cast Review Wizard

- [ ] **WIZ-01**: User can review the LLM-suggested cast of characters in a wizard before segments are generated
- [ ] **WIZ-02**: User can rename, merge, or edit the description of any suggested character (to fix cross-chunk duplicate/renamed characters)
- [ ] **WIZ-03**: User can assign a voice to each character, choosing between a preset voice (e.g. male/female narrator, stock character voices) or free-text voice instructions derived from the character's inferred description
- [ ] **WIZ-04**: Each character has a play/pause preview button that plays a short neutral intro line in that character's assigned voice (e.g. "Hi, my name is ___ and I am a ___")
- [ ] **WIZ-05**: Character voice previews are pre-generated automatically as soon as a character's voice is assigned in the wizard, so playback is instant rather than generated on click

### Segment Table

- [x] **TBL-01**: Main UI shows an editable table (~70% width) with three columns: Narrator (dropdown of defined characters), Voice Instructions (free text), Text (free text)
- [x] **TBL-02**: User can edit the Narrator, Voice Instructions, or Text of any row
- [x] **TBL-03**: User can select multiple rows and bulk-reassign their Narrator/voice in one action
- [x] **TBL-04**: Each row has a generate + play/pause button that synthesizes and previews that row's audio individually, on demand

### Generation & Audio

- [ ] **GEN-01**: Each table row's audio segment is generated via self-hosted Qwen TTS running on the AMD GPU host
- [x] **GEN-02**: Each segment's audio is cached and keyed by a content hash of (character, voice instructions, text, voice/model version); unchanged segments are not regenerated
- [x] **GEN-03**: Editing a row's Narrator, Voice Instructions, or Text after generation invalidates only that segment (clears its stale audio, marks it pending); the user triggers regeneration manually via the per-row or Generate All controls, which rejoins the full file
- [x] **GEN-04**: Generated segments are joined in table order into a single output audio file (MP3 or WAV)
- [x] **GEN-05**: Per-segment generation status (pending/queued/generating/complete/error) is persisted so a batch generation run can resume after an interruption or crash

### Persistence

- [x] **PERS-01**: Projects (source text, character cast with voice assignments, segment table, cached per-segment audio, joined output) are saved automatically as the user works
- [x] **PERS-02**: User can reopen a previously saved project and continue editing/generating from where they left off — single user, no accounts

### Config & Progress

- [x] **CFG-01**: Right-side panel (~30% width) holds configuration: input file, TTS model, output format, output file
- [x] **CFG-02**: Right-side panel shows the list of defined characters with their voice preview controls (see WIZ-04/WIZ-05)
- [x] **CFG-03**: Right-side panel shows live progress of the current conversion (per-segment and overall)

### Deployment

- [ ] **DEPL-01**: App is deployed as Podman container(s) on a VM with an AMD GPU (RX 9070 XT, 16GB VRAM), with the TTS service isolated in its own GPU-scoped container
- [x] **DEPL-02**: App is served over the user's Tailscale network only, with no public exposure and no additional auth layer

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhancements

- **ENH-01**: Cost/usage visibility for the LLM (OpenRouter) analysis step — estimated/actual token spend per project
- **ENH-02**: "Last good" segment audio fallback retained if a regenerate produces an unusable result

### Output

- **OUT-01**: Audiobook-specific output (M4B container, chapter markers/metadata)

### Voice

- **VOICE-01**: Voice cloning from user-recorded/personal audio samples

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Multi-user accounts / login / RBAC | Single-user personal tool; Tailscale network membership is the access control |
| Cloud sync / multi-device sync | Already reachable from any device via the same Tailscale URL; no separate sync layer needed |
| Native mobile app | Creation workflow is desktop/table-editing-oriented; listening happens via the exported audio file in any player |
| Real-time audio streaming/preview during generation | Batch generate-then-download flow; per-row preview (WIZ-04, TBL-04) already covers "hear it before committing" |
| PDF input | Only .txt and .epub for v1 |
| SSML / fine-grained audio timeline editor | Free-text Voice Instructions + full segment regeneration is an adequate substitute at personal-use quality bar |
| Full git-like version history / diff of edits | Disproportionate for a personal tool; regenerate-on-edit is sufficient |
| Usage analytics / telemetry dashboards | Single user, no audience for this data |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ING-01 | Phase 1 | Complete |
| ING-03 | Phase 1 | Complete |
| GEN-01 | Phase 1 | Pending (verified via override — see 01-VERIFICATION.md; real GPU synthesis deferred to production RX 9070 XT hardware) |
| GEN-04 | Phase 1 | Complete |
| DEPL-01 | Phase 1 | Pending (verified via override — see 01-VERIFICATION.md; real GPU VM deployment deferred to production RX 9070 XT hardware) |
| ING-02 | Phase 2 | Pending |
| CAST-01 | Phase 2 | Pending |
| CAST-02 | Phase 2 | Pending |
| CAST-03 | Phase 2 | Pending |
| WIZ-01 | Phase 2 | Pending |
| WIZ-02 | Phase 2 | Pending |
| WIZ-03 | Phase 2 | Pending |
| WIZ-04 | Phase 2 | Pending |
| WIZ-05 | Phase 2 | Pending |
| TBL-01 | Phase 3 | Complete |
| TBL-02 | Phase 3 | Complete |
| TBL-03 | Phase 3 | Complete |
| TBL-04 | Phase 3 | Complete |
| GEN-02 | Phase 3 | Complete |
| GEN-03 | Phase 3 | Complete |
| GEN-05 | Phase 3 | Complete |
| PERS-01 | Phase 3 | Complete |
| PERS-02 | Phase 3 | Complete |
| CFG-01 | Phase 3 | Complete |
| CFG-02 | Phase 3 | Complete |
| CFG-03 | Phase 3 | Complete |
| DEPL-02 | Phase 3 | Complete |

**Coverage:**

- v1 requirements: 27 total
- Mapped to phases: 27
- Unmapped: 0 ✓

---
*Requirements defined: 2026-07-09*
*Last updated: 2026-07-09 after roadmap creation (3 phases, 100% coverage)*
