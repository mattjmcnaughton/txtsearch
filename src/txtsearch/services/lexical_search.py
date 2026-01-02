"""Lexical search service for querying indexed documents via DuckDB FTS.

Orchestrates full-text search via DuckDB, hydrates results with metadata
from SQLite, and returns normalized SearchHit objects for consumption by
higher layers (CLI, API).
"""

from uuid import uuid4

import structlog

from txtsearch.models.chunk import DocumentChunk
from txtsearch.models.document import Document
from txtsearch.models.enums import SearchStrategy
from txtsearch.models.hit import SearchHit
from txtsearch.models.query import Query
from txtsearch.services.lexical_store import LexicalStore
from txtsearch.services.metadata_store import MetadataStore


class LexicalIndexNotFoundError(Exception):
    """Raised when the DuckDB FTS index does not exist.

    This typically means the user needs to run indexing before searching.
    """

    def __init__(self, message: str | None = None) -> None:
        if message is None:
            message = "Lexical index not found. Run 'txtsearch index <directory>' first to build the index."
        super().__init__(message)


class LexicalSearchService:
    """Performs lexical full-text search over indexed documents.

    Queries DuckDB FTS for BM25-ranked matches, hydrates results with
    document/chunk metadata, and returns ranked SearchHit objects. All
    dependencies are injected via constructor for testability.
    """

    def __init__(
        self,
        lexical_store: LexicalStore,
        metadata_store: MetadataStore,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._lexical_store = lexical_store
        self._metadata_store = metadata_store
        self._logger = logger or structlog.get_logger(__name__)

    async def close(self) -> None:
        """Close all resources and release connections."""
        await self._lexical_store.close()
        await self._metadata_store.close()

    async def __aenter__(self) -> "LexicalSearchService":
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
        """Initialize underlying stores."""
        await self._metadata_store.initialize_schema()
        await self._lexical_store.initialize()
        self._logger.info("lexical_search_service_initialized")

    async def search(self, query: Query) -> list[SearchHit]:
        """Search for documents matching the query text.

        Args:
            query: Query object containing search text, filters, and options.

        Returns:
            List of SearchHit objects ranked by BM25 relevance (most relevant first).

        Raises:
            ValueError: If query text is empty.
            LexicalIndexNotFoundError: If the FTS index has not been built.
        """
        if not query.text or not query.text.strip():
            raise ValueError("Query text cannot be empty")

        if not await self._lexical_store.index_exists():
            raise LexicalIndexNotFoundError()

        self._logger.info(
            "lexical_search_started",
            query_id=query.query_id,
            text_length=len(query.text),
            top_k=query.top_k,
            has_filters=query.filters.has_filters(),
        )

        # Query FTS index for matching chunks
        fts_results = await self._lexical_store.search(
            query=query.text,
            limit=query.top_k,
        )

        if not fts_results:
            self._logger.info(
                "lexical_search_completed",
                query_id=query.query_id,
                hit_count=0,
            )
            return []

        # Hydrate results with chunk metadata
        hits = await self._hydrate_results(query, fts_results)

        # Apply post-query filters (source_types, ingested_after)
        hits = await self._apply_post_filters(query, hits)

        # Re-rank after filtering to maintain sequential ranks
        hits = self._rerank(hits)

        self._logger.info(
            "lexical_search_completed",
            query_id=query.query_id,
            hit_count=len(hits),
        )

        return hits

    async def _hydrate_results(
        self,
        query: Query,
        fts_results: list,
    ) -> list[SearchHit]:
        """Convert FTS query results to SearchHit objects."""
        from txtsearch.services.lexical_store import LexicalQueryResult

        chunk_ids = [r.chunk_id for r in fts_results]
        chunks_by_id: dict[str, DocumentChunk] = {}
        docs_by_id: dict[str, Document] = {}

        if chunk_ids:
            chunks = await self._metadata_store.get_chunks_by_ids(chunk_ids)
            chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}

            unique_doc_ids = list({chunk.document_id for chunk in chunks})
            documents = await self._metadata_store.get_documents_by_ids(unique_doc_ids)
            docs_by_id = {doc.document_id: doc for doc in documents}

        hits: list[SearchHit] = []
        for i, fts_result in enumerate(fts_results):
            fts_result: LexicalQueryResult
            score = self._bm25_to_score(fts_result.bm25_score)

            chunk = chunks_by_id.get(fts_result.chunk_id)
            if chunk is None:
                continue

            document = docs_by_id.get(chunk.document_id)
            uri = document.uri if document else None

            snippet = None
            if query.include_snippets:
                snippet = chunk.text

            hit = SearchHit(
                hit_id=str(uuid4()),
                query_id=query.query_id,
                document_id=chunk.document_id,
                chunk_id=fts_result.chunk_id,
                rank=i,
                score=score,
                strategy=SearchStrategy.LEXICAL,
                snippet=snippet,
                extra={
                    "bm25_score": fts_result.bm25_score,
                    "chunk_index": chunk.chunk_index,
                    "uri": uri,
                    "line_start": chunk.line_start,
                    "line_end": chunk.line_end,
                },
            )
            hits.append(hit)

        return hits

    def _bm25_to_score(self, bm25_score: float) -> float:
        """Convert BM25 score to 0-1 similarity score.

        Uses the formula: score = bm25 / (1 + bm25)
        This ensures scores are always in (0, 1) range.
        """
        return bm25_score / (1.0 + bm25_score)

    async def _apply_post_filters(
        self,
        query: Query,
        hits: list[SearchHit],
    ) -> list[SearchHit]:
        """Apply filters that require metadata store lookup."""
        if not query.filters.source_types and not query.filters.ingested_after:
            return hits

        # Bulk fetch document metadata for filtering (avoids N+1 queries)
        unique_doc_ids = list({hit.document_id for hit in hits})
        documents = await self._metadata_store.get_documents_by_ids(unique_doc_ids)
        docs_by_id = {doc.document_id: doc for doc in documents}

        filtered_hits: list[SearchHit] = []
        for hit in hits:
            document = docs_by_id.get(hit.document_id)
            if document is None:
                continue

            # Filter by source_types
            if query.filters.source_types:
                if document.source_type not in query.filters.source_types:
                    continue

            # Filter by ingested_after
            if query.filters.ingested_after:
                if document.ingested_at < query.filters.ingested_after:
                    continue

            filtered_hits.append(hit)

        return filtered_hits

    def _rerank(self, hits: list[SearchHit]) -> list[SearchHit]:
        """Re-assign sequential ranks after filtering."""
        reranked: list[SearchHit] = []
        for i, hit in enumerate(hits):
            # SearchHit is frozen, so we need to create a new instance
            reranked.append(
                SearchHit(
                    hit_id=hit.hit_id,
                    query_id=hit.query_id,
                    document_id=hit.document_id,
                    chunk_id=hit.chunk_id,
                    rank=i,
                    score=hit.score,
                    strategy=hit.strategy,
                    snippet=hit.snippet,
                    highlights=hit.highlights,
                    extra=hit.extra,
                )
            )
        return reranked
