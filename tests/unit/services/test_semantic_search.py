"""Unit tests for the SemanticSearchService."""

from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4

import pytest

from txtsearch.models.chunk import DocumentChunk
from txtsearch.models.document import Document
from txtsearch.models.enums import SearchStrategy, SourceType
from txtsearch.models.query import Query, QueryFilters
from txtsearch.services.semantic_search import SemanticSearchService
from txtsearch.services.vector_store import VectorQueryResult


class FakeVectorStore:
    """In-memory fake VectorStore for testing."""

    def __init__(self) -> None:
        self.initialized = False
        self.query_results: list[VectorQueryResult] = []
        self.last_query_texts: list[str] | None = None
        self.last_n_results: int | None = None
        self.last_where: dict[str, Any] | None = None

    async def initialize(self) -> None:
        self.initialized = True

    async def query(
        self,
        query_texts: list[str],
        n_results: int = 10,
        where: dict[str, Any] | None = None,
    ) -> list[VectorQueryResult]:
        self.last_query_texts = query_texts
        self.last_n_results = n_results
        self.last_where = where
        return self.query_results


class FakeMetadataStore:
    """In-memory fake MetadataStore for testing."""

    def __init__(self) -> None:
        self.initialized = False
        self.documents: dict[str, Document] = {}
        self.chunks: dict[str, DocumentChunk] = {}
        self.closed = False

    async def initialize_schema(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True

    async def get_chunks_by_ids(self, chunk_ids: list[str]) -> list[DocumentChunk]:
        return [self.chunks[cid] for cid in chunk_ids if cid in self.chunks]

    async def get_document_by_id(self, document_id: str) -> Document | None:
        return self.documents.get(document_id)

    async def get_documents_by_ids(self, document_ids: list[str]) -> list[Document]:
        return [self.documents[did] for did in document_ids if did in self.documents]


def make_document(
    document_id: str | None = None,
    source_type: SourceType = SourceType.FILE,
    ingested_at: datetime | None = None,
) -> Document:
    """Create a test Document."""
    return Document(
        document_id=document_id or str(uuid4()),
        uri=f"file:///test/{uuid4().hex}.txt",
        display_name="test.txt",
        content_hash="a" * 64,
        size_bytes=100,
        source_type=source_type,
        ingested_at=ingested_at or datetime.now(timezone.utc),
    )


def make_chunk(
    chunk_id: str | None = None,
    document_id: str | None = None,
    chunk_index: int = 0,
    text: str = "Test chunk text",
) -> DocumentChunk:
    """Create a test DocumentChunk."""
    return DocumentChunk(
        chunk_id=chunk_id or str(uuid4()),
        document_id=document_id or str(uuid4()),
        chunk_index=chunk_index,
        text=text,
        content_hash="b" * 64,
        char_start=0,
        char_end=len(text),
        line_start=1,
        line_end=1,
    )


def make_query_result(
    ids: list[str],
    documents: list[str],
    distances: list[float],
    metadatas: list[dict[str, Any]] | None = None,
) -> VectorQueryResult:
    """Create a test VectorQueryResult."""
    return VectorQueryResult(
        ids=ids,
        documents=documents,
        metadatas=metadatas or [{} for _ in ids],
        distances=distances,
    )


@pytest.fixture
def fake_vector_store() -> FakeVectorStore:
    """Create a fake vector store."""
    return FakeVectorStore()


@pytest.fixture
def fake_metadata_store() -> FakeMetadataStore:
    """Create a fake metadata store."""
    return FakeMetadataStore()


@pytest.fixture
def search_service(
    fake_vector_store: FakeVectorStore,
    fake_metadata_store: FakeMetadataStore,
) -> SemanticSearchService:
    """Create a SemanticSearchService with fake dependencies."""
    return SemanticSearchService(
        vector_store=fake_vector_store,
        metadata_store=fake_metadata_store,
    )


class TestSemanticSearchServiceInitialization:
    """Tests for SemanticSearchService initialization."""

    def test_accepts_all_dependencies(
        self,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        service = SemanticSearchService(
            vector_store=fake_vector_store,
            metadata_store=fake_metadata_store,
        )
        assert service._vector_store is fake_vector_store
        assert service._metadata_store is fake_metadata_store

    async def test_initialize_calls_both_stores(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        await search_service.initialize()

        assert fake_vector_store.initialized
        assert fake_metadata_store.initialized

    async def test_context_manager_closes_metadata_store(
        self,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        async with SemanticSearchService(
            vector_store=fake_vector_store,
            metadata_store=fake_metadata_store,
        ):
            pass

        assert fake_metadata_store.closed


class TestSemanticSearchServiceEmptyCollection:
    """Tests for searching empty collections."""

    async def test_empty_results_returns_empty_list(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
    ) -> None:
        fake_vector_store.query_results = [make_query_result(ids=[], documents=[], distances=[])]

        query = Query(text="test query", strategy=SearchStrategy.SEMANTIC)
        hits = await search_service.search(query)

        assert hits == []

    async def test_no_results_returns_empty_list(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
    ) -> None:
        fake_vector_store.query_results = []

        query = Query(text="test query", strategy=SearchStrategy.SEMANTIC)
        hits = await search_service.search(query)

        assert hits == []


class TestSemanticSearchServiceHappyPath:
    """Tests for successful search scenarios."""

    async def test_returns_search_hits(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        chunk = make_chunk(chunk_id=chunk_id, document_id=doc_id, text="Python code")
        fake_metadata_store.chunks[chunk_id] = chunk

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk_id],
                documents=["Python code"],
                distances=[0.1],
                metadatas=[{"document_id": doc_id}],
            )
        ]

        query = Query(text="python", strategy=SearchStrategy.SEMANTIC)
        hits = await search_service.search(query)

        assert len(hits) == 1
        assert hits[0].chunk_id == chunk_id
        assert hits[0].document_id == doc_id
        assert hits[0].strategy == SearchStrategy.SEMANTIC

    async def test_returns_multiple_hits_ranked(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk1_id = str(uuid4())
        chunk2_id = str(uuid4())
        chunk3_id = str(uuid4())

        fake_metadata_store.chunks[chunk1_id] = make_chunk(chunk_id=chunk1_id, document_id=doc_id, text="First")
        fake_metadata_store.chunks[chunk2_id] = make_chunk(chunk_id=chunk2_id, document_id=doc_id, text="Second")
        fake_metadata_store.chunks[chunk3_id] = make_chunk(chunk_id=chunk3_id, document_id=doc_id, text="Third")

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk1_id, chunk2_id, chunk3_id],
                documents=["First", "Second", "Third"],
                distances=[0.1, 0.2, 0.3],
                metadatas=[{"document_id": doc_id}] * 3,
            )
        ]

        query = Query(text="test", strategy=SearchStrategy.SEMANTIC, top_k=3)
        hits = await search_service.search(query)

        assert len(hits) == 3
        assert hits[0].rank == 0
        assert hits[1].rank == 1
        assert hits[2].rank == 2

    async def test_passes_top_k_to_vector_store(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
    ) -> None:
        fake_vector_store.query_results = [make_query_result(ids=[], documents=[], distances=[])]

        query = Query(text="test", strategy=SearchStrategy.SEMANTIC, top_k=5)
        await search_service.search(query)

        assert fake_vector_store.last_n_results == 5

    async def test_includes_snippet_when_requested(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        chunk = make_chunk(chunk_id=chunk_id, document_id=doc_id, text="Snippet text")
        fake_metadata_store.chunks[chunk_id] = chunk

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk_id],
                documents=["Snippet text"],
                distances=[0.1],
                metadatas=[{"document_id": doc_id}],
            )
        ]

        query = Query(text="test", strategy=SearchStrategy.SEMANTIC, include_snippets=True)
        hits = await search_service.search(query)

        assert hits[0].snippet == "Snippet text"

    async def test_excludes_snippet_when_not_requested(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        chunk = make_chunk(chunk_id=chunk_id, document_id=doc_id, text="Snippet text")
        fake_metadata_store.chunks[chunk_id] = chunk

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk_id],
                documents=["Snippet text"],
                distances=[0.1],
                metadatas=[{"document_id": doc_id}],
            )
        ]

        query = Query(text="test", strategy=SearchStrategy.SEMANTIC, include_snippets=False)
        hits = await search_service.search(query)

        assert hits[0].snippet is None


