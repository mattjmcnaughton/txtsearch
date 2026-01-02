"""Unit tests for the LiteralSearchService."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from txtsearch.models.document import Document
from txtsearch.models.enums import SearchStrategy, SourceType
from txtsearch.models.query import Query
from txtsearch.services.literal_search import LiteralSearchService
from txtsearch.services.literal_store import LiteralQueryResult, RipgrepNotFoundError


class FakeLiteralStore:
    """In-memory fake LiteralStore for testing."""

    def __init__(self) -> None:
        self.rg_available = True
        self.search_results: list[LiteralQueryResult] = []
        self.last_pattern: str | None = None
        self.last_directory: Path | None = None
        self.last_limit: int | None = None

    async def check_available(self) -> bool:
        return self.rg_available

    async def search(
        self,
        pattern: str,
        directory: Path,
        limit: int = 10,
    ) -> list[LiteralQueryResult]:
        self.last_pattern = pattern
        self.last_directory = directory
        self.last_limit = limit
        return self.search_results


class FakeMetadataStore:
    """In-memory fake MetadataStore for testing."""

    def __init__(self) -> None:
        self.initialized = False
        self.documents: dict[str, Document] = {}
        self.documents_by_uri: dict[str, Document] = {}
        self.closed = False

    async def initialize_schema(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True

    async def get_document_by_uri(self, uri: str) -> Document | None:
        return self.documents_by_uri.get(uri)

    async def get_document_by_id(self, document_id: str) -> Document | None:
        return self.documents.get(document_id)


def make_document(
    document_id: str | None = None,
    uri: str | None = None,
    source_type: SourceType = SourceType.FILE,
) -> Document:
    """Create a test Document."""
    doc_id = document_id or str(uuid4())
    return Document(
        document_id=doc_id,
        uri=uri or f"/test/{doc_id}.txt",
        display_name="test.txt",
        content_hash="a" * 64,
        size_bytes=100,
        source_type=source_type,
        ingested_at=datetime.now(timezone.utc),
    )


def make_literal_result(
    path: str,
    line_number: int,
    line_text: str,
    submatches: list[tuple[int, int]] | None = None,
) -> LiteralQueryResult:
    """Create a test LiteralQueryResult."""
    return LiteralQueryResult(
        path=path,
        line_number=line_number,
        line_text=line_text,
        submatches=submatches or [],
    )


@pytest.fixture
def fake_literal_store() -> FakeLiteralStore:
    """Create a fake literal store."""
    return FakeLiteralStore()


@pytest.fixture
def fake_metadata_store() -> FakeMetadataStore:
    """Create a fake metadata store."""
    return FakeMetadataStore()


@pytest.fixture
def search_service(
    fake_literal_store: FakeLiteralStore,
    fake_metadata_store: FakeMetadataStore,
) -> LiteralSearchService:
    """Create a LiteralSearchService with fake dependencies."""
    return LiteralSearchService(
        literal_store=fake_literal_store,
        metadata_store=fake_metadata_store,
    )


class TestLiteralSearchServiceInitialization:
    """Tests for LiteralSearchService initialization."""

    def test_accepts_all_dependencies(
        self,
        fake_literal_store: FakeLiteralStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        service = LiteralSearchService(
            literal_store=fake_literal_store,
            metadata_store=fake_metadata_store,
        )
        assert service._literal_store is fake_literal_store
        assert service._metadata_store is fake_metadata_store

    async def test_initialize_checks_ripgrep_available(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        fake_literal_store.rg_available = True

        await search_service.initialize()

        assert fake_metadata_store.initialized

    async def test_initialize_raises_when_ripgrep_not_available(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.rg_available = False

        with pytest.raises(RipgrepNotFoundError):
            await search_service.initialize()

    async def test_context_manager_closes_metadata_store(
        self,
        fake_literal_store: FakeLiteralStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        async with LiteralSearchService(
            literal_store=fake_literal_store,
            metadata_store=fake_metadata_store,
        ):
            pass

        assert fake_metadata_store.closed


class TestLiteralSearchServiceRipgrepCheck:
    """Tests for ripgrep availability check."""

    async def test_raises_when_ripgrep_not_available(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.rg_available = False

        query = Query(text="test", strategy=SearchStrategy.LITERAL)

        with pytest.raises(RipgrepNotFoundError):
            await search_service.search(query, Path("/tmp"))

    async def test_proceeds_when_ripgrep_available(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.rg_available = True
        fake_literal_store.search_results = []

        query = Query(text="test", strategy=SearchStrategy.LITERAL)
        hits = await search_service.search(query, Path("/tmp"))

        assert hits == []


class TestLiteralSearchServiceEmptyResults:
    """Tests for searching with no results."""

    async def test_empty_results_returns_empty_list(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = []

        query = Query(text="nonexistent", strategy=SearchStrategy.LITERAL)
        hits = await search_service.search(query, Path("/tmp"))

        assert hits == []

    async def test_raises_on_empty_query_text(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        # Query model validates text cannot be empty at construction
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="cannot be empty"):
            Query(text="", strategy=SearchStrategy.LITERAL)


class TestLiteralSearchServiceHappyPath:
    """Tests for successful search scenarios."""

    async def test_returns_search_hits(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc = make_document(uri="/tmp/test.py")
        fake_metadata_store.documents[doc.document_id] = doc
        fake_metadata_store.documents_by_uri[doc.uri] = doc

        fake_literal_store.search_results = [
            make_literal_result(
                path="/tmp/test.py",
                line_number=42,
                line_text="def test_function():",
            )
        ]

        query = Query(text="test", strategy=SearchStrategy.LITERAL)
        hits = await search_service.search(query, Path("/tmp"))

        assert len(hits) == 1
        assert hits[0].document_id == doc.document_id
        assert hits[0].chunk_id is None  # Literal search is file-level
        assert hits[0].strategy == SearchStrategy.LITERAL
        assert hits[0].score == 1.0

    async def test_returns_multiple_hits_ranked(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = [
            make_literal_result("/tmp/a.py", 1, "first match"),
            make_literal_result("/tmp/b.py", 5, "second match"),
            make_literal_result("/tmp/c.py", 10, "third match"),
        ]

        query = Query(text="match", strategy=SearchStrategy.LITERAL, top_k=3)
        hits = await search_service.search(query, Path("/tmp"))

        assert len(hits) == 3
        assert hits[0].rank == 0
        assert hits[1].rank == 1
        assert hits[2].rank == 2

    async def test_passes_top_k_to_literal_store(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = []

        query = Query(text="test", strategy=SearchStrategy.LITERAL, top_k=5)
        await search_service.search(query, Path("/tmp"))

        assert fake_literal_store.last_limit == 5

    async def test_passes_pattern_to_literal_store(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = []

        query = Query(text="my_pattern", strategy=SearchStrategy.LITERAL)
        await search_service.search(query, Path("/tmp"))

        assert fake_literal_store.last_pattern == "my_pattern"

    async def test_passes_directory_to_literal_store(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = []

        query = Query(text="test", strategy=SearchStrategy.LITERAL)
        await search_service.search(query, Path("/some/directory"))

        assert fake_literal_store.last_directory == Path("/some/directory")

    async def test_includes_snippet_when_requested(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = [make_literal_result("/tmp/test.py", 1, "snippet text here")]

        query = Query(text="test", strategy=SearchStrategy.LITERAL, include_snippets=True)
        hits = await search_service.search(query, Path("/tmp"))

        assert hits[0].snippet == "snippet text here"

    async def test_excludes_snippet_when_not_requested(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = [make_literal_result("/tmp/test.py", 1, "snippet text here")]

        query = Query(text="test", strategy=SearchStrategy.LITERAL, include_snippets=False)
        hits = await search_service.search(query, Path("/tmp"))

        assert hits[0].snippet is None


class TestLiteralSearchServiceExtraFields:
    """Tests for extra field population."""

    async def test_includes_uri_in_extra(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = [make_literal_result("/tmp/test.py", 42, "some line")]

        query = Query(text="test", strategy=SearchStrategy.LITERAL)
        hits = await search_service.search(query, Path("/tmp"))

        assert hits[0].extra["uri"] == "/tmp/test.py"

    async def test_includes_line_number_in_extra(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = [make_literal_result("/tmp/test.py", 42, "some line")]

        query = Query(text="test", strategy=SearchStrategy.LITERAL)
        hits = await search_service.search(query, Path("/tmp"))

        assert hits[0].extra["line_number"] == 42

    async def test_includes_submatches_in_extra(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = [
            make_literal_result("/tmp/test.py", 1, "test test", submatches=[(0, 4), (5, 9)])
        ]

        query = Query(text="test", strategy=SearchStrategy.LITERAL)
        hits = await search_service.search(query, Path("/tmp"))

        assert hits[0].extra["submatches"] == [(0, 4), (5, 9)]


class TestLiteralSearchServiceDocumentLookup:
    """Tests for document metadata lookup."""

    async def test_uses_document_id_from_metadata_when_found(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        doc = make_document(uri="/tmp/known.py")
        fake_metadata_store.documents[doc.document_id] = doc
        fake_metadata_store.documents_by_uri[doc.uri] = doc

        fake_literal_store.search_results = [make_literal_result("/tmp/known.py", 1, "match")]

        query = Query(text="test", strategy=SearchStrategy.LITERAL)
        hits = await search_service.search(query, Path("/tmp"))

        assert hits[0].document_id == doc.document_id

    async def test_generates_synthetic_document_id_when_not_found(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
        fake_metadata_store: FakeMetadataStore,
    ) -> None:
        # Don't add any documents to metadata store

        fake_literal_store.search_results = [make_literal_result("/tmp/unknown.py", 1, "match")]

        query = Query(text="test", strategy=SearchStrategy.LITERAL)
        hits = await search_service.search(query, Path("/tmp"))

        # Should still return a hit with a generated document_id
        assert len(hits) == 1
        assert hits[0].document_id is not None
        # The generated ID should be a valid UUID format
        assert len(hits[0].document_id) == 36  # UUID string length


class TestLiteralSearchServiceScore:
    """Tests for score assignment."""

    async def test_all_matches_have_score_one(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = [
            make_literal_result("/tmp/a.py", 1, "match 1"),
            make_literal_result("/tmp/b.py", 2, "match 2"),
            make_literal_result("/tmp/c.py", 3, "match 3"),
        ]

        query = Query(text="test", strategy=SearchStrategy.LITERAL)
        hits = await search_service.search(query, Path("/tmp"))

        for hit in hits:
            assert hit.score == 1.0

    async def test_score_within_valid_range(
        self,
        search_service: LiteralSearchService,
        fake_literal_store: FakeLiteralStore,
    ) -> None:
        fake_literal_store.search_results = [make_literal_result("/tmp/test.py", 1, "match")]

        query = Query(text="test", strategy=SearchStrategy.LITERAL)
        hits = await search_service.search(query, Path("/tmp"))

        assert hits[0].score is not None
        assert 0.0 <= hits[0].score <= 1.0
