"""Unit tests for the VectorStore service."""

from uuid import uuid4

import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
import pytest

from txtsearch.services.vector_store import VectorStore


class FakeEmbeddingFunction(EmbeddingFunction[Documents]):
    """Deterministic embedding function for testing.

    Generates embeddings based on document length to produce
    consistent, predictable vectors without external dependencies.
    """

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.call_count = 0

    def __call__(self, input: Documents) -> Embeddings:
        self.call_count += 1
        embeddings: Embeddings = []
        for doc in input:
            # Generate deterministic embedding based on document content
            seed = len(doc) * 0.001
            embedding = [seed + (i * 0.0001) for i in range(self.dim)]
            embeddings.append(embedding)
        return embeddings


@pytest.fixture
def ephemeral_client() -> chromadb.ClientAPI:
    """Create an ephemeral ChromaDB client for testing."""
    return chromadb.EphemeralClient()


@pytest.fixture
def fake_embedding_function() -> FakeEmbeddingFunction:
    """Create a fake embedding function for testing."""
    return FakeEmbeddingFunction()


@pytest.fixture
async def store(ephemeral_client: chromadb.ClientAPI) -> VectorStore:
    """Create a VectorStore with initialized collection.

    Uses a unique collection name per test to ensure isolation.
    """
    collection_name = f"test_{uuid4().hex[:8]}"
    store = VectorStore(client=ephemeral_client, collection_name=collection_name)
    await store.initialize()
    return store


@pytest.fixture
async def store_with_fake_embeddings(
    ephemeral_client: chromadb.ClientAPI,
    fake_embedding_function: FakeEmbeddingFunction,
) -> VectorStore:
    """Create a VectorStore with a fake embedding function.

    Uses a unique collection name per test to ensure isolation.
    """
    collection_name = f"test_{uuid4().hex[:8]}"
    store = VectorStore(
        client=ephemeral_client,
        collection_name=collection_name,
        embedding_function=fake_embedding_function,
    )
    await store.initialize()
    return store


def _make_embedding(dim: int = 384, seed: float = 0.1) -> list[float]:
    """Generate a deterministic embedding vector."""
    return [seed + (i * 0.001) for i in range(dim)]


class TestVectorStoreInitialization:
    """Tests for VectorStore initialization."""

    async def test_initialize_creates_collection(self, ephemeral_client: chromadb.ClientAPI) -> None:
        store = VectorStore(client=ephemeral_client, collection_name="test_collection")
        await store.initialize()

        # Verify collection exists
        collections = ephemeral_client.list_collections()
        assert any(c.name == "test_collection" for c in collections)

    async def test_initialize_uses_default_collection_name(self, ephemeral_client: chromadb.ClientAPI) -> None:
        store = VectorStore(client=ephemeral_client)
        await store.initialize()

        collections = ephemeral_client.list_collections()
        assert any(c.name == "chunks" for c in collections)

    async def test_initialize_idempotent(self, ephemeral_client: chromadb.ClientAPI) -> None:
        store = VectorStore(client=ephemeral_client)
        await store.initialize()
        await store.initialize()  # Should not raise

        count = await store.count()
        assert count == 0


