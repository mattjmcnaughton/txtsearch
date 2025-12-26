"""Chunker service for splitting text into overlapping chunks."""

import hashlib
from uuid import uuid4

import structlog

from txtsearch.models.chunk import DocumentChunk


class Chunker:
    """Splits text content into overlapping chunks with position tracking.

    Uses recursive character splitting with configurable separators to preserve
    document structure. Tracks character and line positions for each chunk.
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        separators: list[str] | None = None,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        """Initialize the chunker.

        Args:
            chunk_size: Target size for each chunk in characters.
            chunk_overlap: Number of characters to overlap between chunks.
            separators: Ordered list of separators to try when splitting.
                Defaults to ["\n\n", "\n", " ", ""].
            logger: Structured logger instance.
        """
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")

        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._separators = separators or ["\n\n", "\n", " ", ""]
        self._logger = logger or structlog.get_logger(__name__)

    def chunk(self, text: str, document_id: str) -> list[DocumentChunk]:
        """Split text into chunks with position tracking.

        Args:
            text: The text content to chunk.
            document_id: The ID of the parent document.

        Returns:
            List of DocumentChunk instances with position metadata.
        """
        if not text.strip():
            return []

        self._logger.debug(
            "chunking_started",
            document_id=document_id,
            text_length=len(text),
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
        )

        raw_chunks = self._split_text(text)
        chunks = self._create_chunk_models(raw_chunks, text, document_id)

        self._logger.debug(
            "chunking_completed",
            document_id=document_id,
            chunk_count=len(chunks),
        )

        return chunks

    def _split_text(self, text: str) -> list[str]:
        """Recursively split text using separators."""
        return self._recursive_split(text, self._separators)

    def _recursive_split(self, text: str, separators: list[str]) -> list[str]:
        """Split text recursively, trying separators in order."""
        if len(text) <= self._chunk_size:
            return [text] if text.strip() else []

        if not separators:
            return self._hard_split(text)

        separator = separators[0]
        remaining_separators = separators[1:]

        # Empty separator means we should hard split
        if separator == "":
            return self._hard_split(text)

        if separator not in text:
            return self._recursive_split(text, remaining_separators)

        splits = text.split(separator)
        chunks: list[str] = []
        current_chunk = ""

        for i, split in enumerate(splits):
            candidate = current_chunk + (separator if current_chunk else "") + split

            if len(candidate) <= self._chunk_size:
                current_chunk = candidate
            else:
                if current_chunk:
                    chunks.extend(self._recursive_split(current_chunk, remaining_separators))
                    overlap_text = self._get_overlap_text(current_chunk)
                    current_chunk = overlap_text + separator + split if overlap_text else split
                else:
                    chunks.extend(self._recursive_split(split, remaining_separators))
                    current_chunk = ""

        if current_chunk.strip():
            chunks.extend(self._recursive_split(current_chunk, remaining_separators))

        return chunks

    def _hard_split(self, text: str) -> list[str]:
        """Split text at exact character boundaries when no separator works."""
        chunks: list[str] = []
        start = 0
        step = self._chunk_size - self._chunk_overlap

        while start < len(text):
            end = min(start + self._chunk_size, len(text))
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            start += step

        return chunks

    def _get_overlap_text(self, text: str) -> str:
        """Extract the overlap portion from the end of a chunk."""
        if self._chunk_overlap <= 0:
            return ""
        return text[-self._chunk_overlap :] if len(text) > self._chunk_overlap else text

    def _create_chunk_models(self, raw_chunks: list[str], original_text: str, document_id: str) -> list[DocumentChunk]:
        """Create DocumentChunk models with position metadata."""
        chunks: list[DocumentChunk] = []
        search_start = 0

        for index, chunk_text in enumerate(raw_chunks):
            char_start = original_text.find(chunk_text, search_start)
            if char_start == -1:
                char_start = search_start

            char_end = char_start + len(chunk_text)
            line_start, line_end = self._compute_line_positions(original_text, char_start, char_end)
            content_hash = self._compute_hash(chunk_text)

            chunk = DocumentChunk(
                chunk_id=str(uuid4()),
                document_id=document_id,
                chunk_index=index,
                text=chunk_text,
                content_hash=content_hash,
                char_start=char_start,
                char_end=char_end,
                line_start=line_start,
                line_end=line_end,
            )
            chunks.append(chunk)
            search_start = char_start + 1

        return chunks

    def _compute_line_positions(self, text: str, char_start: int, char_end: int) -> tuple[int, int]:
        """Compute 1-based line numbers for character positions."""
        line_start = text[:char_start].count("\n") + 1
        line_end = text[:char_end].count("\n") + 1
        return line_start, line_end

    def _compute_hash(self, text: str) -> str:
        """Compute SHA-256 hash of text content."""
        return hashlib.sha256(text.encode()).hexdigest()
