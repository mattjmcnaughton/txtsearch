"""Metadata store service for persisting documents and chunks to SQLite.

Uses SQLAlchemy's native async support with aiosqlite for non-blocking
database operations. This avoids thread pool overhead from asyncio.to_thread().
"""

from datetime import timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlmodel import SQLModel

from txtsearch.models.chunk import DocumentChunk
from txtsearch.models.document import Document
from txtsearch.models.enums import SourceType
from txtsearch.models.tables import ChunkRecord, DocumentRecord


class MetadataStore:
    """Persists document and chunk metadata to SQLite via SQLModel.

    Uses native async SQLAlchemy with aiosqlite for true async I/O.
    Accepts an AsyncEngine via dependency injection to support both
    persistent and in-memory databases for testing.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._engine = engine
        self._logger = logger or structlog.get_logger(__name__)

    async def initialize_schema(self) -> None:
        """Create database tables if they don't exist."""
        async with self._engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        self._logger.info("metadata_store_initialized")

    async def save_document(self, document: Document) -> None:
        """Persist a document to the database.

        Args:
            document: The Document domain model to persist.
        """
        record = self._document_to_record(document)
        async with AsyncSession(self._engine) as session:
            existing = await session.get(DocumentRecord, record.document_id)
            if existing:
                existing.schema_version = record.schema_version
                existing.uri = record.uri
                existing.display_name = record.display_name
                existing.content_hash = record.content_hash
                existing.size_bytes = record.size_bytes
                existing.source_type = record.source_type
                existing.extra = record.extra
                existing.ingested_at = record.ingested_at
            else:
                session.add(record)
            await session.commit()
        self._logger.debug(
            "document_saved",
            document_id=document.document_id,
            uri=document.uri,
        )

    async def save_chunks(self, chunks: list[DocumentChunk]) -> None:
        """Persist multiple chunks to the database.

        Args:
            chunks: List of DocumentChunk domain models to persist.
        """
        if not chunks:
            return

        records = [self._chunk_to_record(chunk) for chunk in chunks]
        async with AsyncSession(self._engine) as session:
            for record in records:
                existing = await session.get(ChunkRecord, record.chunk_id)
                if existing:
                    await session.delete(existing)
            session.add_all(records)
            await session.commit()
        self._logger.debug(
            "chunks_saved",
            document_id=chunks[0].document_id,
            chunk_count=len(chunks),
        )

    async def get_document_by_uri(self, uri: str) -> Document | None:
        """Retrieve a document by its URI.

        Args:
            uri: The document URI to look up.

        Returns:
            The Document if found, None otherwise.
        """
        async with AsyncSession(self._engine) as session:
            statement = select(DocumentRecord).where(DocumentRecord.uri == uri)
            result = await session.execute(statement)
            record = result.scalar_one_or_none()
            if record is None:
                return None
            return self._record_to_document(record)

    async def get_document_by_id(self, document_id: str) -> Document | None:
        """Retrieve a document by its ID.

        Args:
            document_id: The document ID to look up.

        Returns:
            The Document if found, None otherwise.
        """
        async with AsyncSession(self._engine) as session:
            record = await session.get(DocumentRecord, document_id)
            if record is None:
                return None
            return self._record_to_document(record)

    async def get_chunks_by_document_id(self, document_id: str) -> list[DocumentChunk]:
        """Retrieve all chunks for a document.

        Args:
            document_id: The document ID to fetch chunks for.

        Returns:
            List of DocumentChunk models for the document.
        """
        async with AsyncSession(self._engine) as session:
            statement = (
                select(ChunkRecord).where(ChunkRecord.document_id == document_id).order_by(ChunkRecord.chunk_index)
            )
            result = await session.execute(statement)
            records = result.scalars().all()
            return [self._record_to_chunk(r) for r in records]

    async def delete_document(self, document_id: str) -> bool:
        """Delete a document and its chunks.

        Args:
            document_id: The document ID to delete.

        Returns:
            True if document was deleted, False if not found.
        """
        async with AsyncSession(self._engine) as session:
            document = await session.get(DocumentRecord, document_id)
            if document is None:
                return False

            # Delete associated chunks first
            chunk_statement = select(ChunkRecord).where(ChunkRecord.document_id == document_id)
            result = await session.execute(chunk_statement)
            for chunk in result.scalars():
                await session.delete(chunk)

            await session.delete(document)
            await session.commit()

        self._logger.debug("document_deleted", document_id=document_id)
        return True

    def _document_to_record(self, document: Document) -> DocumentRecord:
        """Convert domain Document to SQLModel record.

        Uses Pydantic serialization with explicit enum-to-string conversion.
        """
        data = document.model_dump()
        # Convert SourceType enum to its string value for database storage
        data["source_type"] = document.source_type.value
        return DocumentRecord.model_validate(data)

    def _record_to_document(self, record: DocumentRecord) -> Document:
        """Convert SQLModel record to domain Document.

        Uses Pydantic validation which handles string-to-enum conversion.
        SQLite doesn't preserve timezone info, so we restore UTC timezone.
        """
        data = record.model_dump()
        # Convert string back to SourceType enum
        data["source_type"] = SourceType(data["source_type"])
        # Restore timezone (SQLite stores naive datetimes)
        if data["ingested_at"].tzinfo is None:
            data["ingested_at"] = data["ingested_at"].replace(tzinfo=timezone.utc)
        return Document.model_validate(data)

    def _chunk_to_record(self, chunk: DocumentChunk) -> ChunkRecord:
        """Convert domain DocumentChunk to SQLModel record."""
        return ChunkRecord.model_validate(chunk.model_dump())

    def _record_to_chunk(self, record: ChunkRecord) -> DocumentChunk:
        """Convert SQLModel record to domain DocumentChunk."""
        return DocumentChunk.model_validate(record.model_dump())


def create_async_engine_from_path(db_path: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine for the given database path.

    Args:
        db_path: Path to SQLite database file, or ":memory:" for in-memory.

    Returns:
        AsyncEngine instance configured for aiosqlite.
    """
    if db_path == ":memory:":
        # For in-memory async SQLite, we need special handling to share
        # the connection across the async session lifecycle
        url = "sqlite+aiosqlite:///:memory:"
    else:
        url = f"sqlite+aiosqlite:///{db_path}"
    return create_async_engine(url)
