"""Unit tests for LexicalStore service."""

from datetime import datetime, timezone

import pytest

from txtsearch.services.lexical_store import LexicalStore


class TestLexicalStoreInitialization:
    """Test lexical store initialization and schema creation."""

    async def test_initialize_creates_schema(self):
        """Test that initialize creates document_chunks table and FTS index."""
        store = LexicalStore(db_path=":memory:")

        await store.initialize()

        result = await store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='document_chunks'"
        )
        tables = result.fetchall()
        assert len(tables) == 1
        assert tables[0][0] == "document_chunks"

        await store.close()

    async def test_initialize_loads_fts_extension(self):
        """Test that FTS extension is loaded during initialization."""
        store = LexicalStore(db_path=":memory:")

        await store.initialize()

        result = await store._conn.execute(
            "SELECT * FROM duckdb_extensions() WHERE extension_name = 'fts'"
        )
        extensions = result.fetchall()
        assert len(extensions) == 1
        assert extensions[0][1] is True

        await store.close()

    async def test_context_manager_lifecycle(self):
        """Test that async context manager works correctly."""
        async with LexicalStore(db_path=":memory:") as store:
            assert store._conn is not None

        # Connection should be closed after exiting context


class TestLexicalStoreIndexing:
    """Test chunk indexing operations."""

    async def test_index_chunks_inserts_data(self):
        """Test that index_chunks successfully inserts chunk data."""
        store = LexicalStore(db_path=":memory:")
        await store.initialize()

        chunks = [
            {
                "document_id": "chunk-1",
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "content": "Python is a programming language",
                "file_path": "file:///test.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
            {
                "document_id": "chunk-2",
                "chunk_id": "chunk-2",
                "chunk_index": 1,
                "content": "JavaScript is also a programming language",
                "file_path": "file:///test.js",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
        ]

        count = await store.index_chunks(chunks)

        assert count == 2

        result = await store._conn.execute("SELECT COUNT(*) FROM document_chunks")
        row_count = result.fetchone()[0]
        assert row_count == 2

        await store.close()

    async def test_index_chunks_handles_duplicates(self):
        """Test that duplicate chunks are replaced (INSERT OR REPLACE)."""
        store = LexicalStore(db_path=":memory:")
        await store.initialize()

        chunk = {
            "document_id": "chunk-1",
            "chunk_id": "chunk-1",
            "chunk_index": 0,
            "content": "Original content",
            "file_path": "file:///test.py",
            "source_type": "file",
            "ingested_at": datetime.now(timezone.utc),
            "extra": {},
        }

        await store.index_chunks([chunk])

        chunk["content"] = "Updated content"
        await store.index_chunks([chunk])

        result = await store._conn.execute("SELECT COUNT(*) FROM document_chunks")
        row_count = result.fetchone()[0]
        assert row_count == 1

        result = await store._conn.execute(
            "SELECT content FROM document_chunks WHERE document_id = 'chunk-1'"
        )
        content = result.fetchone()[0]
        assert content == "Updated content"

        await store.close()

    async def test_index_chunks_empty_list_returns_zero(self):
        """Test that indexing empty list returns 0."""
        store = LexicalStore(db_path=":memory:")
        await store.initialize()

        count = await store.index_chunks([])

        assert count == 0
        await store.close()


class TestLexicalStoreSearch:
    """Test search operations with BM25 ranking."""

    async def test_search_returns_ranked_results(self):
        """Test that search returns results ranked by BM25 score."""
        store = LexicalStore(db_path=":memory:")
        await store.initialize()

        chunks = [
            {
                "document_id": "chunk-1",
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "content": "Python programming language tutorial",
                "file_path": "file:///python.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
            {
                "document_id": "chunk-2",
                "chunk_id": "chunk-2",
                "chunk_index": 1,
                "content": "JavaScript basics for beginners",
                "file_path": "file:///js.js",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
            {
                "document_id": "chunk-3",
                "chunk_id": "chunk-3",
                "chunk_index": 2,
                "content": "Advanced Python programming techniques",
                "file_path": "file:///advanced.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
        ]

        await store.index_chunks(chunks)

        results = await store.search(query_text="Python programming", top_k=10)

        assert len(results) == 2
        assert results[0]["document_id"] in ["chunk-1", "chunk-3"]
        assert results[1]["document_id"] in ["chunk-1", "chunk-3"]

        for result in results:
            assert "score" in result
            assert result["score"] > 0

        assert results[0]["score"] >= results[1]["score"]

        await store.close()

    async def test_search_empty_query_returns_nothing(self):
        """Test that search with no matching results returns empty list."""
        store = LexicalStore(db_path=":memory:")
        await store.initialize()

        chunks = [
            {
                "document_id": "chunk-1",
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "content": "Python programming",
                "file_path": "file:///test.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            }
        ]

        await store.index_chunks(chunks)

        results = await store.search(query_text="nonexistent term xyz", top_k=10)

        assert len(results) == 0
        await store.close()

    async def test_search_respects_top_k_limit(self):
        """Test that search respects the top_k parameter."""
        store = LexicalStore(db_path=":memory:")
        await store.initialize()

        chunks = [
            {
                "document_id": f"chunk-{i}",
                "chunk_id": f"chunk-{i}",
                "chunk_index": i,
                "content": f"Python programming example {i}",
                "file_path": f"file:///test{i}.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            }
            for i in range(10)
        ]

        await store.index_chunks(chunks)

        results = await store.search(query_text="Python", top_k=3)

        assert len(results) == 3
        await store.close()

    async def test_search_with_document_ids_filter(self):
        """Test that search filters by document_ids."""
        store = LexicalStore(db_path=":memory:")
        await store.initialize()

        chunks = [
            {
                "document_id": "chunk-1",
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "content": "Python programming",
                "file_path": "file:///test1.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
            {
                "document_id": "chunk-2",
                "chunk_id": "chunk-2",
                "chunk_index": 1,
                "content": "Python tutorial",
                "file_path": "file:///test2.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
            {
                "document_id": "chunk-3",
                "chunk_id": "chunk-3",
                "chunk_index": 2,
                "content": "Python examples",
                "file_path": "file:///test3.py",
                "source_type": "file",
                "ingested_at": datetime.now(timezone.utc),
                "extra": {},
            },
        ]

        await store.index_chunks(chunks)

        results = await store.search(
            query_text="Python",
            top_k=10,
            filters={"document_ids": ["chunk-1", "chunk-3"]},
        )

        assert len(results) == 2
        assert all(r["document_id"] in ["chunk-1", "chunk-3"] for r in results)
        await store.close()

    async def test_search_result_structure(self):
        """Test that search results have expected structure."""
        store = LexicalStore(db_path=":memory:")
        await store.initialize()

        chunk = {
            "document_id": "chunk-1",
            "chunk_id": "chunk-1",
            "chunk_index": 0,
            "content": "Python programming",
            "file_path": "file:///test.py",
            "source_type": "file",
            "ingested_at": datetime.now(timezone.utc),
            "extra": {"key": "value"},
        }

        await store.index_chunks([chunk])

        results = await store.search(query_text="Python", top_k=10)

        assert len(results) == 1
        result = results[0]

        assert result["document_id"] == "chunk-1"
        assert result["chunk_id"] == "chunk-1"
        assert result["chunk_index"] == 0
        assert result["content"] == "Python programming"
        assert result["file_path"] == "file:///test.py"
        assert result["source_type"] == "file"
        assert "ingested_at" in result
        assert result["extra"] == {"key": "value"}
        assert "score" in result
        assert isinstance(result["score"], (int, float))

        await store.close()