class TestSemanticSearchServiceScoreNormalization:
    """Tests for score normalization."""

    async def test_converts_distance_to_score(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        fake_metadata_store.chunks[chunk_id] = make_chunk(chunk_id=chunk_id, document_id=doc_id)

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk_id],
                documents=["text"],
                distances=[0.0],  # Distance 0 = perfect match
                metadatas=[{"document_id": doc_id}],
            )
        ]

        query = Query(text="test", strategy=SearchStrategy.SEMANTIC)
        hits = await search_service.search(query)

        # score = 1 / (1 + 0) = 1.0
        assert hits[0].score == 1.0

    async def test_score_decreases_with_distance(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk1_id = str(uuid4())
        chunk2_id = str(uuid4())

        fake_metadata_store.chunks[chunk1_id] = make_chunk(chunk_id=chunk1_id, document_id=doc_id)
        fake_metadata_store.chunks[chunk2_id] = make_chunk(chunk_id=chunk2_id, document_id=doc_id)

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk1_id, chunk2_id],
                documents=["text1", "text2"],
                distances=[0.1, 0.5],
                metadatas=[{"document_id": doc_id}] * 2,
            )
        ]

        query = Query(text="test", strategy=SearchStrategy.SEMANTIC)
        hits = await search_service.search(query)

        assert hits[0].score is not None
        assert hits[1].score is not None
        assert hits[0].score > hits[1].score

    async def test_score_always_in_valid_range(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        fake_metadata_store.chunks[chunk_id] = make_chunk(chunk_id=chunk_id, document_id=doc_id)

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk_id],
                documents=["text"],
                distances=[100.0],  # Large distance
                metadatas=[{"document_id": doc_id}],
            )
        ]

        query = Query(text="test", strategy=SearchStrategy.SEMANTIC)
        hits = await search_service.search(query)

        # score = 1 / (1 + 100) ~= 0.0099
        assert hits[0].score is not None
        assert 0.0 < hits[0].score <= 1.0

    async def test_includes_distance_in_extra(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        fake_metadata_store.chunks[chunk_id] = make_chunk(chunk_id=chunk_id, document_id=doc_id)

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk_id],
                documents=["text"],
                distances=[0.25],
                metadatas=[{"document_id": doc_id}],
            )
        ]

        query = Query(text="test", strategy=SearchStrategy.SEMANTIC)
        hits = await search_service.search(query)

        assert hits[0].extra["distance"] == 0.25