class TestVectorStoreAddEmbeddings:
    """Tests for adding embeddings to the store."""

    async def test_add_single_embedding(self, store: VectorStore) -> None:
        await store.add_embeddings(
            ids=["chunk-1"],
            embeddings=[_make_embedding()],
            documents=["This is the text content."],
        )

        count = await store.count()
        assert count == 1

    async def test_add_multiple_embeddings(self, store: VectorStore) -> None:
        await store.add_embeddings(
            ids=["chunk-1", "chunk-2", "chunk-3"],
            embeddings=[_make_embedding(seed=0.1), _make_embedding(seed=0.2), _make_embedding(seed=0.3)],
            documents=["Text one.", "Text two.", "Text three."],
        )

        count = await store.count()
        assert count == 3

    async def test_add_embeddings_with_metadata(self, store: VectorStore) -> None:
        await store.add_embeddings(
            ids=["chunk-1"],
            embeddings=[_make_embedding()],
            documents=["Sample text."],
            metadatas=[{"document_id": "doc-1", "chunk_index": 0}],
        )

        result = await store.get_by_ids(["chunk-1"])
        assert result["metadatas"][0]["document_id"] == "doc-1"
        assert result["metadatas"][0]["chunk_index"] == 0

    async def test_add_empty_list_does_nothing(self, store: VectorStore) -> None:
        await store.add_embeddings(ids=[], embeddings=[], documents=[])
        count = await store.count()
        assert count == 0

    async def test_upsert_updates_existing_embedding(self, store: VectorStore) -> None:
        await store.add_embeddings(
            ids=["chunk-1"],
            embeddings=[_make_embedding(seed=0.1)],
            documents=["Original text."],
        )

        # Update with same ID
        await store.add_embeddings(
            ids=["chunk-1"],
            embeddings=[_make_embedding(seed=0.9)],
            documents=["Updated text."],
        )

        count = await store.count()
        assert count == 1

        result = await store.get_by_ids(["chunk-1"])
        assert result["documents"][0] == "Updated text."

    async def test_raises_on_mismatched_lengths(self, store: VectorStore) -> None:
        with pytest.raises(ValueError, match="Mismatched lengths"):
            await store.add_embeddings(
                ids=["chunk-1", "chunk-2"],
                embeddings=[_make_embedding()],  # Only one embedding
                documents=["Text one.", "Text two."],
            )

    async def test_raises_on_mismatched_metadata_length(self, store: VectorStore) -> None:
        with pytest.raises(ValueError, match="Mismatched lengths"):
            await store.add_embeddings(
                ids=["chunk-1", "chunk-2"],
                embeddings=[_make_embedding(), _make_embedding()],
                documents=["Text one.", "Text two."],
                metadatas=[{"key": "value"}],  # Only one metadata dict
            )

    async def test_raises_when_not_initialized(self, ephemeral_client: chromadb.ClientAPI) -> None:
        store = VectorStore(client=ephemeral_client)
        # Don't call initialize()

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.add_embeddings(
                ids=["chunk-1"],
                embeddings=[_make_embedding()],
                documents=["Text."],
            )


class TestVectorStoreDeleteOperations:
    """Tests for deleting embeddings from the store."""

    async def test_delete_by_ids(self, store: VectorStore) -> None:
        await store.add_embeddings(
            ids=["chunk-1", "chunk-2", "chunk-3"],
            embeddings=[_make_embedding(seed=0.1), _make_embedding(seed=0.2), _make_embedding(seed=0.3)],
            documents=["One.", "Two.", "Three."],
        )

        await store.delete_by_ids(["chunk-1", "chunk-3"])

        count = await store.count()
        assert count == 1

        result = await store.get_by_ids(["chunk-2"])
        assert len(result["ids"]) == 1
        assert result["documents"][0] == "Two."

    async def test_delete_empty_list_does_nothing(self, store: VectorStore) -> None:
        await store.add_embeddings(
            ids=["chunk-1"],
            embeddings=[_make_embedding()],
            documents=["Text."],
        )

        await store.delete_by_ids([])

        count = await store.count()
        assert count == 1

    async def test_delete_nonexistent_ids_does_not_raise(self, store: VectorStore) -> None:
        await store.delete_by_ids(["nonexistent-id"])
        # Should not raise

    async def test_delete_raises_when_not_initialized(self, ephemeral_client: chromadb.ClientAPI) -> None:
        store = VectorStore(client=ephemeral_client)

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.delete_by_ids(["chunk-1"])


