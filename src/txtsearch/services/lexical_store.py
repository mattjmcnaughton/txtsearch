"""DuckDB-based lexical search store for full-text search.

This module provides a storage layer for lexical (keyword-based) search using
DuckDB's FTS extension with BM25 ranking. The store manages document chunks
optimized for full-text search operations.

DuckDB operations are synchronous, so all database calls are wrapped with
asyncio.to_thread() to maintain async compatibility per CLAUDE.md guidelines.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import structlog


class LexicalStore:
    """Manages DuckDB FTS index for lexical search.

    Provides async interface to DuckDB's full-text search capabilities,
    including BM25-ranked queries and bulk chunk indexing. All synchronous
    DuckDB operations are wrapped with asyncio.to_thread().

    The store creates a table with an FTS index using Porter stemming,
    English stopwords, and case-insensitive matching for optimal search
    quality.
    """

    def __init__(
        self,
        db_path: Path | str,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        """Initialize lexical store.

        Args:
            db_path: Path to DuckDB file, or ":memory:" for ephemeral storage.
            logger: Structured logger instance. If None, creates one.
        """
        self._db_path = str(db_path) if db_path != ":memory:" else ":memory:"
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._logger = logger or structlog.get_logger(__name__)

    async def __aenter__(self) -> "LexicalStore":
        """Enter async context manager."""
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context manager, ensuring cleanup."""
        await self.close()

    async def initialize(self) -> None:
        """Initialize connection and create schema.

        Loads the DuckDB FTS extension, creates the document_chunks table,
        and builds the full-text search index with BM25 ranking.

        Raises:
            duckdb.Error: If extension loading or schema creation fails.
        """
        self._conn = await asyncio.to_thread(duckdb.connect, self._db_path)

        await asyncio.to_thread(self._conn.execute, "INSTALL fts")
        await asyncio.to_thread(self._conn.execute, "LOAD fts")

        await self._create_schema()

        self._logger.info("lexical_store_initialized", db_path=self._db_path)

    async def _create_schema(self) -> None:
        """Create document_chunks table and FTS index."""
        schema_sql = """
        CREATE TABLE IF NOT EXISTS document_chunks(
            document_id VARCHAR PRIMARY KEY,
            chunk_id VARCHAR NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            file_path VARCHAR NOT NULL,
            source_type VARCHAR NOT NULL,
            ingested_at TIMESTAMP NOT NULL,
            extra JSON
        );
        """
        await asyncio.to_thread(self._conn.execute, schema_sql)

        fts_sql = """
        PRAGMA create_fts_index(
            'document_chunks',
            'document_id',
            'content',
            stemmer='porter',
            stopwords='english',
            lower=1,
            overwrite=1
        );
        """
        await asyncio.to_thread(self._conn.execute, fts_sql)

    async def index_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Bulk insert chunks for FTS indexing.

        Args:
            chunks: List of chunk dictionaries with keys: document_id, chunk_id,
                chunk_index, content, file_path, source_type, ingested_at, extra.

        Returns:
            Number of chunks indexed.

        Raises:
            duckdb.Error: If insertion fails.
        """
        if not chunks:
            return 0

        insert_sql = """
        INSERT OR REPLACE INTO document_chunks
        (document_id, chunk_id, chunk_index, content, file_path, source_type, ingested_at, extra)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """

        rows = [
            (
                chunk["document_id"],
                chunk["chunk_id"],
                chunk["chunk_index"],
                chunk["content"],
                chunk["file_path"],
                chunk["source_type"],
                chunk["ingested_at"],
                chunk.get("extra", {}),
            )
            for chunk in chunks
        ]

        await asyncio.to_thread(self._conn.executemany, insert_sql, rows)

        self._logger.info("chunks_indexed", count=len(chunks))
        return len(chunks)

    async def search(
        self,
        query_text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute BM25-ranked full-text search.

        Args:
            query_text: Search query string.
            top_k: Maximum number of results to return.
            filters: Optional filters, supports "document_ids" key with list of IDs.

        Returns:
            List of result dictionaries with keys: document_id, chunk_id,
            chunk_index, content, file_path, source_type, ingested_at, extra, score.

        Raises:
            duckdb.Error: If query execution fails.
        """
        where_clauses = ["score IS NOT NULL"]
        params = [query_text]

        if filters and "document_ids" in filters:
            doc_ids = filters["document_ids"]
            if doc_ids:
                placeholders = ",".join("?" * len(doc_ids))
                where_clauses.append(f"document_id IN ({placeholders})")
                params.extend(doc_ids)

        params.append(top_k)

        where_clause = " AND ".join(where_clauses)

        search_sql = f"""
        SELECT
            document_id,
            chunk_id,
            chunk_index,
            content,
            file_path,
            source_type,
            ingested_at,
            extra,
            fts_main_document_chunks.match_bm25(document_id, ?) AS score
        FROM document_chunks
        WHERE {where_clause}
        ORDER BY score DESC
        LIMIT ?
        """

        result = await asyncio.to_thread(self._conn.execute, search_sql, params)
        rows = await asyncio.to_thread(result.fetchall)

        columns = [
            "document_id",
            "chunk_id",
            "chunk_index",
            "content",
            "file_path",
            "source_type",
            "ingested_at",
            "extra",
            "score",
        ]

        return [dict(zip(columns, row)) for row in rows]

    async def close(self) -> None:
        """Close database connection.

        Critical to call this to avoid process hangs. The connection
        must be properly closed when done.
        """
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._logger.info("lexical_store_closed")
