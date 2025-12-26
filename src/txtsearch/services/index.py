"""Indexing service that orchestrates the full ingestion pipeline.

Coordinates file discovery, content chunking, embedding storage, and metadata
persistence to create a searchable index of text files.
"""

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import structlog
from pydantic import BaseModel, Field

from txtsearch.models.chunk import DocumentChunk
from txtsearch.models.document import Document
from txtsearch.models.enums import SourceType
from txtsearch.services.chunker import Chunker
from txtsearch.services.file_walker import FileWalker
from txtsearch.services.metadata_store import MetadataStore
from txtsearch.services.vector_store import VectorStore


class IndexingResult(BaseModel):
    """Result of an indexing operation with statistics."""

    files_processed: int = Field(ge=0)
    files_skipped: int = Field(ge=0)
    chunks_created: int = Field(ge=0)
    errors: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


class FileError(BaseModel):
    """Details of a file processing error."""

    path: str
    error: str

    model_config = {"frozen": True}


class IndexingService:
    """Orchestrates the indexing pipeline for text files.

    Coordinates file discovery, content chunking, embedding storage, and
    metadata persistence. All dependencies are injected via constructor
    for testability.
    """

    def __init__(
        self,
        file_walker: FileWalker,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
        chunker: Chunker,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._file_walker = file_walker
        self._metadata_store = metadata_store
        self._vector_store = vector_store
        self._chunker = chunker
        self._logger = logger or structlog.get_logger(__name__)

    async def index_directory(self, directory: Path) -> IndexingResult:
        """Index all matching files in a directory.

        Discovers files, reads content, chunks text, generates embeddings,
        and persists both metadata and vectors.

        Args:
            directory: Root directory to index.

        Returns:
            IndexingResult with processing statistics.

        Raises:
            FileNotFoundError: If directory does not exist.
            NotADirectoryError: If path is not a directory.
        """
        self._logger.info(
            "indexing_started",
            directory=str(directory),
        )

        await self._metadata_store.initialize_schema()
        await self._vector_store.initialize()

        files_processed = 0
        files_skipped = 0
        chunks_created = 0
        errors: list[str] = []

        async for file_path in self._file_walker.walk(directory):
            result = await self._process_file(file_path, directory)
            if result is None:
                files_skipped += 1
            elif isinstance(result, FileError):
                errors.append(f"{result.path}: {result.error}")
            else:
                files_processed += 1
                chunks_created += result

        self._logger.info(
            "indexing_completed",
            directory=str(directory),
            files_processed=files_processed,
            files_skipped=files_skipped,
            chunks_created=chunks_created,
            error_count=len(errors),
        )

        return IndexingResult(
            files_processed=files_processed,
            files_skipped=files_skipped,
            chunks_created=chunks_created,
            errors=errors,
        )

    async def _process_file(self, file_path: Path, root_directory: Path) -> int | FileError | None:
        """Process a single file through the indexing pipeline.

        Args:
            file_path: Path to the file to process.
            root_directory: Root directory for relative path computation.

        Returns:
            Number of chunks created, FileError on failure, or None if skipped.
        """
        self._logger.debug(
            "file_processing_started",
            file_path=str(file_path),
        )

        try:
            content = await self._read_file(file_path)
        except (OSError, UnicodeDecodeError) as e:
            self._logger.warning(
                "file_read_error",
                file_path=str(file_path),
                error=str(e),
            )
            return FileError(path=str(file_path), error=str(e))

        if not content.strip():
            self._logger.debug(
                "file_skipped_empty",
                file_path=str(file_path),
            )
            return None

        document = self._create_document(file_path, content)
        chunks = self._chunker.chunk(content, document.document_id)

        if not chunks:
            self._logger.debug(
                "file_skipped_no_chunks",
                file_path=str(file_path),
            )
            return None

        await self._persist_document(document, chunks)

        self._logger.debug(
            "file_processing_completed",
            file_path=str(file_path),
            document_id=document.document_id,
            chunk_count=len(chunks),
        )

        return len(chunks)

    async def _read_file(self, file_path: Path) -> str:
        """Read file content asynchronously."""
        return await asyncio.to_thread(file_path.read_text, encoding="utf-8")

    def _create_document(self, file_path: Path, content: str) -> Document:
        """Create a Document model from file path and content."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        stat = file_path.stat()

        return Document(
            document_id=str(uuid4()),
            uri=file_path.as_uri(),
            display_name=file_path.name,
            content_hash=content_hash,
            size_bytes=stat.st_size,
            source_type=SourceType.FILE,
            ingested_at=datetime.now(timezone.utc),
        )

    async def _persist_document(self, document: Document, chunks: list[DocumentChunk]) -> None:
        """Persist document and chunks to both metadata and vector stores."""
        await self._metadata_store.save_document(document)
        await self._metadata_store.save_chunks(chunks)

        chunk_ids = [chunk.chunk_id for chunk in chunks]
        chunk_texts = [chunk.text for chunk in chunks]
        chunk_metadatas = [
            {
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
            }
            for chunk in chunks
        ]

        await self._vector_store.add_documents(
            ids=chunk_ids,
            documents=chunk_texts,
            metadatas=chunk_metadatas,
        )
