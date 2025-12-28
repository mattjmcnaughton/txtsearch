"""Integration tests for SemanticSearchService with real embeddings.

These tests use ChromaDB's default embedding function (sentence-transformers
all-MiniLM-L6-v2) and real SQLite to verify end-to-end search behavior.
Marked as slow since they load ML models and perform real inference.
"""

from datetime import datetime, timezone, timedelta
from uuid import uuid4

import chromadb
import pytest

from txtsearch.models.chunk import DocumentChunk
from txtsearch.models.document import Document
from txtsearch.models.enums import SearchStrategy, SourceType
from txtsearch.models.query import Query, QueryFilters
from txtsearch.services.metadata_store import MetadataStore, create_async_engine_from_path
from txtsearch.services.semantic_search import SemanticSearchService
from txtsearch.services.vector_store import VectorStore


def make_document(
    document_id: str | None = None,
    source_type: SourceType = SourceType.FILE,
    ingested_at: datetime | None = None,
) -> Document:
    """Create a test Document."""
    doc_id = document_id or str(uuid4())
    return Document(
        document_id=doc_id,
        uri=f"file:///test/{doc_id}.txt",
        display_name="test.txt",
        content_hash="a" * 64,
        size_bytes=100,
        source_type=source_type,
        ingested_at=ingested_at or datetime.now(timezone.utc),
    )


def make_chunk(
    chunk_id: str,
    document_id: str,
    chunk_index: int,
    text: str,
) -> DocumentChunk:
    """Create a test DocumentChunk."""
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_index=chunk_index,
        text=text,
        content_hash="b" * 64,
        char_start=0,
        char_end=len(text),
        line_start=1,
        line_end=1,
    )


@pytest.fixture
def ephemeral_client() -> chromadb.ClientAPI:
    """Create an ephemeral ChromaDB client for testing."""
    return chromadb.EphemeralClient()


@pytest.fixture
async def metadata_store() -> MetadataStore:
    """Create an in-memory MetadataStore."""
    engine = create_async_engine_from_path(":memory:")
    store = MetadataStore(engine=engine)
    await store.initialize_schema()
    return store


@pytest.fixture
async def vector_store(ephemeral_client: chromadb.ClientAPI) -> VectorStore:
    """Create a VectorStore with real embeddings."""
    collection_name = f"test_{uuid4().hex[:8]}"
    store = VectorStore(client=ephemeral_client, collection_name=collection_name)
    await store.initialize()
    return store


@pytest.fixture
async def search_service(
    vector_store: VectorStore,
    metadata_store: MetadataStore,
) -> SemanticSearchService:
    """Create a SemanticSearchService with real dependencies."""
    return SemanticSearchService(
        vector_store=vector_store,
        metadata_store=metadata_store,
    )


async def index_document(
    metadata_store: MetadataStore,
    vector_store: VectorStore,
    document: Document,
    chunks: list[DocumentChunk],
) -> None:
    """Helper to index a document with its chunks."""
    await metadata_store.save_document(document)
    await metadata_store.save_chunks(chunks)

    chunk_ids = [c.chunk_id for c in chunks]
    chunk_texts = [c.text for c in chunks]
    chunk_metadatas = [{"document_id": c.document_id, "chunk_index": c.chunk_index} for c in chunks]

    await vector_store.add_documents(
        ids=chunk_ids,
        documents=chunk_texts,
        metadatas=chunk_metadatas,
    )


