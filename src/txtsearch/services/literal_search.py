"""Literal search service for querying files via ripgrep pattern matching.

Orchestrates ripgrep searches, hydrates results with metadata from SQLite,
and returns normalized SearchHit objects for consumption by higher layers
(CLI, API).
"""

from pathlib import Path
from uuid import uuid4

import structlog

from txtsearch.models.enums import SearchStrategy
from txtsearch.models.hit import SearchHit
from txtsearch.models.query import Query
from txtsearch.services.literal_store import (
    LiteralQueryResult,
    LiteralStore,
    RipgrepNotFoundError,
)
from txtsearch.services.metadata_store import MetadataStore


class LiteralSearchService:
    """Performs literal pattern search over files using ripgrep.

    Searches files directly using ripgrep, hydrates results with
    document metadata when available, and returns ranked SearchHit objects.
    All dependencies are injected via constructor for testability.
    """

    def __init__(
        self,
        literal_store: LiteralStore,
        metadata_store: MetadataStore,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._literal_store = literal_store
        self._metadata_store = metadata_store
        self._logger = logger or structlog.get_logger(__name__)

    async def close(self) -> None:
        """Close all resources and release connections."""
        await self._metadata_store.close()

    async def __aenter__(self) -> "LiteralSearchService":
        """Enter async context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit async context, ensuring resources are cleaned up."""
        await self.close()

    async def initialize(self) -> None:
        """Initialize underlying stores and verify ripgrep availability."""
        if not await self._literal_store.check_available():
            raise RipgrepNotFoundError()
        await self._metadata_store.initialize_schema()
        self._logger.info("literal_search_service_initialized")

    async def search(self, query: Query, directory: Path) -> list[SearchHit]:
        """Search for files matching the query pattern.

        Args:
            query: Query object containing search pattern and options.
            directory: Directory to search within.

        Returns:
            List of SearchHit objects ranked by occurrence order.

        Raises:
            ValueError: If query text is empty.
            RipgrepNotFoundError: If ripgrep is not installed.
        """
        if not query.text or not query.text.strip():
            raise ValueError("Query text cannot be empty")

        if not await self._literal_store.check_available():
            raise RipgrepNotFoundError()

        self._logger.info(
            "literal_search_started",
            query_id=query.query_id,
            pattern_length=len(query.text),
            directory=str(directory),
            top_k=query.top_k,
        )

        # Query ripgrep for matching lines
        rg_results = await self._literal_store.search(
            pattern=query.text,
            directory=directory,
            limit=query.top_k,
        )

        if not rg_results:
            self._logger.info(
                "literal_search_completed",
                query_id=query.query_id,
                hit_count=0,
            )
            return []

        # Hydrate results with document metadata
        hits = await self._hydrate_results(query, rg_results)

        self._logger.info(
            "literal_search_completed",
            query_id=query.query_id,
            hit_count=len(hits),
        )

        return hits

    async def _hydrate_results(
        self,
        query: Query,
        rg_results: list[LiteralQueryResult],
    ) -> list[SearchHit]:
        """Convert ripgrep results to SearchHit objects."""
        hits: list[SearchHit] = []

        for i, rg_result in enumerate(rg_results):
            # Try to find the document in metadata store by URI
            document = await self._metadata_store.get_document_by_uri(rg_result.path)

            document_id: str
            if document is not None:
                document_id = document.document_id
            else:
                # Generate a synthetic document ID for unindexed files
                document_id = str(uuid4())

            snippet = None
            if query.include_snippets:
                snippet = rg_result.line_text

            hit = SearchHit(
                hit_id=str(uuid4()),
                query_id=query.query_id,
                document_id=document_id,
                chunk_id=None,  # Literal search is file-level, not chunk-level
                rank=i,
                score=1.0,  # Exact matches are considered perfect relevance
                strategy=SearchStrategy.LITERAL,
                snippet=snippet,
                extra={
                    "uri": rg_result.path,
                    "line_number": rg_result.line_number,
                    "submatches": rg_result.submatches,
                },
            )
            hits.append(hit)

        return hits
