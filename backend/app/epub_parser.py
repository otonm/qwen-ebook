"""EPUB text extraction (ING-02).

Walks `book.spine` in reading order — never `get_items_of_type
(ITEM_DOCUMENT)`, which is manifest order and can silently scramble
chapters (Pitfall 2 / 02-RESEARCH.md) — respecting `linear == "no"`
exclusions. Strips EPUB3-style footnote markers and their same-document
note bodies (D-11), applies a best-effort skip of obvious non-narrative
spine items (D-10), and preserves chapter boundaries as blank-line breaks
(D-12) so `chunk_paragraphs`' paragraph splitter treats them as chunk
boundaries too. Fails fast (`EpubParseError`) if a single chapter can't be
parsed even under lxml's `recover=True` behavior (D-13) — never a silent
skip-and-continue.

Security (T-02-05, RESEARCH.md Security Domain): parsed via BeautifulSoup's
`features="lxml-xml"`, which is lxml's own default best-effort recovery
parser. Never construct a custom `lxml.etree.XMLParser` with
`resolve_entities=True`/`no_network=False` here — lxml disables
entity/network resolution by default, and overriding that would reopen
XXE. `_read_upload_bounded` (main.py) already bounds the *compressed*
upload before this module ever runs `epub.read_epub`, which is what
guards against a zip-bomb (T-02-04) — this module does not re-check size.
"""

from __future__ import annotations

import re
from io import BytesIO

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

# EPUB3's `epub:type` convention (idpf.org/epub/vocab/structure) is the
# only footnote-marking signal detected (D-11 / A2 in 02-RESEARCH.md). A
# plain `<sup>` marker with no `epub:type` attribute is a known, accepted
# leak — not something this heuristic claims to catch.
_NOTE_REF_TYPES = {"noteref"}
_NOTE_BODY_TYPES = {"footnote", "endnote", "rearnote"}

# Best-effort non-narrative signals (D-10): very short extracted text, or a
# filename/id hint matching common front/back-matter naming. Not a
# guarantee — an ambiguous item still passes through to the LLM.
_NON_NARRATIVE_HINTS = (
    "cover",
    "toc",
    "contents",
    "copyright",
    "title",
    "titlepage",
    "index",
    "nav",
)
_MIN_NARRATIVE_CHARS = 200

# Chapter-boundary sentinel joined between successive chapters' extracted
# text (D-12) — a blank line, matching chunking.py's own paragraph-split
# regex (`\n\s*\n`) so a chapter break also reads as a chunk boundary in
# the oversized-text fallback path.
_CHAPTER_BOUNDARY = "\n\n"

_WHITESPACE_RUN = re.compile(r"\s+")


class EpubParseError(Exception):
    """Raised when a spine chapter can't be parsed even under lxml's
    `recover=True` mode (D-13) — the whole upload is rejected; no partial
    book is ever returned."""


def _strip_footnotes(soup: BeautifulSoup) -> None:
    """Remove footnote/endnote markers and their same-document linked note
    bodies from `soup` in place (D-11).

    Known limits (documented, not silently assumed): only the EPUB3
    `epub:type` convention is detected, and only a same-document
    `href="#id"` link is resolved to its note body — a note body living in
    a *separate* spine item relies on D-10's non-narrative filter instead,
    not on this function.
    """
    removed_ids: set[str] = set()
    for tag in soup.find_all(attrs={"epub:type": True}):
        types = set((tag.attrs.get("epub:type") or "").split())
        if types & _NOTE_REF_TYPES:
            href = tag.attrs.get("href", "")
            if href.startswith("#"):
                removed_ids.add(href[1:])
            tag.decompose()
        elif types & _NOTE_BODY_TYPES:
            note_id = tag.attrs.get("id")
            if note_id:
                removed_ids.add(note_id)
            tag.decompose()

    for note_id in removed_ids:
        target = soup.find(id=note_id)
        if target is not None:
            target.decompose()


def _is_non_narrative(item: epub.EpubHtml, text: str) -> bool:
    """Best-effort skip of obvious front/back matter (D-10) — a heuristic,
    not a guarantee. Ambiguous items intentionally still pass through."""
    if len(text) < _MIN_NARRATIVE_CHARS:
        return True

    name_hint = (item.get_name() or "").lower()
    id_hint = (item.get_id() or "").lower()
    return any(hint in name_hint or hint in id_hint for hint in _NON_NARRATIVE_HINTS)


def extract_text(epub_bytes: bytes) -> str:
    """Extract reading-order, footnote-stripped, non-narrative-filtered,
    chapter-preserving narrative text from `epub_bytes` (ING-02).

    Raises `EpubParseError` if the container itself or any single spine
    chapter can't be parsed even under lxml's `recover=True` behavior.
    """
    try:
        book = epub.read_epub(BytesIO(epub_bytes), options={"ignore_ncx": True})
    except Exception as exc:
        raise EpubParseError(f"could not read EPUB container: {exc}") from exc

    chapters: list[str] = []
    for idref, linear in book.spine:
        if linear == "no":
            continue

        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        # `item.content` is the raw XHTML bytes read straight from the zip
        # entry — deliberately *not* `item.get_content()`, which re-runs
        # ebooklib's own lenient `parse_html_string` and re-templates the
        # document, silently absorbing genuinely broken markup into an
        # empty-but-well-formed shell and defeating the fail-fast check
        # below.
        soup = BeautifulSoup(item.content, features="lxml-xml")
        if soup.find() is None:
            # lxml's recover=True mode extracted zero elements at all —
            # not "malformed but salvageable," genuinely unparseable.
            raise EpubParseError(f"chapter {idref!r} could not be parsed")

        _strip_footnotes(soup)

        # Narrative text only ever lives in <body> — extracting from the
        # whole document would leak <head><title> text (often just the
        # chapter's internal id/title string) into the narration.
        body = soup.find("body")
        target = body if body is not None else soup
        text = _WHITESPACE_RUN.sub(" ", target.get_text(separator=" ", strip=True)).strip()

        if _is_non_narrative(item, text):
            continue

        chapters.append(text)

    return _CHAPTER_BOUNDARY.join(chapters)
