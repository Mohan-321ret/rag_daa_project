"""
Chunking Service  –  Phase 3 Module 2 (Step 4)
------------------------------------------------
Implements semantic chunking using LangChain's RecursiveCharacterTextSplitter.

Splitting strategy (priority order):
  1. Double newline (paragraph boundary)
  2. Single newline (line boundary)
  3. Sentence boundary  ('. ')
  4. Space
  5. Empty string (character-level fallback)

This mirrors heading/paragraph/section splitting as required.
Chunks shorter than CHUNK_MIN_LENGTH are discarded to avoid noise.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Chunk dataclass ───────────────────────────────────────────────────────────

@dataclass
class TextChunk:
    """Represents a single semantic chunk extracted from a document."""
    index: int          # position within the document (0-based)
    text: str           # chunk content
    char_start: int     # character offset in the original cleaned text
    char_end: int       # character offset end in the original cleaned text
    word_count: int     # number of words in this chunk


# ── Chunker ───────────────────────────────────────────────────────────────────

def chunk_document(text: str) -> List[TextChunk]:
    """
    Split *text* into semantic chunks using RecursiveCharacterTextSplitter.

    Config (from settings):
        chunk_size      – target characters per chunk (default 1000)
        chunk_overlap   – overlap between consecutive chunks (default 200)
        chunk_min_length – discard chunks shorter than this (default 50)

    Returns:
        Ordered list of TextChunk objects. Empty list if text is too short.
    """
    if not text or not text.strip():
        logger.warning("[ChunkingService] Received empty text – returning no chunks.")
        return []

    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        # Separators tried in order (paragraph → line → sentence → word → char)
        separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""],
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=len,
        is_separator_regex=False,
        # Keep the separator at the end of each chunk for readability
        keep_separator=True,
    )

    raw_chunks: list[str] = splitter.split_text(text)

    chunks: list[TextChunk] = []
    search_start = 0  # track position in original text for char offsets

    for idx, chunk_text in enumerate(raw_chunks):
        # Filter out trivially short chunks
        stripped = chunk_text.strip()
        if len(stripped) < settings.chunk_min_length:
            logger.debug(
                "[ChunkingService] Skipping short chunk #%d (len=%d < min=%d)",
                idx, len(stripped), settings.chunk_min_length,
            )
            continue

        # Calculate character offsets in the original text
        char_start = text.find(chunk_text, search_start)
        if char_start == -1:
            # fallback if exact match fails (can happen after normalisation)
            char_start = search_start
        char_end = char_start + len(chunk_text)
        search_start = max(search_start, char_end - settings.chunk_overlap)

        chunks.append(TextChunk(
            index=len(chunks),    # use len(chunks) so indices stay contiguous after filtering
            text=stripped,
            char_start=char_start,
            char_end=char_end,
            word_count=len(stripped.split()),
        ))

    logger.info(
        "[ChunkingService] Chunked document | total_chars=%d -> %d chunks "
        "(chunk_size=%d, overlap=%d)",
        len(text), len(chunks), settings.chunk_size, settings.chunk_overlap,
    )
    return chunks
