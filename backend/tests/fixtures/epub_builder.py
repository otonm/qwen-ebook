"""Builds small .epub fixtures in-memory for test_epub_parser.py.

No binary .epub blobs are committed to the repo — `ebooklib` (already a
test/runtime dependency) can build a real, spec-valid EPUB container in a
few lines, and that's more maintainable than a checked-in binary fixture a
future contributor can't diff or regenerate.
"""

from __future__ import annotations

import io
import zipfile

from ebooklib import epub

COPYRIGHT_TEXT = (
    "Copyright 2026 by the Author. All rights reserved. No part of this "
    "publication may be reproduced, distributed, or transmitted in any "
    "form or by any means without the prior written permission of the "
    "publisher, except in the case of brief quotations."
)

CHAPTER1_VISIBLE_TEXT = (
    "The old lighthouse keeper watched the storm roll in from the north, "
    "his weathered hands gripping the iron rail as the wind howled around "
    "the tower he had called home for forty long years by the cold and "
    "restless sea, listening for the first rumble of thunder over the water."
)

FOOTNOTE_MARKER_TEXT = "1"

FOOTNOTE_BODY_TEXT = (
    "A lengthy digression about nineteenth-century lighthouse lens "
    "maintenance schedules that has nothing to do with the story itself."
)

CHAPTER2_VISIBLE_TEXT = (
    "Maria climbed down the wet stone steps at dawn, the tide already "
    "lapping at the base of the lighthouse as grey light broke over the "
    "churning sea, wondering if they would make it back before the water "
    "rose any higher along the rocky shoreline they both knew so well."
)

LINEAR_NO_TEXT = (
    "This is an ancillary page (an errata slip or a promotional insert) "
    "explicitly marked linear=\"no\" in the spine, so it must never appear "
    "in the extracted narrative text regardless of its own content length."
)


def _html_item(item_id: str, file_name: str, content: str) -> epub.EpubHtml:
    item = epub.EpubHtml(title=item_id, file_name=file_name, lang="en")
    item.id = item_id
    item.content = content
    return item


def build_valid_epub() -> bytes:
    """A cover + copyright page (both skippable) + two narrative chapters,
    the first carrying an inline EPUB3 footnote (marker + same-document
    note body) + one linear="no" ancillary item."""
    book = epub.EpubBook()
    book.set_identifier("qwen-ebook-test-valid")
    book.set_title("Test Book")
    book.set_language("en")

    cover = _html_item("cover", "cover.xhtml", "<h1>Cover</h1>")
    copyright_page = _html_item("copyright", "copyright.xhtml", f"<p>{COPYRIGHT_TEXT}</p>")
    chapter1 = _html_item(
        "chap1",
        "chap1.xhtml",
        (
            f"<p>{CHAPTER1_VISIBLE_TEXT}"
            f'<a epub:type="noteref" href="#note1" id="ref1">{FOOTNOTE_MARKER_TEXT}</a>'
            "</p>"
            f'<aside epub:type="footnote" id="note1"><p>{FOOTNOTE_BODY_TEXT}</p></aside>'
        ),
    )
    chapter2 = _html_item("chap2", "chap2.xhtml", f"<p>{CHAPTER2_VISIBLE_TEXT}</p>")
    ancillary = _html_item("ancillary", "ancillary.xhtml", f"<p>{LINEAR_NO_TEXT}</p>")

    for item in (cover, copyright_page, chapter1, chapter2, ancillary):
        book.add_item(item)

    book.toc = (cover, copyright_page, chapter1, chapter2)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    # (item, linear) tuples — ebooklib accepts either a bare item (linear
    # defaults to "yes") or an (item, "no") pair for spine exclusions.
    book.spine = [cover, copyright_page, chapter1, chapter2, (ancillary, "no")]

    buf = io.BytesIO()
    epub.write_epub(buf, book)
    return buf.getvalue()


def build_broken_chapter_epub() -> bytes:
    """A valid EPUB container whose one chapter's internal XHTML file has
    been overwritten with genuine non-XML garbage bytes at the zip level —
    bytes lxml's recover=True mode cannot extract any element tree from at
    all, unlike merely-malformed-but-recoverable markup."""
    base = build_valid_epub()

    buf_in = io.BytesIO(base)
    buf_out = io.BytesIO()
    with (
        zipfile.ZipFile(buf_in, "r") as zin,
        zipfile.ZipFile(buf_out, "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        for zinfo in zin.infolist():
            data = zin.read(zinfo.filename)
            if zinfo.filename.endswith("chap1.xhtml"):
                data = b"\x00\x01\x02\xff\xfe not xml at all <<<>>>>"
            zout.writestr(zinfo, data)

    return buf_out.getvalue()
