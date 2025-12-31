"""Lexical store service for DuckDB full-text search operations.

DuckDB is synchronous, so we use asyncio.to_thread() to wrap blocking
operations and maintain async consistency with other services.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import duckdb
import structlog


@dataclass(frozen=True)
class LexicalQueryResult:
    """Result of a lexical FTS query."""

    chunk_id: str
    bm25_score: float


class LexicalStore:
    """Stores and retrieves document chunks via DuckDB full-text search.

    Wraps DuckDB FTS operations with async interface using asyncio.to_thread().
    Supports both persistent (file-based) and ephemeral (:memory:) modes.
    """

    TABLE_NAME = "chunks_fts"
    FTS_INDEX_NAME = f"fts_main_{TABLE_NAME}"

    def __init__(
        self,
        db_path: Path | str,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        """Initialize the lexical store.

        Args:
            db_path: Path to DuckDB database file, or ":memory:" for in-memory.
            logger: Optional structured logger.
        """
        self._db_path = str(db_path)
        self._logger = logger or structlog.get_logger(__name__)
        self._connection: duckdb.DuckDBPyConnection | None = None

    async def initialize(self) -> None:
        """Initialize the DuckDB connection and load FTS extension."""
        await asyncio.to_thread(self._sync_initialize)

    def _sync_initialize(self) -> None:
        """Synchronous initialization of DuckDB connection."""
        self._connection = duckdb.connect(self._db_path)
        self._connection.execute("INSTALL fts")
        self._connection.execute("LOAD fts")
        self._logger.info(
            "lexical_store_initialized",
            db_path=self._db_path,
        )

    async def close(self) -> None:
        """Close the DuckDB connection."""
        if self._connection:
            await asyncio.to_thread(self._connection.close)
            self._connection = None
            self._logger.debug("lexical_store_closed")

    async def __aenter__(self) -> "LexicalStore":
        """Enter async context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context, ensuring connection is closed."""
        await self.close()

    async def add_chunks(
        self,
        chunk_ids: list[str],
        texts: list[str],
    ) -> None:
        """Add chunks to the FTS source table.

        This populates the source table. Call build_index() afterward to
        create/rebuild the FTS index.

        Args:
            chunk_ids: Unique identifiers for each chunk.
            texts: Text content for each chunk.

        Raises:
            ValueError: If input lists have mismatched lengths.
            RuntimeError: If store not initialized.
        """
        if self._connection is None:
            raise RuntimeError("LexicalStore not initialized. Call initialize() first.")

        if not chunk_ids:
            return

        if len(chunk_ids) != len(texts):
            raise ValueError(f"Mismatched lengths: chunk_ids={len(chunk_ids)}, texts={len(texts)}")

        await asyncio.to_thread(self._sync_add_chunks, chunk_ids, texts)

    def _sync_add_chunks(self, chunk_ids: list[str], texts: list[str]) -> None:
        """Synchronous chunk insertion."""
        assert self._connection is not None

        self._connection.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                chunk_id VARCHAR PRIMARY KEY,
                text VARCHAR
            )
        """)

        for chunk_id, text in zip(chunk_ids, texts, strict=True):
            self._connection.execute(
                f"""
                INSERT OR REPLACE INTO {self.TABLE_NAME} (chunk_id, text)
                VALUES (?, ?)
                """,
                [chunk_id, text],
            )

        self._logger.debug(
            "chunks_added_to_fts",
            count=len(chunk_ids),
        )

    async def build_index(self) -> None:
        """Create or rebuild the FTS index on the chunks table.

        DuckDB FTS indexes are not automatically updated when the source
        table changes, so this must be called after all chunks are added.

        Raises:
            RuntimeError: If store not initialized.
        """
        if self._connection is None:
            raise RuntimeError("LexicalStore not initialized. Call initialize() first.")

        await asyncio.to_thread(self._sync_build_index)

    def _sync_build_index(self) -> None:
        """Synchronous FTS index creation."""
        assert self._connection is not None

        self._connection.execute(f"""
            PRAGMA create_fts_index(
                '{self.TABLE_NAME}',
                'chunk_id',
                'text',
                stemmer = 'porter',
                stopwords = 'english',
                lower = 1,
                overwrite = 1
            )
        """)

        self._logger.info("fts_index_built", table=self.TABLE_NAME)

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[LexicalQueryResult]:
        """Search the FTS index for matching chunks.

        Args:
            query: Search query text.
            limit: Maximum number of results to return.

        Returns:
            List of LexicalQueryResult with chunk IDs and BM25 scores,
            ordered by relevance (highest score first).

        Raises:
            RuntimeError: If store not initialized.
        """
        if self._connection is None:
            raise RuntimeError("LexicalStore not initialized. Call initialize() first.")

        if not query or not query.strip():
            return []

        return await asyncio.to_thread(self._sync_search, query, limit)

    def _sync_search(self, query: str, limit: int) -> list[LexicalQueryResult]:
        """Synchronous FTS search."""
        assert self._connection is not None

        result = self._connection.execute(
            f"""
            SELECT chunk_id, score
            FROM (
                SELECT *, fts_main_{self.TABLE_NAME}.match_bm25(
                    chunk_id,
                    ?,
                    fields := 'text'
                ) AS score
                FROM {self.TABLE_NAME}
            ) sq
            WHERE score IS NOT NULL
            ORDER BY score DESC
            LIMIT ?
            """,
            [query, limit],
        )

        rows = result.fetchall()
        results = [LexicalQueryResult(chunk_id=row[0], bm25_score=row[1]) for row in rows]

        self._logger.debug(
            "fts_search_executed",
            query_length=len(query),
            result_count=len(results),
        )

        return results

    async def index_exists(self) -> bool:
        """Check if the FTS index exists and is ready for queries.

        Returns:
            True if the FTS index exists, False otherwise.

        Raises:
            RuntimeError: If store not initialized.
        """
        if self._connection is None:
            raise RuntimeError("LexicalStore not initialized. Call initialize() first.")

        return await asyncio.to_thread(self._sync_index_exists)

    def _sync_index_exists(self) -> bool:
        """Synchronous index existence check."""
        assert self._connection is not None

        result = self._connection.execute(
            """
            SELECT COUNT(*) FROM duckdb_tables()
            WHERE table_name = ?
        """,
            [self.TABLE_NAME],
        )
        count = result.fetchone()
        return count is not None and count[0] > 0

    async def clear(self) -> None:
        """Drop the FTS index and source table.

        Raises:
            RuntimeError: If store not initialized.
        """
        if self._connection is None:
            raise RuntimeError("LexicalStore not initialized. Call initialize() first.")

        await asyncio.to_thread(self._sync_clear)

    def _sync_clear(self) -> None:
        """Synchronous table and index clearing."""
        assert self._connection is not None

        try:
            self._connection.execute(f"PRAGMA drop_fts_index('{self.TABLE_NAME}')")
        except duckdb.CatalogException:
            pass

        try:
            self._connection.execute(f"DROP TABLE IF EXISTS {self.TABLE_NAME}")
        except duckdb.CatalogException:
            pass

        self._logger.info("lexical_store_cleared")

    async def count(self) -> int:
        """Return the number of chunks in the store.

        Returns:
            Number of stored chunks.

        Raises:
            RuntimeError: If store not initialized.
        """
        if self._connection is None:
            raise RuntimeError("LexicalStore not initialized. Call initialize() first.")

        return await asyncio.to_thread(self._sync_count)

    def _sync_count(self) -> int:
        """Synchronous count."""
        assert self._connection is not None

        try:
            result = self._connection.execute(f"SELECT COUNT(*) FROM {self.TABLE_NAME}")
            row = result.fetchone()
            return row[0] if row else 0
        except duckdb.CatalogException:
            return 0
