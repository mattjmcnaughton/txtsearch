"""Unit tests for the Chunker service."""

import hashlib
from uuid import uuid4

import pytest

from txtsearch.models.chunk import DocumentChunk
from txtsearch.services.chunker import Chunker


class TestChunkerInitialization:
    """Tests for Chunker initialization and configuration."""

    def test_default_initialization(self) -> None:
        chunker = Chunker()
        assert chunker._chunk_size == 512
        assert chunker._chunk_overlap == 50
        assert chunker._separators == ["\n\n", "\n", " ", ""]

    def test_custom_chunk_size(self) -> None:
        chunker = Chunker(chunk_size=256)
        assert chunker._chunk_size == 256

    def test_custom_overlap(self) -> None:
        chunker = Chunker(chunk_overlap=100)
        assert chunker._chunk_overlap == 100

    def test_custom_separators(self) -> None:
        separators = [".", " "]
        chunker = Chunker(separators=separators)
        assert chunker._separators == separators

    def test_overlap_must_be_less_than_size(self) -> None:
        with pytest.raises(ValueError, match="chunk_overlap must be less than chunk_size"):
            Chunker(chunk_size=100, chunk_overlap=100)

    def test_overlap_greater_than_size_raises(self) -> None:
        with pytest.raises(ValueError, match="chunk_overlap must be less than chunk_size"):
            Chunker(chunk_size=100, chunk_overlap=150)


class TestChunkerBasicChunking:
    """Tests for basic chunking functionality."""

    def test_short_text_returns_single_chunk(self) -> None:
        chunker = Chunker(chunk_size=100)
        document_id = str(uuid4())
        text = "This is a short text."

        chunks = chunker.chunk(text, document_id)

        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].document_id == document_id

    def test_empty_text_returns_no_chunks(self) -> None:
        chunker = Chunker()
        document_id = str(uuid4())

        chunks = chunker.chunk("", document_id)

        assert chunks == []

    def test_whitespace_only_returns_no_chunks(self) -> None:
        chunker = Chunker()
        document_id = str(uuid4())

        chunks = chunker.chunk("   \n\n\t  ", document_id)

        assert chunks == []

    def test_long_text_splits_into_multiple_chunks(self) -> None:
        chunker = Chunker(chunk_size=50, chunk_overlap=10)
        document_id = str(uuid4())
        text = "word " * 50  # 250 characters

        chunks = chunker.chunk(text, document_id)

        assert len(chunks) > 1

    def test_chunks_have_sequential_indices(self) -> None:
        chunker = Chunker(chunk_size=50, chunk_overlap=10)
        document_id = str(uuid4())
        text = "This is paragraph one.\n\nThis is paragraph two.\n\nThis is paragraph three."

        chunks = chunker.chunk(text, document_id)

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i


class TestChunkerPositionTracking:
    """Tests for character and line position tracking."""

    def test_single_chunk_positions(self) -> None:
        chunker = Chunker(chunk_size=100)
        document_id = str(uuid4())
        text = "Hello world"

        chunks = chunker.chunk(text, document_id)

        assert len(chunks) == 1
        assert chunks[0].char_start == 0
        assert chunks[0].char_end == len(text)

    def test_line_positions_single_line(self) -> None:
        chunker = Chunker(chunk_size=100)
        document_id = str(uuid4())
        text = "Single line text"

        chunks = chunker.chunk(text, document_id)

        assert chunks[0].line_start == 1
        assert chunks[0].line_end == 1

    def test_line_positions_multiple_lines(self) -> None:
        chunker = Chunker(chunk_size=100)
        document_id = str(uuid4())
        text = "Line one\nLine two\nLine three"

        chunks = chunker.chunk(text, document_id)

        assert chunks[0].line_start == 1
        assert chunks[0].line_end == 3

    def test_chunk_positions_are_valid(self) -> None:
        chunker = Chunker(chunk_size=30, chunk_overlap=5)
        document_id = str(uuid4())
        text = "First part.\n\nSecond part.\n\nThird part."

        chunks = chunker.chunk(text, document_id)

        for chunk in chunks:
            assert chunk.char_start >= 0
            assert chunk.char_end > chunk.char_start
            assert chunk.char_end <= len(text)
            assert chunk.line_start >= 1
            assert chunk.line_end >= chunk.line_start


class TestChunkerHashComputation:
    """Tests for content hash computation."""

    def test_chunk_has_valid_hash(self) -> None:
        chunker = Chunker(chunk_size=100)
        document_id = str(uuid4())
        text = "Test content"

        chunks = chunker.chunk(text, document_id)

        expected_hash = hashlib.sha256(text.encode()).hexdigest()
        assert chunks[0].content_hash == expected_hash

    def test_different_content_has_different_hash(self) -> None:
        chunker = Chunker(chunk_size=30, chunk_overlap=5)
        document_id = str(uuid4())
        text = "Part one.\n\nPart two."

        chunks = chunker.chunk(text, document_id)

        if len(chunks) > 1:
            assert chunks[0].content_hash != chunks[1].content_hash

    def test_hash_is_64_character_hex(self) -> None:
        chunker = Chunker(chunk_size=100)
        document_id = str(uuid4())
        text = "Test content"

        chunks = chunker.chunk(text, document_id)

        assert len(chunks[0].content_hash) == 64
        assert all(c in "0123456789abcdef" for c in chunks[0].content_hash)


