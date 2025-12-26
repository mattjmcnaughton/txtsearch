"""Unit tests for the MetadataStore service."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from txtsearch.models.chunk import DocumentChunk
from txtsearch.models.document import Document
from txtsearch.models.enums import SourceType
from txtsearch.services.metadata_store import MetadataStore, create_async_engine_from_path


def _make_hash() -> str:
    """Generate a valid 64-character hex digest."""
    return "0123456789abcdef" * 4


def _make_document(
    document_id: str | None = None,
    uri: str | None = None,
) -> Document:
    """Create a valid Document for testing."""
    return Document(
        document_id=document_id or str(uuid4()),
        uri=uri or f"file:///tmp/{uuid4()}.txt",
        display_name="test.txt",
        content_hash=_make_hash(),
        size_bytes=1024,
        source_type=SourceType.FILE,
        ingested_at=datetime.now(timezone.utc),
        extra={"language": "en"},
    )


def _make_chunk(
    document_id: str,
    chunk_index: int = 0,
    chunk_id: str | None = None,
) -> DocumentChunk:
    """Create a valid DocumentChunk for testing."""
    return DocumentChunk(
        chunk_id=chunk_id or str(uuid4()),
        document_id=document_id,
        chunk_index=chunk_index,
        text="This is some sample text for the chunk.",
        content_hash=_make_hash(),
        char_start=0,
        char_end=40,
        line_start=1,
        line_end=1,
        token_count=10,
        extra={"section": "intro"},
    )


@pytest.fixture
def async_engine():
    """Create an in-memory async SQLite engine for testing."""
    return create_async_engine_from_path(":memory:")


@pytest.fixture
async def store(async_engine) -> MetadataStore:
    """Create a MetadataStore with initialized schema."""
    store = MetadataStore(engine=async_engine)
    await store.initialize_schema()
    return store


class TestMetadataStoreDocumentOperations:
    """Tests for document save and retrieve operations."""

    async def test_save_and_retrieve_document_by_uri(self, store: MetadataStore) -> None:
        document = _make_document(uri="file:///test/example.txt")
        await store.save_document(document)

        retrieved = await store.get_document_by_uri("file:///test/example.txt")

        assert retrieved is not None
        assert retrieved.document_id == document.document_id
        assert retrieved.uri == document.uri
        assert retrieved.display_name == document.display_name
        assert retrieved.content_hash == document.content_hash
        assert retrieved.size_bytes == document.size_bytes
        assert retrieved.source_type == document.source_type
        assert retrieved.extra == document.extra

    async def test_save_and_retrieve_document_by_id(self, store: MetadataStore) -> None:
        doc_id = str(uuid4())
        document = _make_document(document_id=doc_id)
        await store.save_document(document)

        retrieved = await store.get_document_by_id(doc_id)

        assert retrieved is not None
        assert retrieved.document_id == doc_id

    async def test_returns_none_for_nonexistent_uri(self, store: MetadataStore) -> None:
        result = await store.get_document_by_uri("file:///nonexistent")
        assert result is None

    async def test_returns_none_for_nonexistent_id(self, store: MetadataStore) -> None:
        result = await store.get_document_by_id(str(uuid4()))
        assert result is None

    async def test_upsert_updates_existing_document(self, store: MetadataStore) -> None:
        doc_id = str(uuid4())
        document1 = _make_document(document_id=doc_id, uri="file:///test.txt")
        await store.save_document(document1)

        # Create updated document with same ID but different content
        document2 = Document(
            document_id=doc_id,
            uri="file:///test.txt",
            display_name="updated.txt",
            content_hash="abcd" * 16,
            size_bytes=2048,
            source_type=SourceType.FILE,
            ingested_at=datetime.now(timezone.utc),
            extra={"updated": True},
        )
        await store.save_document(document2)

        retrieved = await store.get_document_by_id(doc_id)

        assert retrieved is not None
        assert retrieved.display_name == "updated.txt"
        assert retrieved.size_bytes == 2048
        assert retrieved.extra == {"updated": True}


class TestMetadataStoreChunkOperations:
    """Tests for chunk save and retrieve operations."""

    async def test_save_and_retrieve_chunks(self, store: MetadataStore) -> None:
        document = _make_document()
        await store.save_document(document)

        chunks = [
            _make_chunk(document.document_id, chunk_index=0),
            _make_chunk(document.document_id, chunk_index=1),
            _make_chunk(document.document_id, chunk_index=2),
        ]
        await store.save_chunks(chunks)

        retrieved = await store.get_chunks_by_document_id(document.document_id)

        assert len(retrieved) == 3
        assert [c.chunk_index for c in retrieved] == [0, 1, 2]

    async def test_chunks_preserve_metadata(self, store: MetadataStore) -> None:
        document = _make_document()
        await store.save_document(document)

        chunk = _make_chunk(document.document_id)
        await store.save_chunks([chunk])

        retrieved = await store.get_chunks_by_document_id(document.document_id)

        assert len(retrieved) == 1
        assert retrieved[0].extra == {"section": "intro"}
        assert retrieved[0].token_count == 10

    async def test_empty_chunks_list_does_nothing(self, store: MetadataStore) -> None:
        await store.save_chunks([])
        # Should not raise

    async def test_returns_empty_list_for_nonexistent_document(self, store: MetadataStore) -> None:
        result = await store.get_chunks_by_document_id(str(uuid4()))
        assert result == []


class TestMetadataStoreDeleteOperations:
    """Tests for delete operations."""

    async def test_delete_document_removes_document(self, store: MetadataStore) -> None:
        document = _make_document()
        await store.save_document(document)

        deleted = await store.delete_document(document.document_id)

        assert deleted is True
        assert await store.get_document_by_id(document.document_id) is None

    async def test_delete_document_removes_associated_chunks(self, store: MetadataStore) -> None:
        document = _make_document()
        await store.save_document(document)
        chunks = [_make_chunk(document.document_id, i) for i in range(3)]
        await store.save_chunks(chunks)

        await store.delete_document(document.document_id)

        remaining = await store.get_chunks_by_document_id(document.document_id)
        assert remaining == []

    async def test_delete_nonexistent_document_returns_false(self, store: MetadataStore) -> None:
        result = await store.delete_document(str(uuid4()))
        assert result is False


class TestMetadataStoreRoundTrip:
    """Tests for domain model round-trip conversion."""

    async def test_document_round_trip_preserves_all_fields(self, store: MetadataStore) -> None:
        original = Document(
            document_id=str(uuid4()),
            uri="file:///test/path.txt",
            display_name="path.txt",
            content_hash=_make_hash(),
            size_bytes=999,
            source_type=SourceType.WEB,
            ingested_at=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            extra={"key": "value", "nested": {"a": 1}},
        )
        await store.save_document(original)

        retrieved = await store.get_document_by_id(original.document_id)

        assert retrieved is not None
        assert retrieved.schema_version == original.schema_version
        assert retrieved.source_type == SourceType.WEB
        assert retrieved.ingested_at == original.ingested_at
        assert retrieved.extra == {"key": "value", "nested": {"a": 1}}

    async def test_chunk_round_trip_preserves_all_fields(self, store: MetadataStore) -> None:
        document = _make_document()
        await store.save_document(document)

        original = DocumentChunk(
            chunk_id=str(uuid4()),
            document_id=document.document_id,
            chunk_index=5,
            text="Test chunk text content.",
            content_hash=_make_hash(),
            char_start=100,
            char_end=200,
            line_start=10,
            line_end=15,
            token_count=25,
            extra={"position": "middle"},
        )
        await store.save_chunks([original])

        retrieved = await store.get_chunks_by_document_id(document.document_id)

        assert len(retrieved) == 1
        chunk = retrieved[0]
        assert chunk.chunk_id == original.chunk_id
        assert chunk.chunk_index == 5
        assert chunk.char_start == 100
        assert chunk.char_end == 200
        assert chunk.line_start == 10
        assert chunk.line_end == 15
        assert chunk.token_count == 25
        assert chunk.extra == {"position": "middle"}
