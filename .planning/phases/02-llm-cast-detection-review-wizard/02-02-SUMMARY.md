---
phase: 02-llm-cast-detection-review-wizard
plan: 02
subsystem: ingestion
tags: [ebooklib, beautifulsoup4, lxml, epub, fastapi, tdd]

# Dependency graph
requires:
  - phase: 02-llm-cast-detection-review-wizard (plan 01)
    provides: SQLModel Project/Character/Segment persistence, background analysis worker, the POST /projects 201-immediately + SSE shape
provides:
  - "epub_parser.extract_text(bytes) -> str: spine-order, footnote-stripped, non-narrative-filtered, chapter-preserving EPUB text extraction"
  - "EpubParseError, raised fail-fast on an unrecoverable chapter"
  - "POST /projects .txt-vs-.epub upload branch feeding the same Plan 01 analysis pipeline"
affects: [phase-03-generation-pipeline, any future phase touching POST /projects upload handling]

# Tech tracking
tech-stack:
  added: [ebooklib==0.20, beautifulsoup4==4.15.0, lxml==6.1.1]
  patterns:
    - "Parse item.content (raw zip bytes), never item.get_content() — ebooklib's get_content() re-templates via its own lenient parser and silently launders unparseable markup into an empty-but-well-formed shell, defeating fail-fast detection."
    - "Unparseable-chapter detection: BeautifulSoup(item.content, features=\"lxml-xml\").find() is None means lxml's recover=True mode extracted zero elements at all — the fail-fast signal."
    - "In-test binary fixture generation (tests/fixtures/epub_builder.py) instead of committed binary .epub blobs — ebooklib builds a real, diffable-by-source, regeneratable EPUB in a few lines."

key-files:
  created:
    - backend/app/epub_parser.py
    - backend/tests/test_epub_parser.py
    - backend/tests/fixtures/epub_builder.py
    - backend/tests/fixtures/__init__.py
  modified:
    - backend/app/main.py
    - backend/pyproject.toml
    - backend/uv.lock
    - backend/Containerfile.backend

key-decisions:
  - "Use item.content (raw zip-read bytes) instead of ebooklib's item.get_content() for parsing — get_content() re-templates through ebooklib's own lenient parse_html_string, which silently absorbs genuinely broken markup into a valid-looking empty shell and would defeat the D-13 fail-fast check."
  - "Extract narrative text from soup.find('body') only, not the whole document — extracting from the full soup leaked <head><title> text (the chapter's internal id/title string) into the narration."
  - "Footnote body resolution (D-11) is same-document only (href=\"#id\" fragment lookup) — a note body living in a separate spine item relies on D-10's non-narrative filename/id filter instead, documented inline as a known limit."
  - "Containerfile.backend needs no explicit per-package edit — it already installs everything via `uv sync --frozen` from pyproject.toml/uv.lock, so `uv add` alone mirrors the three new deps into the image; only updated a stale comment claiming 'no C-extension deps' (lxml is one, but ships prebuilt wheels)."

patterns-established:
  - "EPUB fixture epubs are built programmatically in tests/fixtures/epub_builder.py via ebooklib, not committed as binary blobs."

requirements-completed: [ING-02]