class TestVectorStoreClearCollection:
    """Tests for clearing the collection."""

    async def test_clear_removes_all_embeddings(self, store: VectorStore) -> None:
        await store.add_embeddings(
            ids=["chunk-1", "chunk-2"],
            embeddings=[_make_embedding(), _make_embedding()],
            documents=["One.", "Two."],
        )

        await store.clear_collection()

        count = await store.count()
        assert count == 0

    async def test_clear_allows_new_additions(self, store: VectorStore) -> None:
        await store.add_embeddings(
            ids=["chunk-1"],
            embeddings=[_make_embedding()],
            documents=["Original."],
        )
        await store.clear_collection()

        await store.add_embeddings(
            ids=["chunk-new"],
            embeddings=[_make_embedding()],
            documents=["New content."],
        )

        count = await store.count()
        assert count == 1

    async def test_clear_raises_when_not_initialized(self, ephemeral_client: chromadb.ClientAPI) -> None:
        store = VectorStore(client=ephemeral_client)

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.clear_collection()


class TestVectorStoreRetrieval:
    """Tests for retrieving embeddings."""

    async def test_get_by_ids_returns_all_data(self, store: VectorStore) -> None:
        embedding = _make_embedding(seed=0.5)
        await store.add_embeddings(
            ids=["chunk-1"],
            embeddings=[embedding],
            documents=["Test document text."],
            metadatas=[{"doc_id": "doc-1"}],
        )

        result = await store.get_by_ids(["chunk-1"])

        assert result["ids"] == ["chunk-1"]
        assert result["documents"] == ["Test document text."]
        assert result["metadatas"][0]["doc_id"] == "doc-1"
        # ChromaDB stores as float32, so use approximate comparison
        retrieved_embedding = list(result["embeddings"][0])
        assert len(retrieved_embedding) == len(embedding)
        assert retrieved_embedding == pytest.approx(embedding, rel=1e-5)

    async def test_get_by_ids_empty_list(self, store: VectorStore) -> None:
        result = await store.get_by_ids([])

        assert result["ids"] == []
        assert result["embeddings"] == []
        assert result["documents"] == []
        assert result["metadatas"] == []

    async def test_get_by_ids_nonexistent_returns_empty(self, store: VectorStore) -> None:
        result = await store.get_by_ids(["nonexistent"])

        assert result["ids"] == []

    async def test_get_raises_when_not_initialized(self, ephemeral_client: chromadb.ClientAPI) -> None:
        store = VectorStore(client=ephemeral_client)

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.get_by_ids(["chunk-1"])


class TestVectorStoreCount:
    """Tests for counting embeddings."""

    async def test_count_empty_collection(self, store: VectorStore) -> None:
        count = await store.count()
        assert count == 0

    async def test_count_after_additions(self, store: VectorStore) -> None:
        await store.add_embeddings(
            ids=["chunk-1", "chunk-2"],
            embeddings=[_make_embedding(), _make_embedding()],
            documents=["One.", "Two."],
        )

        count = await store.count()
        assert count == 2

    async def test_count_raises_when_not_initialized(self, ephemeral_client: chromadb.ClientAPI) -> None:
        store = VectorStore(client=ephemeral_client)

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.count()


