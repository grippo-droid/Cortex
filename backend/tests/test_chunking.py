"""T2.3 — the chunking function."""

import pytest

from app.services.chunking import chunk_text


def test_short_text_is_a_single_chunk():
    assert chunk_text("hello world", chunk_size=100, chunk_overlap=10) == ["hello world"]


def test_empty_and_whitespace_text_produce_no_chunks():
    assert chunk_text("", chunk_size=100, chunk_overlap=10) == []
    assert chunk_text("   \n\t  ", chunk_size=100, chunk_overlap=10) == []


def test_long_text_is_split_into_multiple_chunks():
    text = "word " * 500

    chunks = chunk_text(text, chunk_size=200, chunk_overlap=20)

    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)


def test_every_chunk_respects_the_size_limit():
    text = "".join(f"sentence number {index}. " for index in range(400))

    chunks = chunk_text(text, chunk_size=300, chunk_overlap=50)

    assert all(len(chunk) <= 300 for chunk in chunks)


def test_chunks_overlap_so_context_survives_a_boundary():
    text = " ".join(f"token{index}" for index in range(300))

    chunks = chunk_text(text, chunk_size=200, chunk_overlap=60)

    # Something from the tail of one chunk should reappear in the next.
    first_tail = chunks[0][-40:].split()
    assert any(fragment in chunks[1] for fragment in first_tail if fragment)


def test_no_content_is_lost_between_chunks():
    text = " ".join(f"token{index}" for index in range(300))

    chunks = chunk_text(text, chunk_size=200, chunk_overlap=40)

    combined = " ".join(chunks)
    for index in range(300):
        assert f"token{index}" in combined


def test_paragraph_boundaries_are_preferred():
    text = "First paragraph here.\n\n" + ("x" * 50) + "\n\nThird paragraph."

    chunks = chunk_text(text, chunk_size=60, chunk_overlap=5)

    assert chunks[0].startswith("First paragraph")


def test_text_without_separators_still_splits():
    """A single unbroken run must not defeat the splitter."""
    chunks = chunk_text("a" * 500, chunk_size=100, chunk_overlap=10)

    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)


@pytest.mark.parametrize(
    ("size", "overlap"),
    [(0, 0), (-1, 0), (100, -1), (100, 100), (100, 150)],
)
def test_invalid_parameters_are_rejected(size, overlap):
    """Overlap >= size would never advance, so it must raise, not hang."""
    with pytest.raises(ValueError):
        chunk_text("some text to split", chunk_size=size, chunk_overlap=overlap)


def test_defaults_come_from_settings():
    from app.config import settings

    text = "z" * (settings.chunk_size * 2)

    chunks = chunk_text(text)

    assert len(chunks) > 1
    assert all(len(chunk) <= settings.chunk_size for chunk in chunks)
