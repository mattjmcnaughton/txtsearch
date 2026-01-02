"""Semantic search service for querying indexed documents.

Orchestrates vector similarity search via ChromaDB, hydrates results with
metadata from SQLite, and returns normalized SearchHit objects for consumption
by higher layers (CLI, API).
"""

from uuid import uuid4

import structlog

from txtsearch.models.chunk import DocumentChunk
from txtsearch.models.document import Document
from txtsearch.models.enums import SearchStrategy
from txtsearch.models.hit import SearchHit
from txtsearch.models.query import Query
from txtsearch.services.metadata_store import MetadataStore
from txtsearch.services.vector_store import VectorQueryResult, VectorStore


class SemanticSearchService:
    """Performs semantic similarity search over indexed documents.

    Queries ChromaDB for nearest neighbor embeddings, hydrates results with
    document/chunk metadata, and returns ranked SearchHit objects. All
    dependencies are injected via constructor for testability.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        metadata_store: MetadataStore,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._metadata_store = metadata_store
        self._logger = logger or structlog.get_logger(__name__)

    async def close(self) -> None:
        """Close all resources and release connections."""
        await self._metadata_store.close()

    async def __aenter__(self) -> "SemanticSearchService":
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
        await self._vector_store.initialize()
        self._logger.info("semantic_search_service_initialized")

    async def search(self, query: Query) -> list[SearchHit]:
        """Search for documents similar to the query text.

        Args:
            query: Query object containing search text, filters, and options.

        Returns:
            List of SearchHit objects ranked by similarity (most similar first).

        Raises:
            ValueError: If query text is empty.
        """
        if not query.text or not query.text.strip():
            raise ValueError("Query text cannot be empty")

        self._logger.info(
            "search_started",
            query_id=query.query_id,
            text_length=len(query.text),
            top_k=query.top_k,
            has_filters=query.filters.has_filters(),
        )

        # Build ChromaDB where clause from document_ids filter
        where_clause = self._build_where_clause(query)

        # Query vector store for nearest neighbors
        results = await self._vector_store.query(
            query_texts=[query.text],
            n_results=query.top_k,
            where=where_clause,
        )

        if not results or not results[0].ids:
            self._logger.info(
                "search_completed",
                query_id=query.query_id,
                hit_count=0,
            )
            return []

        # Get the single query result (we only pass one query text)
        vector_result = results[0]

        # Hydrate results with chunk metadata
        hits = await self._hydrate_results(query, vector_result)

        # Apply post-query filters (source_types, ingested_after)
        hits = await self._apply_post_filters(query, hits)

        # Re-rank after filtering to maintain sequential ranks
        hits = self._rerank(hits)

        self._logger.info(
            "search_completed",
            query_id=query.query_id,
            hit_count=len(hits),
        )

        return hits

    def _build_where_clause(self, query: Query) -> dict | None:
        """Build ChromaDB where clause from query filters."""
        if not query.filters.document_ids:
            return None

        if len(query.filters.document_ids) == 1:
            return {"document_id": query.filters.document_ids[0]}

        return {"document_id": {"$in": query.filters.document_ids}}

    async def _hydrate_results(
        self,
        query: Query,
        vector_result: VectorQueryResult,
    ) -> list[SearchHit]:
        """Convert vector query results to SearchHit objects."""

        chunk_ids = vector_result.ids
        chunks_by_id: dict[str, DocumentChunk] = {}
        docs_by_id: dict[str, Document] = {}

        if chunk_ids:
            chunks = await self._metadata_store.get_chunks_by_ids(chunk_ids)
            chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}

            unique_doc_ids = list({chunk.document_id for chunk in chunks})
            documents = await self._metadata_store.get_documents_by_ids(unique_doc_ids)
            docs_by_id = {doc.document_id: doc for doc in documents}

        hits: list[SearchHit] = []
        for i, chunk_id in enumerate(chunk_ids):
            distance = vector_result.distances[i]
            score = self._distance_to_score(distance)

            chunk = chunks_by_id.get(chunk_id)
            document_id = chunk.document_id if chunk else vector_result.metadatas[i].get("document_id", "")

            document = docs_by_id.get(document_id)
            uri = document.uri if document else None

            snippet = None
            if query.include_snippets:
                snippet = chunk.text if chunk else vector_result.documents[i] if vector_result.documents else None

            hit = SearchHit(
                hit_id=str(uuid4()),
                query_id=query.query_id,
                document_id=document_id,
                chunk_id=chunk_id,
                rank=i,
                score=score,
                strategy=SearchStrategy.SEMANTIC,
                snippet=snippet,
                extra={
                    "distance": distance,
                    "chunk_index": chunk.chunk_index if chunk else None,
                    "uri": uri,
                },
            )
            hits.append(hit)

        return hits

    def _distance_to_score(self, distance: float) -> float:
        """Convert ChromaDB distance to 0-1 similarity score.

        Uses the formula: score = 1 / (1 + distance)
        This ensures scores are always in (0, 1] range.
        """
        return 1.0 / (1.0 + distance)

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