class TestVectorStoreAddDocuments:
    """Tests for adding documents with automatic embedding generation."""

    async def test_add_single_document(self, store_with_fake_embeddings: VectorStore) -> None:
        await store_with_fake_embeddings.add_documents(
            ids=["chunk-1"],
            documents=["This is the text content."],
        )

        count = await store_with_fake_embeddings.count()
        assert count == 1

    async def test_add_multiple_documents(self, store_with_fake_embeddings: VectorStore) -> None:
        await store_with_fake_embeddings.add_documents(
            ids=["chunk-1", "chunk-2", "chunk-3"],
            documents=["Text one.", "Text two.", "Text three."],
        )

        count = await store_with_fake_embeddings.count()
        assert count == 3

    async def test_add_documents_with_metadata(self, store_with_fake_embeddings: VectorStore) -> None:
        await store_with_fake_embeddings.add_documents(
            ids=["chunk-1"],
            documents=["Sample text."],
            metadatas=[{"document_id": "doc-1", "chunk_index": 0}],
        )

        result = await store_with_fake_embeddings.get_by_ids(["chunk-1"])
        assert result["metadatas"][0]["document_id"] == "doc-1"
        assert result["metadatas"][0]["chunk_index"] == 0

    async def test_add_documents_empty_list_does_nothing(self, store_with_fake_embeddings: VectorStore) -> None:
        await store_with_fake_embeddings.add_documents(ids=[], documents=[])
        count = await store_with_fake_embeddings.count()
        assert count == 0

    async def test_add_documents_upserts_existing(self, store_with_fake_embeddings: VectorStore) -> None:
        await store_with_fake_embeddings.add_documents(
            ids=["chunk-1"],
            documents=["Original text."],
        )

        # Update with same ID
        await store_with_fake_embeddings.add_documents(
            ids=["chunk-1"],
            documents=["Updated text."],
        )

        count = await store_with_fake_embeddings.count()
        assert count == 1

        result = await store_with_fake_embeddings.get_by_ids(["chunk-1"])
        assert result["documents"][0] == "Updated text."

    async def test_add_documents_raises_on_mismatched_lengths(self, store_with_fake_embeddings: VectorStore) -> None:
        with pytest.raises(ValueError, match="Mismatched lengths"):
            await store_with_fake_embeddings.add_documents(
                ids=["chunk-1", "chunk-2"],
                documents=["Only one document."],
            )

    async def test_add_documents_raises_on_mismatched_metadata_length(
        self, store_with_fake_embeddings: VectorStore
    ) -> None:
        with pytest.raises(ValueError, match="Mismatched lengths"):
            await store_with_fake_embeddings.add_documents(
                ids=["chunk-1", "chunk-2"],
                documents=["Text one.", "Text two."],
                metadatas=[{"key": "value"}],  # Only one metadata dict
            )

    async def test_add_documents_raises_when_not_initialized(self, ephemeral_client: chromadb.ClientAPI) -> None:
        store = VectorStore(client=ephemeral_client)

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.add_documents(ids=["chunk-1"], documents=["Text."])

    async def test_add_documents_generates_embeddings(
        self,
        store_with_fake_embeddings: VectorStore,
        fake_embedding_function: FakeEmbeddingFunction,
    ) -> None:
        await store_with_fake_embeddings.add_documents(
            ids=["chunk-1"],
            documents=["Test document."],
        )

        # Verify embedding was generated
        result = await store_with_fake_embeddings.get_by_ids(["chunk-1"])
        assert result["embeddings"] is not None
        assert len(result["embeddings"][0]) == fake_embedding_function.dim


class TestVectorStoreEmbeddingFunction:
    """Tests for custom embedding function injection."""

    async def test_uses_injected_embedding_function(
        self,
        ephemeral_client: chromadb.ClientAPI,
        fake_embedding_function: FakeEmbeddingFunction,
    ) -> None:
        collection_name = f"test_{uuid4().hex[:8]}"
        store = VectorStore(
            client=ephemeral_client,
            collection_name=collection_name,
            embedding_function=fake_embedding_function,
        )
        await store.initialize()

        await store.add_documents(
            ids=["chunk-1"],
            documents=["Test document."],
        )

        # Verify the fake embedding function was called
        assert fake_embedding_function.call_count >= 1

    async def test_embedding_function_preserved_after_clear(
        self,
        ephemeral_client: chromadb.ClientAPI,
        fake_embedding_function: FakeEmbeddingFunction,
    ) -> None:
        collection_name = f"test_{uuid4().hex[:8]}"
        store = VectorStore(
            client=ephemeral_client,
            collection_name=collection_name,
            embedding_function=fake_embedding_function,
        )
        await store.initialize()

        await store.add_documents(ids=["chunk-1"], documents=["Text one."])
        await store.clear_collection()

        # Should still work after clear
        await store.add_documents(ids=["chunk-2"], documents=["Text two."])

        count = await store.count()
        assert count == 1