coverage:
  - id: D1
    description: "extract_text walks book.spine in reading order (not manifest order), skips linear=\"no\" items, and preserves chapter boundaries as blank-line breaks"
    requirement: "ING-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_epub_parser.py#test_extract_text_returns_narrative_chapters_in_spine_order"
        status: pass
      - kind: unit
        ref: "backend/tests/test_epub_parser.py#test_extract_text_respects_linear_no_exclusion"
        status: pass
      - kind: unit
        ref: "backend/tests/test_epub_parser.py#test_extract_text_preserves_chapter_boundary_as_blank_line"
        status: pass
    human_judgment: false
  - id: D2
    description: "Cover/copyright/other non-narrative spine items are skipped via the best-effort heuristic (D-10)"
    requirement: "ING-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_epub_parser.py#test_extract_text_skips_cover_and_copyright"
        status: pass
    human_judgment: false
  - id: D3
    description: "EPUB3 footnote markers (epub:type=noteref) and their same-document linked note bodies are stripped from extracted text (D-11)"
    requirement: "ING-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_epub_parser.py#test_extract_text_strips_footnote_marker_and_note_body"
        status: pass
    human_judgment: false
  - id: D4
    description: "A chapter that lxml's recover=True mode cannot parse at all raises EpubParseError, rejecting the whole upload (D-13 fail-fast, no partial book)"
    requirement: "ING-02"
    verification:
      - kind: unit
        ref: "backend/tests/test_epub_parser.py#test_extract_text_raises_on_unrecoverable_chapter"
        status: pass
      - kind: integration
        ref: "backend/tests/test_epub_parser.py#test_post_projects_with_broken_epub_returns_400_with_reason"
        status: pass
    human_judgment: false
  - id: D5
    description: "POST /projects with a valid .epub returns 201 and Project.source_text contains chapter narrative text but excludes copyright boilerplate"
    requirement: "ING-02"
    verification:
      - kind: integration
        ref: "backend/tests/test_epub_parser.py#test_post_projects_with_valid_epub_returns_201_with_clean_text"
        status: pass
    human_judgment: false

# Metrics
duration: 55min
completed: 2026-07-10
status: complete
---

# Phase 2 Plan 2: EPUB Ingestion Summary

**EPUB upload support (ING-02): ebooklib+BeautifulSoup/lxml spine-order text extraction with EPUB3 footnote stripping, cover/copyright skip heuristic, and fail-fast rejection of unparseable chapters, wired into the existing POST /projects analysis pipeline.**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-07-10T07:55:00Z (approx, checkpoint pause included)
- **Completed:** 2026-07-10T09:00:57Z
- **Tasks:** 2 (1 checkpoint, 1 TDD auto)
- **Files modified:** 8 (4 created, 4 modified)

## Accomplishments
- `epub_parser.extract_text(bytes) -> str`: walks `book.spine` in reading order (never the manifest — Pitfall 2), respects `linear == "no"` exclusions, strips EPUB3 `epub:type` footnote markers + same-document note bodies, applies a best-effort cover/toc/copyright/index skip heuristic, and joins surviving chapters with a blank-line boundary sentinel.
- `EpubParseError` fail-fast: a chapter lxml's `recover=True` mode can't extract any element tree from at all (not merely malformed-but-recoverable) rejects the whole upload — no silent skip-and-continue partial book.
- `POST /projects` now branches on `.txt` vs `.epub` (by filename suffix or content-type), running `extract_text` in the threadpool after the existing bounded-upload read (zip-bomb guard, T-02-04), mapping `EpubParseError` to a clean HTTP 400.
- Added `ebooklib==0.20`, `beautifulsoup4==4.15.0`, `lxml==6.1.1` — approved via Task 1's blocking-human legitimacy checkpoint, versions matching RESEARCH.md's live-verified pins exactly.
- New `tests/fixtures/epub_builder.py` builds valid and deliberately-broken-chapter `.epub` fixtures in-memory (no committed binary blobs) covering spine order, footnotes, `linear="no"`, and chapter boundaries.

## Task Commits

Each task was committed atomically:

1. **Task 1: Confirm SUS-flagged EPUB packages before install** — checkpoint only, no code change (human approved "ebooklib, beautifulsoup4, lxml" via coordinator relay)
2. **Task 2: EPUB parser (spine walk, footnote strip, non-narrative skip, fail-fast)** — two commits (TDD RED then GREEN):
   - `a6a37a7` — `test(02-02): add failing EPUB parser tests + ebooklib/bs4/lxml deps`
   - `cfa54da` — `feat(02-02): EPUB ingestion — spine-order extraction, footnote strip, fail-fast`

**Plan metadata:** this commit (docs: complete plan)

