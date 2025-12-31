"""Unit tests for the LexicalSearchService."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from txtsearch.models.chunk import DocumentChunk
from txtsearch.models.document import Document
from txtsearch.models.enums import SearchStrategy, SourceType
from txtsearch.models.query import Query, QueryFilters
from txtsearch.services.lexical_search import (
    LexicalIndexNotFoundError,
    LexicalSearchService,
)
from txtsearch.services.lexical_store import LexicalQueryResult


class FakeLexicalStore:
    """In-memory fake LexicalStore for testing."""

    def __init__(self) -> None:
        self.initialized = False
        self.closed = False
        self._index_exists = True
        self.search_results: list[LexicalQueryResult] = []
        self.last_query: str | None = None
        self.last_limit: int | None = None

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True

    async def index_exists(self) -> bool:
        return self._index_exists

    async def search(self, query: str, limit: int = 10) -> list[LexicalQueryResult]:
        self.last_query = query
        self.last_limit = limit
        return self.search_results


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
    line_start: int = 1,
    line_end: int = 1,
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
        line_start=line_start,
        line_end=line_end,
    )


def make_lexical_result(chunk_id: str, bm25_score: float) -> LexicalQueryResult:
    """Create a test LexicalQueryResult."""
    return LexicalQueryResult(chunk_id=chunk_id, bm25_score=bm25_score)


@pytest.fixture
def fake_lexical_store() -> FakeLexicalStore:
    """Create a fake lexical store."""
    return FakeLexicalStore()


@pytest.fixture
def fake_metadata_store() -> FakeMetadataStore:
    """Create a fake metadata store."""
    return FakeMetadataStore()


@pytest.fixture
def search_service(
    fake_lexical_store: FakeLexicalStore,
    fake_metadata_store: FakeMetadataStore,
) -> LexicalSearchService:
    """Create a LexicalSearchService with fake dependencies."""
    return LexicalSearchService(
        lexical_store=fake_lexical_store,
        metadata_store=fake_metadata_store,
    )


class TestLexicalSearchServiceInitialization:
    """Tests for LexicalSearchService initialization."""

    def test_accepts_all_dependencies(
        self,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        service = LexicalSearchService(
            lexical_store=fake_lexical_store,
            metadata_store=fake_metadata_store,
        )
        assert service._lexical_store is fake_lexical_store
        assert service._metadata_store is fake_metadata_store

    async def test_initialize_calls_both_stores(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        await search_service.initialize()

        assert fake_lexical_store.initialized
        assert fake_metadata_store.initialized

    async def test_context_manager_closes_stores(
        self,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        async with LexicalSearchService(
            lexical_store=fake_lexical_store,
            metadata_store=fake_metadata_store,
        ):
            pass

        assert fake_lexical_store.closed
        assert fake_metadata_store.closed


class TestLexicalSearchServiceIndexCheck:
    """Tests for FTS index existence check."""

    async def test_raises_when_index_not_found(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
    ) -> None:
        fake_lexical_store._index_exists = False

        query = Query(text="test query", strategy=SearchStrategy.LEXICAL)

        with pytest.raises(LexicalIndexNotFoundError):
            await search_service.search(query)

    async def test_proceeds_when_index_exists(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
    ) -> None:
        fake_lexical_store._index_exists = True
        fake_lexical_store.search_results = []

        query = Query(text="test query", strategy=SearchStrategy.LEXICAL)
        hits = await search_service.search(query)

        assert hits == []


class TestLexicalSearchServiceEmptyResults:
    """Tests for searching with no results."""

    async def test_empty_results_returns_empty_list(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
    ) -> None:
        fake_lexical_store.search_results = []

        query = Query(text="test query", strategy=SearchStrategy.LEXICAL)
        hits = await search_service.search(query)

        assert hits == []

    def test_empty_query_rejected_by_model(self) -> None:
        # Query model validates text cannot be empty at construction
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="cannot be empty"):
            Query(text="", strategy=SearchStrategy.LEXICAL)

    def test_whitespace_query_rejected_by_model(self) -> None:
        # Query model validates text cannot be whitespace-only at construction
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="cannot be empty"):
            Query(text="   ", strategy=SearchStrategy.LEXICAL)


class TestLexicalSearchServiceHappyPath:
    """Tests for successful search scenarios."""

    async def test_returns_search_hits(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        chunk = make_chunk(chunk_id=chunk_id, document_id=doc_id, text="Python code")
        fake_metadata_store.chunks[chunk_id] = chunk

        fake_lexical_store.search_results = [make_lexical_result(chunk_id=chunk_id, bm25_score=2.5)]

        query = Query(text="python", strategy=SearchStrategy.LEXICAL)
        hits = await search_service.search(query)

        assert len(hits) == 1
        assert hits[0].chunk_id == chunk_id
        assert hits[0].document_id == doc_id
        assert hits[0].strategy == SearchStrategy.LEXICAL

    async def test_returns_multiple_hits_ranked(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk1_id = str(uuid4())
        chunk2_id = str(uuid4())
        chunk3_id = str(uuid4())

        fake_metadata_store.chunks[chunk1_id] = make_chunk(chunk_id=chunk1_id, document_id=doc_id, text="First")
        fake_metadata_store.chunks[chunk2_id] = make_chunk(chunk_id=chunk2_id, document_id=doc_id, text="Second")
        fake_metadata_store.chunks[chunk3_id] = make_chunk(chunk_id=chunk3_id, document_id=doc_id, text="Third")

        fake_lexical_store.search_results = [
            make_lexical_result(chunk1_id, bm25_score=3.0),
            make_lexical_result(chunk2_id, bm25_score=2.0),
            make_lexical_result(chunk3_id, bm25_score=1.0),
        ]

        query = Query(text="test", strategy=SearchStrategy.LEXICAL, top_k=3)
        hits = await search_service.search(query)

        assert len(hits) == 3
        assert hits[0].rank == 0
        assert hits[1].rank == 1
        assert hits[2].rank == 2

    async def test_passes_top_k_to_lexical_store(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
    ) -> None:
        fake_lexical_store.search_results = []

        query = Query(text="test", strategy=SearchStrategy.LEXICAL, top_k=5)
        await search_service.search(query)

        assert fake_lexical_store.last_limit == 5

    async def test_includes_snippet_when_requested(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        chunk = make_chunk(chunk_id=chunk_id, document_id=doc_id, text="Snippet text")
        fake_metadata_store.chunks[chunk_id] = chunk

        fake_lexical_store.search_results = [make_lexical_result(chunk_id=chunk_id, bm25_score=1.5)]

        query = Query(text="test", strategy=SearchStrategy.LEXICAL, include_snippets=True)
        hits = await search_service.search(query)

        assert hits[0].snippet == "Snippet text"

    async def test_excludes_snippet_when_not_requested(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        chunk = make_chunk(chunk_id=chunk_id, document_id=doc_id, text="Snippet text")
        fake_metadata_store.chunks[chunk_id] = chunk

        fake_lexical_store.search_results = [make_lexical_result(chunk_id=chunk_id, bm25_score=1.5)]

        query = Query(text="test", strategy=SearchStrategy.LEXICAL, include_snippets=False)
        hits = await search_service.search(query)

        assert hits[0].snippet is None


class TestLexicalSearchServiceScoreNormalization:
    """Tests for BM25 score normalization."""

    async def test_converts_bm25_to_score(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        fake_metadata_store.chunks[chunk_id] = make_chunk(chunk_id=chunk_id, document_id=doc_id)

        fake_lexical_store.search_results = [make_lexical_result(chunk_id=chunk_id, bm25_score=1.0)]

        query = Query(text="test", strategy=SearchStrategy.LEXICAL)
        hits = await search_service.search(query)

        # score = 1.0 / (1.0 + 1.0) = 0.5
        assert hits[0].score == 0.5

    async def test_higher_bm25_gives_higher_score(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk1_id = str(uuid4())
        chunk2_id = str(uuid4())

        fake_metadata_store.chunks[chunk1_id] = make_chunk(chunk_id=chunk1_id, document_id=doc_id)
        fake_metadata_store.chunks[chunk2_id] = make_chunk(chunk_id=chunk2_id, document_id=doc_id)

        fake_lexical_store.search_results = [
            make_lexical_result(chunk1_id, bm25_score=5.0),
            make_lexical_result(chunk2_id, bm25_score=1.0),
        ]

        query = Query(text="test", strategy=SearchStrategy.LEXICAL)
        hits = await search_service.search(query)

        assert hits[0].score is not None
        assert hits[1].score is not None
        assert hits[0].score > hits[1].score

    async def test_score_always_in_valid_range(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        fake_metadata_store.chunks[chunk_id] = make_chunk(chunk_id=chunk_id, document_id=doc_id)

        fake_lexical_store.search_results = [make_lexical_result(chunk_id=chunk_id, bm25_score=100.0)]

        query = Query(text="test", strategy=SearchStrategy.LEXICAL)
        hits = await search_service.search(query)

        # score = 100 / (1 + 100) ~= 0.99
        assert hits[0].score is not None
        assert 0.0 < hits[0].score <= 1.0

    async def test_includes_bm25_score_in_extra(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        fake_metadata_store.chunks[chunk_id] = make_chunk(chunk_id=chunk_id, document_id=doc_id)

        fake_lexical_store.search_results = [make_lexical_result(chunk_id=chunk_id, bm25_score=2.5)]

        query = Query(text="test", strategy=SearchStrategy.LEXICAL)
        hits = await search_service.search(query)

        assert hits[0].extra["bm25_score"] == 2.5

    async def test_includes_uri_in_extra(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        test_uri = f"file:///test/{doc_id}.txt"

        fake_metadata_store.documents[doc_id] = Document(
            document_id=doc_id,
            uri=test_uri,
            display_name="test.txt",
            content_hash="a" * 64,
            size_bytes=100,
            source_type=SourceType.FILE,
            ingested_at=datetime.now(timezone.utc),
        )
        fake_metadata_store.chunks[chunk_id] = make_chunk(chunk_id=chunk_id, document_id=doc_id)

        fake_lexical_store.search_results = [make_lexical_result(chunk_id=chunk_id, bm25_score=1.0)]

        query = Query(text="test", strategy=SearchStrategy.LEXICAL)
        hits = await search_service.search(query)

        assert hits[0].extra["uri"] == test_uri

    async def test_includes_line_numbers_in_extra(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        fake_metadata_store.chunks[chunk_id] = make_chunk(
            chunk_id=chunk_id, document_id=doc_id, line_start=10, line_end=20
        )

        fake_lexical_store.search_results = [make_lexical_result(chunk_id=chunk_id, bm25_score=1.0)]

        query = Query(text="test", strategy=SearchStrategy.LEXICAL)
        hits = await search_service.search(query)

        assert hits[0].extra["line_start"] == 10
        assert hits[0].extra["line_end"] == 20


class TestLexicalSearchServiceFiltering:
    """Tests for query filtering."""

    async def test_filters_by_source_type(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
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

        fake_lexical_store.search_results = [
            make_lexical_result(chunk1_id, bm25_score=2.0),
            make_lexical_result(chunk2_id, bm25_score=1.0),
        ]

        query = Query(
            text="test",
            strategy=SearchStrategy.LEXICAL,
            filters=QueryFilters(source_types={SourceType.FILE}),
        )
        hits = await search_service.search(query)

        assert len(hits) == 1
        assert hits[0].document_id == doc1_id

    async def test_filters_by_ingested_after(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
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

        fake_lexical_store.search_results = [
            make_lexical_result(chunk1_id, bm25_score=2.0),
            make_lexical_result(chunk2_id, bm25_score=1.0),
        ]

        query = Query(
            text="test",
            strategy=SearchStrategy.LEXICAL,
            filters=QueryFilters(ingested_after=cutoff),
        )
        hits = await search_service.search(query)

        assert len(hits) == 1
        assert hits[0].document_id == doc2_id

    async def test_reranks_after_filtering(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
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

        fake_lexical_store.search_results = [
            make_lexical_result(chunk1_id, bm25_score=3.0),
            make_lexical_result(chunk2_id, bm25_score=2.0),
            make_lexical_result(chunk3_id, bm25_score=1.0),
        ]

        query = Query(
            text="test",
            strategy=SearchStrategy.LEXICAL,
            filters=QueryFilters(source_types={SourceType.FILE}),
        )
        hits = await search_service.search(query)

        # Should have 2 hits with sequential ranks 0, 1 (not 0, 2)
        assert len(hits) == 2
        assert hits[0].rank == 0
        assert hits[1].rank == 1


class TestLexicalSearchServiceHydration:
    """Tests for result hydration."""

    async def test_hydrates_chunk_from_metadata_store(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk_id = str(uuid4())
        chunk = make_chunk(chunk_id=chunk_id, document_id=doc_id, chunk_index=5, text="Hydrated text")
        fake_metadata_store.chunks[chunk_id] = chunk

        fake_lexical_store.search_results = [make_lexical_result(chunk_id=chunk_id, bm25_score=1.5)]

        query = Query(text="test", strategy=SearchStrategy.LEXICAL, include_snippets=True)
        hits = await search_service.search(query)

        # Should use chunk text from metadata store
        assert hits[0].snippet == "Hydrated text"
        assert hits[0].extra["chunk_index"] == 5

    async def test_skips_chunks_not_in_metadata_store(
        self,
        search_service: LexicalSearchService,
        fake_lexical_store: FakeLexicalStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc_id = str(uuid4())
        chunk1_id = str(uuid4())
        chunk2_id = str(uuid4())

        # Only add chunk1 to metadata store
        fake_metadata_store.chunks[chunk1_id] = make_chunk(chunk_id=chunk1_id, document_id=doc_id)

        fake_lexical_store.search_results = [
            make_lexical_result(chunk1_id, bm25_score=2.0),
            make_lexical_result(chunk2_id, bm25_score=1.0),  # Not in metadata
        ]

        query = Query(text="test", strategy=SearchStrategy.LEXICAL)
        hits = await search_service.search(query)

        # Should only return chunk1
        assert len(hits) == 1
        assert hits[0].chunk_id == chunk1_id


class TestLexicalIndexNotFoundError:
    """Tests for the LexicalIndexNotFoundError exception."""

    def test_default_message(self) -> None:
        error = LexicalIndexNotFoundError()
        assert "Lexical index not found" in str(error)
        assert "txtsearch index" in str(error)

    def test_custom_message(self) -> None:
        error = LexicalIndexNotFoundError("Custom error message")
        assert str(error) == "Custom error message"
