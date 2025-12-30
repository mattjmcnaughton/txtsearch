"""Unit tests for the LexicalSearchService."""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest

from txtsearch.models.chunk import DocumentChunk
from txtsearch.models.document import Document
from txtsearch.models.enums import SearchStrategy, SourceType
from txtsearch.models.query import Query, QueryFilters
from txtsearch.services.lexical_search import LexicalSearchService


class FakeLexicalStore:
    """In-memory fake LexicalStore for testing."""

    def __init__(self) -> None:
        self.initialized = False
        self.search_results: list[dict[str, Any]] = []
        self.last_query_text: str | None = None
        self.last_top_k: int | None = None
        self.last_filters: dict[str, Any] | None = None
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def search(
        self,
        query_text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.last_query_text = query_text
        self.last_top_k = top_k
        self.last_filters = filters
        return self.search_results

    async def close(self) -> None:
        self.closed = True


class FakeMetadataStore:
    """In-memory fake MetadataStore for testing."""

    def __init__(self) -> None:
        self.initialized = False
        self.documents: dict[str, Document] = {}
        self.closed = False

    async def initialize_schema(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True

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


class TestLexicalSearchBasic:
    """Test basic search functionality."""

    async def test_search_initializes_stores(self):
        """Test that search initializes both lexical and metadata stores."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()
        service = LexicalSearchService(lexical_store, metadata_store)

        query = Query(text="test query", strategy=SearchStrategy.LEXICAL)

        await service.initialize()

        assert lexical_store.initialized
        assert metadata_store.initialized

        await service.close()

    async def test_search_empty_query_raises_error(self):
        """Test that empty query text raises ValueError."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()
        service = LexicalSearchService(lexical_store, metadata_store)

        await service.initialize()

        with pytest.raises(ValueError, match="Query text cannot be empty"):
            await service.search(Query(text="", strategy=SearchStrategy.LEXICAL))

        await service.close()

    async def test_search_empty_results(self):
        """Test that search returns empty list when no results."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()
        service = LexicalSearchService(lexical_store, metadata_store)

        lexical_store.search_results = []

        await service.initialize()

        query = Query(text="test query", strategy=SearchStrategy.LEXICAL)
        hits = await service.search(query)

        assert hits == []

        await service.close()

    async def test_search_passes_parameters(self):
        """Test that search passes correct parameters to lexical store."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()
        service = LexicalSearchService(lexical_store, metadata_store)

        await service.initialize()

        query = Query(
            text="test query",
            strategy=SearchStrategy.LEXICAL,
            top_k=5,
            filters=QueryFilters(document_ids=["doc1", "doc2"]),
        )

        lexical_store.search_results = []
        await service.search(query)

        assert lexical_store.last_query_text == "test query"
        assert lexical_store.last_top_k == 5
        assert lexical_store.last_filters == {"document_ids": ["doc1", "doc2"]}

        await service.close()

    async def test_context_manager_lifecycle(self):
        """Test that async context manager works correctly."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()

        async with LexicalSearchService(lexical_store, metadata_store) as service:
            pass

        assert lexical_store.closed
        assert metadata_store.closed


class TestLexicalSearchHydration:
    """Test result hydration and score normalization."""

    async def test_search_normalizes_bm25_scores(self):
        """Test that BM25 scores are normalized to 0-1 range."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()
        service = LexicalSearchService(lexical_store, metadata_store)

        doc_id = str(uuid4())
        chunk_id = str(uuid4())

        metadata_store.documents[doc_id] = make_document(document_id=doc_id)

        lexical_store.search_results = [
            {
                "document_id": doc_id,
                "chunk_id": chunk_id,
                "chunk_index": 0,
                "content": "Test content",
                "file_path": "file:///test.txt",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
                "score": 10.5,
            },
            {
                "document_id": doc_id,
                "chunk_id": chunk_id,
                "chunk_index": 1,
                "content": "Other content",
                "file_path": "file:///test.txt",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
                "score": 5.25,
            },
        ]

        await service.initialize()

        query = Query(text="test", strategy=SearchStrategy.LEXICAL)
        hits = await service.search(query)

        assert len(hits) == 2
        assert 0.0 <= hits[0].score <= 1.0
        assert 0.0 <= hits[1].score <= 1.0

        assert hits[0].score >= hits[1].score

        await service.close()

    async def test_search_creates_search_hits_with_lexical_strategy(self):
        """Test that SearchHit objects use LEXICAL strategy."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()
        service = LexicalSearchService(lexical_store, metadata_store)

        doc_id = str(uuid4())
        chunk_id = str(uuid4())

        metadata_store.documents[doc_id] = make_document(document_id=doc_id)

        lexical_store.search_results = [
            {
                "document_id": doc_id,
                "chunk_id": chunk_id,
                "chunk_index": 0,
                "content": "Test content",
                "file_path": "file:///test.txt",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
                "score": 10.0,
            }
        ]

        await service.initialize()

        query = Query(text="test", strategy=SearchStrategy.LEXICAL)
        hits = await service.search(query)

        assert len(hits) == 1
        assert hits[0].strategy == SearchStrategy.LEXICAL
        assert hits[0].document_id == doc_id
        assert hits[0].chunk_id == chunk_id

        await service.close()

    async def test_search_includes_snippets_when_requested(self):
        """Test that snippets are included when include_snippets is True."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()
        service = LexicalSearchService(lexical_store, metadata_store)

        doc_id = str(uuid4())
        metadata_store.documents[doc_id] = make_document(document_id=doc_id)

        lexical_store.search_results = [
            {
                "document_id": doc_id,
                "chunk_id": str(uuid4()),
                "chunk_index": 0,
                "content": "This is test content",
                "file_path": "file:///test.txt",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
                "score": 10.0,
            }
        ]

        await service.initialize()

        query_with_snippets = Query(
            text="test",
            strategy=SearchStrategy.LEXICAL,
            include_snippets=True,
        )
        hits = await service.search(query_with_snippets)

        assert hits[0].snippet == "This is test content"

        query_without_snippets = Query(
            text="test",
            strategy=SearchStrategy.LEXICAL,
            include_snippets=False,
        )
        hits = await service.search(query_without_snippets)

        assert hits[0].snippet is None

        await service.close()

    async def test_search_includes_bm25_score_in_extra(self):
        """Test that raw BM25 score is preserved in extra field."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()
        service = LexicalSearchService(lexical_store, metadata_store)

        doc_id = str(uuid4())
        metadata_store.documents[doc_id] = make_document(document_id=doc_id)

        lexical_store.search_results = [
            {
                "document_id": doc_id,
                "chunk_id": str(uuid4()),
                "chunk_index": 0,
                "content": "Test content",
                "file_path": "file:///test.txt",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
                "score": 12.345,
            }
        ]

        await service.initialize()

        query = Query(text="test", strategy=SearchStrategy.LEXICAL)
        hits = await service.search(query)

        assert hits[0].extra["bm25_score"] == 12.345
        assert hits[0].extra["chunk_index"] == 0

        await service.close()


class TestLexicalSearchFiltering:
    """Test filtering and re-ranking."""

    async def test_search_filters_by_source_types(self):
        """Test that results are filtered by source_types."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()
        service = LexicalSearchService(lexical_store, metadata_store)

        doc1 = str(uuid4())
        doc2 = str(uuid4())

        metadata_store.documents[doc1] = make_document(
            document_id=doc1,
            source_type=SourceType.FILE,
        )
        metadata_store.documents[doc2] = make_document(
            document_id=doc2,
            source_type=SourceType.WEB,
        )

        lexical_store.search_results = [
            {
                "document_id": doc1,
                "chunk_id": str(uuid4()),
                "chunk_index": 0,
                "content": "File content",
                "file_path": "file:///test.txt",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
                "score": 10.0,
            },
            {
                "document_id": doc2,
                "chunk_id": str(uuid4()),
                "chunk_index": 0,
                "content": "Web content",
                "file_path": "https://example.com",
                "source_type": "web",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
                "score": 8.0,
            },
        ]

        await service.initialize()

        query = Query(
            text="test",
            strategy=SearchStrategy.LEXICAL,
            filters=QueryFilters(source_types={SourceType.FILE}),
        )
        hits = await service.search(query)

        assert len(hits) == 1
        assert hits[0].document_id == doc1

        await service.close()

    async def test_search_filters_by_ingested_after(self):
        """Test that results are filtered by ingested_after."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()
        service = LexicalSearchService(lexical_store, metadata_store)

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        recent_time = datetime.now(timezone.utc)
        old_time = datetime.now(timezone.utc) - timedelta(days=30)

        doc_recent = str(uuid4())
        doc_old = str(uuid4())

        metadata_store.documents[doc_recent] = make_document(
            document_id=doc_recent,
            ingested_at=recent_time,
        )
        metadata_store.documents[doc_old] = make_document(
            document_id=doc_old,
            ingested_at=old_time,
        )

        lexical_store.search_results = [
            {
                "document_id": doc_recent,
                "chunk_id": str(uuid4()),
                "chunk_index": 0,
                "content": "Recent content",
                "file_path": "file:///recent.txt",
                "source_type": "file",
                "ingested_at": recent_time,
                "extra": {},
                "score": 10.0,
            },
            {
                "document_id": doc_old,
                "chunk_id": str(uuid4()),
                "chunk_index": 0,
                "content": "Old content",
                "file_path": "file:///old.txt",
                "source_type": "file",
                "ingested_at": old_time,
                "extra": {},
                "score": 8.0,
            },
        ]

        await service.initialize()

        query = Query(
            text="test",
            strategy=SearchStrategy.LEXICAL,
            filters=QueryFilters(ingested_after=cutoff),
        )
        hits = await service.search(query)

        assert len(hits) == 1
        assert hits[0].document_id == doc_recent

        await service.close()

    async def test_search_reranks_after_filtering(self):
        """Test that ranks are sequential after filtering."""
        lexical_store = FakeLexicalStore()
        metadata_store = FakeMetadataStore()
        service = LexicalSearchService(lexical_store, metadata_store)

        doc1 = str(uuid4())
        doc2 = str(uuid4())
        doc3 = str(uuid4())

        metadata_store.documents[doc1] = make_document(
            document_id=doc1,
            source_type=SourceType.FILE,
        )
        metadata_store.documents[doc2] = make_document(
            document_id=doc2,
            source_type=SourceType.WEB,
        )
        metadata_store.documents[doc3] = make_document(
            document_id=doc3,
            source_type=SourceType.FILE,
        )

        lexical_store.search_results = [
            {
                "document_id": doc1,
                "chunk_id": str(uuid4()),
                "chunk_index": 0,
                "content": "Content 1",
                "file_path": "file:///1.txt",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
                "score": 10.0,
            },
            {
                "document_id": doc2,
                "chunk_id": str(uuid4()),
                "chunk_index": 0,
                "content": "Content 2",
                "file_path": "https://example.com",
                "source_type": "web",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
                "score": 8.0,
            },
            {
                "document_id": doc3,
                "chunk_id": str(uuid4()),
                "chunk_index": 0,
                "content": "Content 3",
                "file_path": "file:///3.txt",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
                "score": 6.0,
            },
        ]

        await service.initialize()

        query = Query(
            text="test",
            strategy=SearchStrategy.LEXICAL,
            filters=QueryFilters(source_types={SourceType.FILE}),
        )
        hits = await service.search(query)

        assert len(hits) == 2
        assert hits[0].rank == 0
        assert hits[1].rank == 1

        await service.close()
