"""Lexical search service for BM25-ranked keyword search.

Orchestrates full-text search via DuckDB FTS, hydrates results with metadata
from SQLite, and returns normalized SearchHit objects for consumption by
higher layers (CLI, API, MCP).

This service mirrors the SemanticSearchService architecture but uses lexical
matching (keyword/term-based) instead of semantic similarity.
"""

from uuid import uuid4

import structlog

from txtsearch.models.document import Document
from txtsearch.models.enums import SearchStrategy
from txtsearch.models.hit import SearchHit
from txtsearch.models.query import Query
from txtsearch.services.lexical_store import LexicalStore
from txtsearch.services.metadata_store import MetadataStore


class LexicalSearchService:
    """Performs BM25-ranked lexical search over indexed documents.

    Queries DuckDB FTS for keyword matches, hydrates results with document
    metadata, and returns ranked SearchHit objects. All dependencies are
    injected via constructor for testability.
    """

    def __init__(
        self,
        lexical_store: LexicalStore,
        metadata_store: MetadataStore,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        """Initialize lexical search service.

        Args:
            lexical_store: DuckDB FTS store for lexical search.
            metadata_store: SQLite metadata store for document lookups.
            logger: Structured logger instance. If None, creates one.
        """
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
        await self._lexical_store.initialize()
        await self._metadata_store.initialize_schema()
        self._logger.info("lexical_search_service_initialized")

    async def search(self, query: Query) -> list[SearchHit]:
        """Search for documents matching query terms using BM25 ranking.

        Args:
            query: Query object containing search text, filters, and options.

        Returns:
            List of SearchHit objects ranked by BM25 score (most relevant first).

        Raises:
            ValueError: If query text is empty.
        """
        if not query.text or not query.text.strip():
            raise ValueError("Query text cannot be empty")

        self._logger.info(
            "lexical_search_started",
            query_id=query.query_id,
            text_length=len(query.text),
            top_k=query.top_k,
            has_filters=query.filters.has_filters(),
        )

        filters = {}
        if query.filters.document_ids:
            filters["document_ids"] = query.filters.document_ids

        results = await self._lexical_store.search(
            query_text=query.text,
            top_k=query.top_k,
            filters=filters,
        )

        if not results:
            self._logger.info(
                "lexical_search_completed",
                query_id=query.query_id,
                hit_count=0,
            )
            return []

        hits = await self._hydrate_results(query, results)

        hits = await self._apply_post_filters(query, hits)

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
        results: list[dict],
    ) -> list[SearchHit]:
        """Convert DuckDB FTS results to SearchHit objects.

        Normalizes BM25 scores to 0-1 range using min-max normalization
        for consistency with SearchHit validation requirements.
        """
        scores = [r["score"] for r in results]
        min_score = min(scores)
        max_score = max(scores)

        unique_doc_ids = list({r["document_id"] for r in results})
        documents = await self._metadata_store.get_documents_by_ids(unique_doc_ids)
        docs_by_id = {doc.document_id: doc for doc in documents}

        hits: list[SearchHit] = []
        for i, result in enumerate(results):
            raw_score = result["score"]
            if max_score == min_score:
                normalized_score = 1.0
            else:
                normalized_score = (raw_score - min_score) / (max_score - min_score)

            document = docs_by_id.get(result["document_id"])
            uri = document.uri if document else None

            snippet = None
            if query.include_snippets:
                snippet = result["content"]

            hit = SearchHit(
                hit_id=str(uuid4()),
                query_id=query.query_id,
                document_id=result["document_id"],
                chunk_id=result["chunk_id"],
                rank=i,
                score=normalized_score,
                strategy=SearchStrategy.LEXICAL,
                snippet=snippet,
                extra={
                    "bm25_score": raw_score,
                    "chunk_index": result["chunk_index"],
                    "uri": uri,
                },
            )
            hits.append(hit)

        return hits

    async def _apply_post_filters(
        self,
        query: Query,
        hits: list[SearchHit],
    ) -> list[SearchHit]:
        """Apply filters that require metadata store lookup."""
        if not query.filters.source_types and not query.filters.ingested_after:
            return hits

        unique_doc_ids = list({hit.document_id for hit in hits})
        documents = await self._metadata_store.get_documents_by_ids(unique_doc_ids)
        docs_by_id = {doc.document_id: doc for doc in documents}

        filtered_hits: list[SearchHit] = []
        for hit in hits:
            document = docs_by_id.get(hit.document_id)
            if document is None:
                continue

            if query.filters.source_types:
                if document.source_type not in query.filters.source_types:
                    continue

            if query.filters.ingested_after:
                if document.ingested_at < query.filters.ingested_after:
                    continue

            filtered_hits.append(hit)

        return filtered_hits

    def _rerank(self, hits: list[SearchHit]) -> list[SearchHit]:
        """Re-assign sequential ranks after filtering."""
        reranked: list[SearchHit] = []
        for i, hit in enumerate(hits):
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
