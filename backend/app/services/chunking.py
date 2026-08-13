"""Recursive character chunking with overlap."""

from app.config import settings

# Tried in order; the first that yields a break near the target size wins, so a
# chunk ends at a paragraph if it can, a sentence if it cannot, and mid-word
# only as a last resort.
_SEPARATORS = ("\n\n", "\n", ". ", " ")

# How far back from the hard limit we will look for a nicer break.
_LOOKBACK_RATIO = 0.2


def _best_break(text: str, start: int, hard_end: int) -> int:
    """Find a natural break at or before `hard_end`, else fall back to it."""
    earliest = max(start + 1, hard_end - int((hard_end - start) * _LOOKBACK_RATIO))

    for separator in _SEPARATORS:
        found = text.rfind(separator, earliest, hard_end)
        if found != -1:
            return found + len(separator)

    return hard_end


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[str]:
    """Split text into overlapping chunks.

    Overlap carries context across a boundary so a sentence split down the
    middle still retrieves sensibly.
    """
    size = settings.chunk_size if chunk_size is None else chunk_size
    overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap

    if size <= 0:
        raise ValueError("chunk_size must be positive.")
    if overlap < 0:
        raise ValueError("chunk_overlap cannot be negative.")
    if overlap >= size:
        # Each step advances by (size - overlap); if that is not positive the
        # loop below would never terminate.
        raise ValueError("chunk_overlap must be smaller than chunk_size.")

    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        hard_end = min(start + size, len(text))
        end = hard_end if hard_end >= len(text) else _best_break(text, start, hard_end)

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        # The max() floor guarantees forward progress even when a break lands
        # at or before where this chunk started.
        start = max(end - overlap, start + 1)

    return chunks