@pytest.mark.slow
class TestSemanticSearchIntegration:
    """Integration tests for semantic search with real embeddings."""

    async def test_returns_semantically_relevant_results(
        self,
        search_service: SemanticSearchService,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
    ) -> None:
        """Verify that search returns semantically relevant documents first."""
        # Index documents on different topics
        python_doc = make_document()
        python_doc_id = python_doc.document_id
        python_chunk = make_chunk(
            str(uuid4()), python_doc_id, 0, "Python is excellent for data analysis and machine learning applications."
        )

        cooking_doc = make_document()
        cooking_chunk = make_chunk(
            str(uuid4()), cooking_doc.document_id, 0, "Baking bread requires flour, water, yeast, and patience."
        )

        gardening_doc = make_document()
        gardening_chunk = make_chunk(
            str(uuid4()), gardening_doc.document_id, 0, "Tomatoes grow best in sunny locations with regular watering."
        )

        await index_document(metadata_store, vector_store, python_doc, [python_chunk])
        await index_document(metadata_store, vector_store, cooking_doc, [cooking_chunk])
        await index_document(metadata_store, vector_store, gardening_doc, [gardening_chunk])

        # Search for programming-related content
        query = Query(
            text="programming languages for AI and data science",
            strategy=SearchStrategy.SEMANTIC,
            top_k=3,
        )
        hits = await search_service.search(query)

        # Python should be the top result
        assert len(hits) == 3
        assert hits[0].document_id == python_doc_id
        assert hits[0].rank == 0
        assert hits[0].score is not None
        assert hits[0].score > hits[1].score  # type: ignore

    async def test_includes_snippet_from_chunk(
        self,
        search_service: SemanticSearchService,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
    ) -> None:
        """Verify that snippets are included from the matching chunk."""
        doc = make_document()
        chunk_text = "This is the specific text that should appear in the snippet."
        chunk = make_chunk(str(uuid4()), doc.document_id, 0, chunk_text)

        await index_document(metadata_store, vector_store, doc, [chunk])

        query = Query(
            text="specific text snippet",
            strategy=SearchStrategy.SEMANTIC,
            include_snippets=True,
        )
        hits = await search_service.search(query)

        assert len(hits) == 1
        assert hits[0].snippet == chunk_text

    async def test_filters_by_document_ids(
        self,
        search_service: SemanticSearchService,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
    ) -> None:
        """Verify that document_ids filter restricts search results."""
        doc1 = make_document()
        doc2 = make_document()

        chunk1 = make_chunk(str(uuid4()), doc1.document_id, 0, "Python programming concepts")
        chunk2 = make_chunk(str(uuid4()), doc2.document_id, 0, "Python coding tutorials")

        await index_document(metadata_store, vector_store, doc1, [chunk1])
        await index_document(metadata_store, vector_store, doc2, [chunk2])

        # Search only in doc1
        query = Query(
            text="Python",
            strategy=SearchStrategy.SEMANTIC,
            filters=QueryFilters(document_ids=[doc1.document_id]),
        )
        hits = await search_service.search(query)

        assert len(hits) == 1
        assert hits[0].document_id == doc1.document_id

    async def test_filters_by_source_type(
        self,
        search_service: SemanticSearchService,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
    ) -> None:
        """Verify that source_types filter works correctly."""
        file_doc = make_document(source_type=SourceType.FILE)
        web_doc = make_document(source_type=SourceType.WEB)

        file_chunk = make_chunk(str(uuid4()), file_doc.document_id, 0, "Python file content")
        web_chunk = make_chunk(str(uuid4()), web_doc.document_id, 0, "Python web content")

        await index_document(metadata_store, vector_store, file_doc, [file_chunk])
        await index_document(metadata_store, vector_store, web_doc, [web_chunk])

        # Search only FILE sources
        query = Query(
            text="Python",
            strategy=SearchStrategy.SEMANTIC,
            filters=QueryFilters(source_types={SourceType.FILE}),
        )
        hits = await search_service.search(query)

        assert len(hits) == 1
        assert hits[0].document_id == file_doc.document_id

    async def test_filters_by_ingested_after(
        self,
        search_service: SemanticSearchService,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
    ) -> None:
        """Verify that ingested_after filter works correctly."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=7)
        new_time = now - timedelta(hours=1)
        cutoff = now - timedelta(days=1)

        old_doc = make_document(ingested_at=old_time)
        new_doc = make_document(ingested_at=new_time)

        old_chunk = make_chunk(str(uuid4()), old_doc.document_id, 0, "Old Python content")
        new_chunk = make_chunk(str(uuid4()), new_doc.document_id, 0, "New Python content")

        await index_document(metadata_store, vector_store, old_doc, [old_chunk])
        await index_document(metadata_store, vector_store, new_doc, [new_chunk])

        # Search only recent documents
        query = Query(
            text="Python",
            strategy=SearchStrategy.SEMANTIC,
            filters=QueryFilters(ingested_after=cutoff),
        )
        hits = await search_service.search(query)

        assert len(hits) == 1
        assert hits[0].document_id == new_doc.document_id

    async def test_respects_top_k_limit(
        self,
        search_service: SemanticSearchService,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
    ) -> None:
        """Verify that top_k limits the number of results."""
        # Index 5 documents
        for i in range(5):
            doc = make_document()
            chunk = make_chunk(str(uuid4()), doc.document_id, 0, f"Python content variant {i}")
            await index_document(metadata_store, vector_store, doc, [chunk])

        query = Query(
            text="Python",
            strategy=SearchStrategy.SEMANTIC,
            top_k=3,
        )
        hits = await search_service.search(query)

        assert len(hits) == 3

    async def test_scores_are_normalized(
        self,
        search_service: SemanticSearchService,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
    ) -> None:
        """Verify that scores are in the valid 0-1 range."""
        doc = make_document()
        chunk = make_chunk(str(uuid4()), doc.document_id, 0, "Python programming")

        await index_document(metadata_store, vector_store, doc, [chunk])

        query = Query(text="Python", strategy=SearchStrategy.SEMANTIC)
        hits = await search_service.search(query)

        assert len(hits) == 1
        assert hits[0].score is not None
        assert 0.0 < hits[0].score <= 1.0

    async def test_empty_collection_returns_empty_results(
        self,
        search_service: SemanticSearchService,
    ) -> None:
        """Verify that searching an empty collection returns no results."""
        query = Query(text="Python", strategy=SearchStrategy.SEMANTIC)
        hits = await search_service.search(query)

        assert hits == []

    async def test_multiple_chunks_per_document(
        self,
        search_service: SemanticSearchService,
        metadata_store: MetadataStore,
        vector_store: VectorStore,
    ) -> None:
        """Verify that multiple chunks from the same document can be returned."""
        doc = make_document()
        doc_id = doc.document_id
        chunk1 = make_chunk(str(uuid4()), doc_id, 0, "Python basics and fundamentals")
        chunk2 = make_chunk(str(uuid4()), doc_id, 1, "Advanced Python programming patterns")

        await index_document(metadata_store, vector_store, doc, [chunk1, chunk2])

        query = Query(
            text="Python programming",
            strategy=SearchStrategy.SEMANTIC,
            top_k=10,
        )
        hits = await search_service.search(query)

        assert len(hits) == 2
        # Both should be from the same document
        assert all(h.document_id == doc_id for h in hits)
        # Ranks should be sequential
        assert hits[0].rank == 0
        assert hits[1].rank == 1