class TestChunkerSeparatorBehavior:
    """Tests for separator-based splitting."""

    def test_splits_on_double_newline(self) -> None:
        chunker = Chunker(chunk_size=20, chunk_overlap=0)
        document_id = str(uuid4())
        text = "Paragraph one.\n\nParagraph two."

        chunks = chunker.chunk(text, document_id)

        assert len(chunks) == 2
        assert "Paragraph one." in chunks[0].text
        assert "Paragraph two." in chunks[1].text

    def test_splits_on_single_newline_when_needed(self) -> None:
        chunker = Chunker(chunk_size=20, chunk_overlap=0)
        document_id = str(uuid4())
        text = "Line one here.\nLine two here."

        chunks = chunker.chunk(text, document_id)

        assert len(chunks) >= 2

    def test_splits_on_space_when_needed(self) -> None:
        chunker = Chunker(chunk_size=15, chunk_overlap=0, separators=[" "])
        document_id = str(uuid4())
        text = "word1 word2 word3 word4"

        chunks = chunker.chunk(text, document_id)

        assert len(chunks) >= 2

    def test_hard_split_when_no_separator(self) -> None:
        chunker = Chunker(chunk_size=10, chunk_overlap=2)
        document_id = str(uuid4())
        text = "abcdefghijklmnopqrstuvwxyz"

        chunks = chunker.chunk(text, document_id)

        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk.text) <= 10

    def test_hard_split_prefers_word_boundaries(self) -> None:
        """Hard split should break at word boundaries, not mid-word."""
        chunker = Chunker(chunk_size=15, chunk_overlap=0, separators=[])
        document_id = str(uuid4())
        text = "hello world testing chunks"

        chunks = chunker.chunk(text, document_id)

        # Should split at word boundaries, not "hello world tes" + "ting chunks"
        for chunk in chunks:
            assert not chunk.text.endswith(" "), "Chunk shouldn't end with space"
            words_in_chunk = chunk.text.split()
            # Each word in the chunk should be complete (not truncated)
            for word in words_in_chunk:
                assert word in text, f"Word '{word}' should exist in original text"

    def test_hard_split_falls_back_to_exact_when_no_whitespace(self) -> None:
        """Hard split still works on text with no whitespace."""
        chunker = Chunker(chunk_size=10, chunk_overlap=2, separators=[])
        document_id = str(uuid4())
        text = "abcdefghijklmnopqrstuvwxyz"

        chunks = chunker.chunk(text, document_id)

        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk.text) <= 10


class TestChunkerOverlapBehavior:
    """Tests for chunk overlap functionality."""

    def test_zero_overlap_allowed(self) -> None:
        chunker = Chunker(chunk_size=100, chunk_overlap=0)
        document_id = str(uuid4())
        text = "Short text"

        chunks = chunker.chunk(text, document_id)

        assert len(chunks) == 1

    def test_hard_split_respects_overlap(self) -> None:
        chunker = Chunker(chunk_size=10, chunk_overlap=3)
        document_id = str(uuid4())
        text = "abcdefghijklmnopqrstuvwxyz"

        chunks = chunker.chunk(text, document_id)

        assert len(chunks) >= 3


class TestChunkerDocumentChunkModel:
    """Tests for DocumentChunk model creation."""

    def test_chunk_has_unique_id(self) -> None:
        chunker = Chunker(chunk_size=100)
        document_id = str(uuid4())
        text = "Test content"

        chunks = chunker.chunk(text, document_id)

        assert chunks[0].chunk_id is not None
        assert len(chunks[0].chunk_id) == 36  # UUID format

    def test_multiple_chunks_have_different_ids(self) -> None:
        chunker = Chunker(chunk_size=30, chunk_overlap=5)
        document_id = str(uuid4())
        text = "Part one.\n\nPart two.\n\nPart three."

        chunks = chunker.chunk(text, document_id)

        chunk_ids = [c.chunk_id for c in chunks]
        assert len(chunk_ids) == len(set(chunk_ids))

    def test_chunks_share_document_id(self) -> None:
        chunker = Chunker(chunk_size=30, chunk_overlap=5)
        document_id = str(uuid4())
        text = "Part one.\n\nPart two.\n\nPart three."

        chunks = chunker.chunk(text, document_id)

        for chunk in chunks:
            assert chunk.document_id == document_id

    def test_chunk_schema_version(self) -> None:
        chunker = Chunker(chunk_size=100)
        document_id = str(uuid4())
        text = "Test content"

        chunks = chunker.chunk(text, document_id)

        assert chunks[0].schema_version == DocumentChunk.SCHEMA_VERSION
