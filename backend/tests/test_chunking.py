from app.chunking import chunk_paragraphs


def test_empty_string_returns_empty_list():
    assert chunk_paragraphs("", target_len=800) == []


def test_whitespace_only_returns_empty_list():
    assert chunk_paragraphs("   \n\n   \n  ", target_len=800) == []


def test_two_short_paragraphs_merge_into_one_chunk():
    text = "Short one.\n\nShort two."
    result = chunk_paragraphs(text, target_len=800)
    assert result == ["Short one.\n\nShort two."]


def test_two_paragraphs_exceeding_target_len_split_into_two_chunks():
    text = "Short one.\n\nShort two."
    result = chunk_paragraphs(text, target_len=15)
    assert result == ["Short one.", "Short two."]


def test_oversized_single_paragraph_splits_at_sentence_boundaries():
    paragraph = "One. Two. Three. Four. Five."
    result = chunk_paragraphs(paragraph, target_len=10)
    assert len(result) > 1
    for piece in result:
        assert len(piece) <= 10
    # Reassembling the pieces must not drop or duplicate any sentence text.
    assert " ".join(result).replace("  ", " ") == paragraph