class TestSemanticSearchServiceFiltering:
    """Tests for query filtering."""

    async def test_applies_document_ids_filter_to_vector_store(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
    ) -> None:
        fake_vector_store.query_results = [make_query_result(ids=[], documents=[], distances=[])]
        doc_id = str(uuid4())

        query = Query(
            text="test",
            strategy=SearchStrategy.SEMANTIC,
            filters=QueryFilters(document_ids=[doc_id]),
        )
        await search_service.search(query)

        assert fake_vector_store.last_where == {"document_id": doc_id}

    async def test_applies_multiple_document_ids_filter(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
    ) -> None:
        fake_vector_store.query_results = [make_query_result(ids=[], documents=[], distances=[])]
        doc_id1 = str(uuid4())
        doc_id2 = str(uuid4())

        query = Query(
            text="test",
            strategy=SearchStrategy.SEMANTIC,
            filters=QueryFilters(document_ids=[doc_id1, doc_id2]),
        )
        await search_service.search(query)

        assert fake_vector_store.last_where == {"document_id": {"$in": [doc_id1, doc_id2]}}

    async def test_filters_by_source_type(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc1_id = str(uuid4())
        doc2_id = str(uuid4())
        chunk1_id = str(uuid4())
        chunk2_id = str(uuid4())

        fake_metadata_store.documents[doc1_id] = make_document(document_id=doc1_id, source_type=SourceType.FILE)
        fake_metadata_store.documents[doc2_id] = make_document(document_id=doc2_id, source_type=SourceType.WEB)
        fake_metadata_store.chunks[chunk1_id] = make_chunk(chunk_id=chunk1_id, document_id=doc1_id)
        fake_metadata_store.chunks[chunk2_id] = make_chunk(chunk_id=chunk2_id, document_id=doc2_id)

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk1_id, chunk2_id],
                documents=["text1", "text2"],
                distances=[0.1, 0.2],
                metadatas=[{"document_id": doc1_id}, {"document_id": doc2_id}],
            )
        ]

        query = Query(
            text="test",
            strategy=SearchStrategy.SEMANTIC,
            filters=QueryFilters(source_types={SourceType.FILE}),
        )
        hits = await search_service.search(query)

        assert len(hits) == 1
        assert hits[0].document_id == doc1_id

    async def test_filters_by_ingested_after(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=7)
        new_time = now - timedelta(hours=1)
        cutoff = now - timedelta(days=1)

        doc1_id = str(uuid4())
        doc2_id = str(uuid4())
        chunk1_id = str(uuid4())
        chunk2_id = str(uuid4())

        fake_metadata_store.documents[doc1_id] = make_document(document_id=doc1_id, ingested_at=old_time)
        fake_metadata_store.documents[doc2_id] = make_document(document_id=doc2_id, ingested_at=new_time)
        fake_metadata_store.chunks[chunk1_id] = make_chunk(chunk_id=chunk1_id, document_id=doc1_id)
        fake_metadata_store.chunks[chunk2_id] = make_chunk(chunk_id=chunk2_id, document_id=doc2_id)

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk1_id, chunk2_id],
                documents=["text1", "text2"],
                distances=[0.1, 0.2],
                metadatas=[{"document_id": doc1_id}, {"document_id": doc2_id}],
            )
        ]

        query = Query(
            text="test",
            strategy=SearchStrategy.SEMANTIC,
            filters=QueryFilters(ingested_after=cutoff),
        )
        hits = await search_service.search(query)

        assert len(hits) == 1
        assert hits[0].document_id == doc2_id

    async def test_reranks_after_filtering(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc1_id = str(uuid4())
        doc2_id = str(uuid4())
        chunk1_id = str(uuid4())
        chunk2_id = str(uuid4())
        chunk3_id = str(uuid4())

        fake_metadata_store.documents[doc1_id] = make_document(document_id=doc1_id, source_type=SourceType.FILE)
        fake_metadata_store.documents[doc2_id] = make_document(document_id=doc2_id, source_type=SourceType.WEB)
        fake_metadata_store.chunks[chunk1_id] = make_chunk(chunk_id=chunk1_id, document_id=doc1_id)
        fake_metadata_store.chunks[chunk2_id] = make_chunk(chunk_id=chunk2_id, document_id=doc2_id)
        fake_metadata_store.chunks[chunk3_id] = make_chunk(chunk_id=chunk3_id, document_id=doc1_id)

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk1_id, chunk2_id, chunk3_id],
                documents=["text1", "text2", "text3"],
                distances=[0.1, 0.2, 0.3],
                metadatas=[
                    {"document_id": doc1_id},
                    {"document_id": doc2_id},
                    {"document_id": doc1_id},
                ],
            )
        ]

        query = Query(
            text="test",
            strategy=SearchStrategy.SEMANTIC,
            filters=QueryFilters(source_types={SourceType.FILE}),
        )
        hits = await search_service.search(query)

        # Should have 2 hits with sequential ranks 0, 1 (not 0, 2)
        assert len(hits) == 2
        assert hits[0].rank == 0
        assert hits[1].rank == 1


