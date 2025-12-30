"""Integration tests for lexical search with real DuckDB FTS."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from txtsearch.models.enums import SearchStrategy
from txtsearch.models.query import Query
from txtsearch.services.factory import create_test_lexical_search_service


@pytest.mark.slow
class TestLexicalSearchIntegration:
    """Integration tests with real DuckDB FTS."""

    async def test_end_to_end_search_workflow(self):
        """Test complete workflow: index chunks -> search -> verify results."""
        service = create_test_lexical_search_service()

        await service.initialize()

        doc_id = str(uuid4())

        chunks = [
            {
                "document_id": f"{doc_id}-chunk-0",
                "chunk_id": f"{doc_id}-chunk-0",
                "chunk_index": 0,
                "content": "Python is a high-level programming language",
                "file_path": "file:///python.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
            {
                "document_id": f"{doc_id}-chunk-1",
                "chunk_id": f"{doc_id}-chunk-1",
                "chunk_index": 1,
                "content": "JavaScript is used for web programming",
                "file_path": "file:///js.js",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
            {
                "document_id": f"{doc_id}-chunk-2",
                "chunk_id": f"{doc_id}-chunk-2",
                "chunk_index": 2,
                "content": "Python programming with advanced features",
                "file_path": "file:///advanced.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
        ]

        await service._lexical_store.index_chunks(chunks)

        query = Query(
            text="Python programming",
            strategy=SearchStrategy.LEXICAL,
            top_k=10,
            include_snippets=False,
        )

        results = await service._lexical_store.search(
            query_text=query.text,
            top_k=query.top_k,
        )

        assert len(results) == 2
        assert all("Python" in r["content"] for r in results)
        assert all("score" in r for r in results)
        assert results[0]["score"] >= results[1]["score"]

        await service.close()

    async def test_bm25_ranking_prefers_term_frequency(self):
        """Test that BM25 ranks documents with higher term frequency higher."""
        service = create_test_lexical_search_service()

        await service.initialize()

        chunks = [
            {
                "document_id": "chunk-1",
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "content": "Python Python Python programming",
                "file_path": "file:///high.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
            {
                "document_id": "chunk-2",
                "chunk_id": "chunk-2",
                "chunk_index": 1,
                "content": "Python programming tutorial",
                "file_path": "file:///low.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
        ]

        await service._lexical_store.index_chunks(chunks)

        results = await service._lexical_store.search(
            query_text="Python",
            top_k=10,
        )

        assert len(results) == 2
        assert results[0]["document_id"] == "chunk-1"
        assert results[0]["score"] > results[1]["score"]

        await service.close()

    async def test_stemming_matches_word_variants(self):
        """Test that Porter stemming matches word variants."""
        service = create_test_lexical_search_service()

        await service.initialize()

        chunks = [
            {
                "document_id": "chunk-1",
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "content": "Running tests on the system",
                "file_path": "file:///test1.txt",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
            {
                "document_id": "chunk-2",
                "chunk_id": "chunk-2",
                "chunk_index": 1,
                "content": "The runner completed the race",
                "file_path": "file:///test2.txt",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
        ]

        await service._lexical_store.index_chunks(chunks)

        results = await service._lexical_store.search(
            query_text="run",
            top_k=10,
        )

        assert len(results) == 2

        await service.close()
