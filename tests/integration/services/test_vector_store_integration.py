"""Integration tests for VectorStore with real embedding functions.

These tests use ChromaDB's default embedding function (sentence-transformers
all-MiniLM-L6-v2) to verify actual embedding generation and similarity search.
Marked as slow since they load ML models and perform real inference.
"""

from uuid import uuid4

import chromadb
import pytest

from txtsearch.services.vector_store import VectorStore


@pytest.fixture
def ephemeral_client() -> chromadb.ClientAPI:
    """Create an ephemeral ChromaDB client for testing."""
    return chromadb.EphemeralClient()


@pytest.fixture
async def store_with_real_embeddings(ephemeral_client: chromadb.ClientAPI) -> VectorStore:
    """Create a VectorStore using ChromaDB's default embedding function.

    Uses sentence-transformers all-MiniLM-L6-v2 for real embedding generation.
    """
    collection_name = f"test_{uuid4().hex[:8]}"
    store = VectorStore(
        client=ephemeral_client,
        collection_name=collection_name,
        # No embedding_function provided = ChromaDB uses default
    )
    await store.initialize()
    return store


@pytest.mark.slow
class TestVectorStoreRealEmbeddings:
    """Integration tests with real sentence-transformers embeddings."""

    async def test_add_documents_generates_real_embeddings(self, store_with_real_embeddings: VectorStore) -> None:
        """Verify that real embeddings are generated for documents."""
        await store_with_real_embeddings.add_documents(
            ids=["chunk-1"],
            documents=["The quick brown fox jumps over the lazy dog."],
        )

        result = await store_with_real_embeddings.get_by_ids(["chunk-1"])

        assert len(result["ids"]) == 1
        assert result["embeddings"] is not None
        # all-MiniLM-L6-v2 produces 384-dimensional embeddings
        assert len(result["embeddings"][0]) == 384
        # Embeddings should be normalized floats, not zeros
        embedding = result["embeddings"][0]
        assert any(v != 0.0 for v in embedding)

    async def test_multiple_documents_get_distinct_embeddings(self, store_with_real_embeddings: VectorStore) -> None:
        """Verify that different documents produce different embeddings."""
        await store_with_real_embeddings.add_documents(
            ids=["chunk-1", "chunk-2"],
            documents=[
                "Python is a programming language.",
                "The weather is sunny today.",
            ],
        )

        result = await store_with_real_embeddings.get_by_ids(["chunk-1", "chunk-2"])

        embedding_1 = result["embeddings"][0]
        embedding_2 = result["embeddings"][1]

        # Embeddings for different content should differ
        differences = sum(1 for a, b in zip(embedding_1, embedding_2) if a != b)
        assert differences > 100  # Most dimensions should differ

    async def test_similar_documents_have_closer_embeddings(self, store_with_real_embeddings: VectorStore) -> None:
        """Verify that semantically similar documents have closer embeddings."""
        await store_with_real_embeddings.add_documents(
            ids=["python-1", "python-2", "weather"],
            documents=[
                "Python is a popular programming language for data science.",
                "Python programming is used for machine learning applications.",
                "The weather forecast predicts rain tomorrow.",
            ],
        )

        result = await store_with_real_embeddings.get_by_ids(["python-1", "python-2", "weather"])

        python_1 = result["embeddings"][0]
        python_2 = result["embeddings"][1]
        weather = result["embeddings"][2]

        # Calculate cosine similarity (embeddings are normalized)
        def cosine_similarity(a: list[float], b: list[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            return dot_product

        sim_python_python = cosine_similarity(python_1, python_2)
        sim_python_weather = cosine_similarity(python_1, weather)

        # Two Python-related sentences should be more similar than Python vs weather
        assert sim_python_python > sim_python_weather

    async def test_embedding_persistence_across_operations(self, store_with_real_embeddings: VectorStore) -> None:
        """Verify embeddings persist correctly through add/get cycles."""
        original_text = "Machine learning models process data to make predictions."

        await store_with_real_embeddings.add_documents(
            ids=["ml-chunk"],
            documents=[original_text],
        )

        # Retrieve and verify
        result = await store_with_real_embeddings.get_by_ids(["ml-chunk"])
        assert result["documents"][0] == original_text
        assert len(result["embeddings"][0]) == 384

        # Add more documents
        await store_with_real_embeddings.add_documents(
            ids=["other-chunk"],
            documents=["Another document about something else."],
        )

        # Original should still be retrievable with same embedding
        result_after = await store_with_real_embeddings.get_by_ids(["ml-chunk"])
        assert result_after["documents"][0] == original_text
        assert result["embeddings"][0] == pytest.approx(result_after["embeddings"][0], rel=1e-5)


@pytest.mark.slow
class TestVectorStoreSimilaritySearch:
    """Integration tests for similarity search with real embeddings."""

    async def test_query_returns_relevant_results(self, ephemeral_client: chromadb.ClientAPI) -> None:
        """Verify that querying returns semantically relevant documents."""
        collection_name = f"test_{uuid4().hex[:8]}"
        store = VectorStore(client=ephemeral_client, collection_name=collection_name)
        await store.initialize()

        # Add documents on different topics
        await store.add_documents(
            ids=["python", "javascript", "cooking", "gardening"],
            documents=[
                "Python is excellent for data analysis and machine learning.",
                "JavaScript runs in web browsers and Node.js servers.",
                "Baking bread requires flour, water, yeast, and patience.",
                "Tomatoes grow best in sunny locations with regular watering.",
            ],
        )

        # Query using the underlying collection directly for similarity search
        # (VectorStore doesn't expose query yet, so we access _collection)
        results = store._collection.query(
            query_texts=["programming languages for AI"],
            n_results=2,
        )

        # Python should be the top result for AI/programming query
        assert "python" in results["ids"][0]
        # JavaScript might be second (also programming), cooking/gardening should not appear
        returned_ids = results["ids"][0]
        assert "cooking" not in returned_ids
        assert "gardening" not in returned_ids

    async def test_query_with_metadata_filter(self, ephemeral_client: chromadb.ClientAPI) -> None:
        """Verify that metadata can be used to filter search results."""
        collection_name = f"test_{uuid4().hex[:8]}"
        store = VectorStore(client=ephemeral_client, collection_name=collection_name)
        await store.initialize()

        await store.add_documents(
            ids=["doc1-chunk1", "doc1-chunk2", "doc2-chunk1"],
            documents=[
                "Python functions are defined with the def keyword.",
                "Python classes use the class keyword for definition.",
                "Python modules can be imported using import statements.",
            ],
            metadatas=[
                {"document_id": "doc1", "chunk_index": 0},
                {"document_id": "doc1", "chunk_index": 1},
                {"document_id": "doc2", "chunk_index": 0},
            ],
        )

        # Query with metadata filter for doc1 only
        results = store._collection.query(
            query_texts=["Python syntax"],
            n_results=3,
            where={"document_id": "doc1"},
        )

        # Should only return chunks from doc1
        for doc_id in results["ids"][0]:
            assert doc_id.startswith("doc1")
