---
phase: 02
slug: llm-cast-detection-review-wizard
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-12
---

# Phase 02 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| browser/curl -> POST /projects | Untrusted uploaded file bytes (.txt/.epub) cross into the backend | Raw file bytes |
| backend -> SQLite | Persisted analysis data (single-process writer, cross-thread via asyncio background task) | Project/Character/Segment rows |
| backend -> OpenRouter (Grok) | Untrusted book text sent to an external LLM; output trusted only after schema validation | Book text out, structured JSON in |
| browser -> PATCH/merge/preview endpoints | Untrusted character-edit payloads and id path params cross into the backend | JSON edit payloads, path-param ids |
| backend -> tts_client (preview synth) | Reuses the Phase 1 GPU/CPU-isolated HTTP boundary | Voice preview request/audio |
| browser React app -> backend endpoints | The UI is the single trusted client (Tailscale-only, single user) | All app state |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-02-01 | Denial of Service | POST /projects upload read | high | mitigate | `_read_upload_bounded(file, MAX_UPLOAD_BYTES)` (main.py:83,109; config.py:53,81) | closed |
| T-02-02 | Tampering | uuid-based project id / file paths | medium | mitigate | Server-generated `uuid4().hex` for project id and all persisted paths (main.py:137,382,665; generation_worker.py:84) | closed |
| T-02-03 | Information Disclosure | SQLite threading under asyncio background task | medium | mitigate | `check_same_thread=False` + fresh per-operation Session (db.py:26) | closed |
| T-02-SC-01 | Tampering | `uv add sqlmodel` (supply chain) | high | mitigate | `sqlmodel>=0.0.39` in backend/pyproject.toml:11; xai-sdk superseded by OpenRouter, no longer a dependency | closed |
| T-02-04 | Denial of Service | EPUB decompression (zip-bomb) | high | mitigate | Same `_read_upload_bounded` bounds compressed bytes before `epub.read_epub` decompresses (main.py:108-109) | closed |
| T-02-05 | Information Disclosure | XHTML XML parse (XXE) | high | mitigate | `BeautifulSoup(item.content, features="lxml-xml")` default (epub_parser.py:170); `resolve_entities`/`no_network` never overridden (epub_parser.py:17) | closed |
| T-02-06 | Tampering | EPUB-internal item names/hrefs | medium | mitigate | `item.get_name()`/`get_id()` used only as lowercased heuristic string match (epub_parser.py:134-136), never in a filesystem path | closed |
| T-02-SC-02 | Tampering | `uv add ebooklib beautifulsoup4 lxml` (supply chain) | high | mitigate | All three present in backend/pyproject.toml:12-14 | closed |
| T-02-07 | Tampering (of LLM output) | Grok/OpenRouter prompt construction | medium | mitigate | Separate `role: system` / `role: user` messages; book text never concatenated into instructions (analysis_client.py:129-130) | closed |
| T-02-08 | Information Disclosure | OPENROUTER_API_KEY handling (was XAI_API_KEY) | medium | mitigate | Read from env (config.py:60,88), used only in outbound `Authorization` header (analysis_client.py:150); no hit in any response body, log, or SSE payload | closed |
| T-02-09 | Denial of Service | Oversized-text token miscount (chars/4 under-estimate) | low | accept | ~50% margin absorbs heuristic error; overflow surfaces as caught analysis error -> Project status "error", not a crash | closed |
| T-02-10 | Tampering | preview WAV path construction | medium | mitigate | `preview_dir / f"{uuid.uuid4().hex}.wav"` (main.py:382); no client string used | closed |
| T-02-11 | Tampering | stale preview from eager-gen race | medium | mitigate | Per-character `voice_version` stamp bumped on edit (main.py:322); write gated on stamp still current (main.py:387) | closed |
| T-02-12 | Input Validation | PATCH/merge request bodies | low | mitigate | Pydantic `BaseModel` request classes (main.py:293,416,550); merge 404s on missing/cross-project ids before mutation (main.py:451-452) | closed |
| T-02-13 | Denial of Service | unbounded eager preview tasks on rapid re-assign | low | accept | Single-user tool; per-character version stamp collapses redundant writes; bounded by human click rate | closed |
| T-02-14 | Tampering | client-rendered book/character text (XSS) | low | mitigate | React escapes text by default; no `dangerouslySetInnerHTML` anywhere in frontend/src (0 hits) | closed |
| T-02-15 | Information Disclosure | preview audio URL | low | accept | Same-origin, Tailscale-scoped; no auth layer by design for this single-user tool | closed |

*Status: open · closed · open — below {block_on} threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-02-01 | T-02-09 | Token-count heuristic error is absorbed by margin; worst case is a caught error state, not a crash or data loss | plan-time (02-03-PLAN.md) | 2026-07-12 |
| AR-02-02 | T-02-13 | Single-user tool; version-stamp collapse bounds redundant work to human click rate, no queue needed | plan-time (02-04-PLAN.md) | 2026-07-12 |
| AR-02-03 | T-02-15 | Tailscale-only network boundary; no auth layer by design across this whole project | plan-time (02-05-PLAN.md) | 2026-07-12 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-12 | 17 | 17 | 0 | /gsd-secure-phase (L1 grep-depth verification, register authored at plan time, asvs_level=1) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-12

**Note:** Threat register T-02-08 and T-02-SC-01 originally referenced `XAI_API_KEY`/`xai-sdk`; the codebase has since moved to `OPENROUTER_API_KEY`/OpenRouter per the project's stack decision (CLAUDE.md). The underlying mitigation pattern (env-only key, never logged/returned; vetted dependency) holds under the new dependency — this is a stale-register naming drift, not a security gap.