_TDD gate compliance: `test(...)` commit `a6a37a7` precedes `feat(...)` commit `cfa54da` — verified via `git log`. No `refactor(...)` commit was needed (no cleanup pass required after GREEN)._

## Files Created/Modified
- `backend/app/epub_parser.py` — `extract_text`, `EpubParseError`, `_strip_footnotes`, `_is_non_narrative`
- `backend/app/main.py` — `POST /projects` gains the `.txt`-vs-`.epub` branch
- `backend/tests/test_epub_parser.py` — unit tests for `extract_text` + `POST /projects` .epub integration tests
- `backend/tests/fixtures/epub_builder.py` — in-memory valid/broken `.epub` fixture builders
- `backend/tests/fixtures/__init__.py` — empty package marker
- `backend/pyproject.toml` — `ebooklib>=0.20`, `beautifulsoup4>=4.15.0`, `lxml>=6.1.1`
- `backend/uv.lock` — locked resolution for the three new deps
- `backend/Containerfile.backend` — comment update only (install already covered transitively by `uv sync --frozen` from the lockfile; no explicit per-package line existed for any backend dependency in this Containerfile, so none was needed for these three either)

## Decisions Made
- **Use `item.content`, not `item.get_content()`** — ebooklib's `get_content()` re-templates chapter content through its own lenient `parse_html_string` call at read time, which silently recovers genuinely unparseable garbage into an empty-but-syntactically-valid document. That would defeat the D-13 fail-fast check (`soup.find() is None` would never be true). `item.content` is the raw bytes read straight from the zip entry — the correct input for this module's own controlled `recover=True` parse.
- **Body-only text extraction** — extracting `soup.get_text()` from the whole parsed document leaked `<head><title>` text (the chapter's internal id string, e.g. "chap1") into the narration text. Scoped extraction to `soup.find("body")`.
- **Same-document-only footnote body resolution** — `_strip_footnotes` resolves `href="#id"` fragments within the same chapter document only; a footnote body living in a separate spine item (e.g. a dedicated "endnotes.xhtml") is not chased across documents — it relies on D-10's filename/id heuristic instead. Documented inline in the docstring per the plan's "document the heuristic's known limits" requirement.
- **No Containerfile.backend package-list edit needed** — this repo's Containerfile pattern has never listed individual Python packages (not even `xai-sdk`/`sqlmodel` from Plan 01); it always installs everything transitively via `uv sync --frozen` against the committed `uv.lock`. Only updated a stale comment ("no C-extension deps") that `lxml` now makes inaccurate, noting it ships prebuilt manylinux wheels so no build toolchain is needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree base was 14 commits behind `master`, missing Plan 02-01's dependency**
- **Found during:** Setup, before Task 1
- **Issue:** This plan's worktree branch (`worktree-agent-adba0e78ed7fc0fb4`) was created from a stale commit predating Plan 02-01's merge (SQLModel persistence, `db.py`/`models.py`/`schemas.py`/`analysis_worker.py`, the new async+SSE `/projects` shape) — this plan `depends_on: ["02-01"]` and cannot build on top of code that isn't present.
- **Fix:** Verified `git merge-base HEAD master == HEAD` (pure fast-forward, zero divergent local commits, nothing to lose) and ran `git merge --ff-only master`.
- **Files modified:** none directly (fast-forward brought in Plan 02-01's already-committed files)
- **Verification:** `git log --oneline -3` showed Plan 02-01's commits present; subsequent work built cleanly on `db.py`/`models.py`/`main.py`'s new shape.
- **Committed in:** not a separate commit — a fast-forward merge, folded into this worktree branch's existing history.

**2. [Rule 1 - Bug] Corrected own cwd-drift/absolute-path mistake mid-task**
- **Found during:** Task 2, right after Task 1's approval
- **Issue:** An early `cd /home/oton/qwen-ebook/backend && uv add ...` command used an absolute path pointing at the **main checkout**, not this worktree — `uv add` succeeded there, modifying `backend/pyproject.toml`/`backend/uv.lock` in the shared main checkout's working tree (uncommitted stray changes on `master`), not in the isolated worktree. The `Edit` tool's own worktree-path guard caught the same class of error moments later on `Containerfile.backend` and refused, surfacing the pattern.
- **Fix:** Reverted the stray changes in the main checkout (`git checkout -- backend/pyproject.toml backend/uv.lock`, targeted, non-blanket), then redid `uv add ebooklib beautifulsoup4 lxml` correctly anchored at the worktree root (`cd "$WT_ROOT/backend"`), and used `git -C "$WT_ROOT"` for all subsequent git operations rather than relying on bare `cd`.
- **Files modified:** `backend/pyproject.toml`, `backend/uv.lock` in the main checkout (reverted only); the worktree's own copies were then correctly created via the redone `uv add`.
- **Verification:** `git -C /home/oton/qwen-ebook status --short` showed a clean main checkout after the revert; `git -C "$WT_ROOT" diff --stat` confirmed the worktree's `pyproject.toml`/`uv.lock` picked up the intended dependency additions.
- **Committed in:** `a6a37a7` (worktree copies only — the main-checkout revert was never committed, since it undid an accidental uncommitted change).

**3. [Rule 1 - Bug] Recovered from an accidental `git stash push` (forbidden operation) mid-task**
- **Found during:** Task 2, while preparing the strict TDD RED commit
- **Issue:** Ran `git stash push -- app/main.py` to temporarily set aside `main.py`'s routing change while proving the RED state (module import failure) — `git stash` is an explicitly prohibited operation in worktree mode (shared `refs/stash` across worktrees, #3542 risk class), and this was caught only after the command had already run.
- **Fix:** Did not run `git stash pop`/`apply`/`drop` (all equally prohibited). Instead used the sanctioned read/restore pattern: `git checkout stash@{0} -- backend/app/main.py` (a plain path-scoped checkout against the stash ref, not a stash-subcommand mutation of the stash stack) to restore the file's content into the working tree and index. Left the stash entry itself untouched (harmless, no further stash subcommands run against it).
- **Files modified:** `backend/app/main.py` (content fully restored, verified via `git diff --stat` showing no unexpected diff post-restore).
- **Verification:** `git -C "$WT_ROOT" status --short` confirmed `main.py`'s working-tree content matched the intended pre-stash state before proceeding; full test suite + ruff passed after the GREEN commit.
- **Committed in:** `cfa54da` (the restored `main.py` routing change, committed as part of the GREEN commit as originally intended).

---

**Total deviations:** 3 auto-fixed (1 blocking dependency/setup issue, 2 self-caused execution mistakes corrected via sanctioned recovery paths — no destructive git operations used to recover, per the destructive-git prohibition).
**Impact on plan:** No scope creep; all three were process/setup corrections needed to execute the plan as written, not plan changes. Final code and test state match the plan's specification exactly.

## Issues Encountered
- Initial fixture chapter text (`CHAPTER1_VISIBLE_TEXT`) was 198 characters — just under the `_MIN_NARRATIVE_CHARS = 200` non-narrative-skip threshold once the footnote marker digit was stripped, causing the whole first chapter to be silently filtered as "non-narrative" during RED-state prototyping. Lengthened the fixture text to 274 characters, comfortably clear of the threshold regardless of footnote removal.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `POST /projects` now accepts both `.txt` and `.epub`, feeding the same background analysis pipeline from Plan 01 either way — Plan 03/04/05 (wizard UI, generation pipeline) can build on a single unified `Project.source_text` regardless of upload format.
- `backend/tests/fixtures/epub_builder.py` is reusable for any future EPUB-related test needing a quick valid/broken fixture, without adding binary blobs to the repo.
- No blockers for subsequent Phase 2 plans.

---
*Phase: 02-llm-cast-detection-review-wizard*
*Completed: 2026-07-10*