class TestSemanticSearchServiceHydration:
    """Tests for result hydration."""

    async def test_hydrates_chunk_from_metadata_store(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        chunk = make_chunk(chunk_id=chunk_id, document_id=doc_id, chunk_index=5, text="Hydrated text")
        fake_metadata_store.chunks[chunk_id] = chunk

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk_id],
                documents=["Vector text"],
                distances=[0.1],
                metadatas=[{"document_id": doc_id}],
            )
        ]

        query = Query(text="test", strategy=SearchStrategy.SEMANTIC, include_snippets=True)
        hits = await search_service.search(query)

        # Should use chunk text from metadata store
        assert hits[0].snippet == "Hydrated text"
        assert hits[0].extra["chunk_index"] == 5

    async def test_falls_back_to_vector_store_data(
        self,
        search_service: SemanticSearchService,
        fake_vector_store: FakeVectorStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        # Don't add chunk to metadata store

        fake_vector_store.query_results = [
            make_query_result(
                ids=[chunk_id],
                documents=["Fallback text"],
                distances=[0.1],
                metadatas=[{"document_id": doc_id}],
            )
        ]

        query = Query(text="test", strategy=SearchStrategy.SEMANTIC, include_snippets=True)
        hits = await search_service.search(query)

        # Should fall back to vector store document text
        assert hits[0].snippet == "Fallback text"
        assert hits[0].document_id == doc_id
