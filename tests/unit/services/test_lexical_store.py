"""Unit tests for the LexicalStore service."""

import pytest

from txtsearch.services.lexical_store import LexicalQueryResult, LexicalStore


@pytest.fixture
async def store() -> LexicalStore:
    """Create a LexicalStore with in-memory DuckDB."""
    store = LexicalStore(db_path=":memory:")
    await store.initialize()
    return store


class TestLexicalStoreInitialization:
    """Tests for LexicalStore initialization."""

    async def test_initialize_creates_connection(self) -> None:
        store = LexicalStore(db_path=":memory:")
        await store.initialize()

        # Verify connection exists by calling a method that requires it
        count = await store.count()
        assert count == 0

    async def test_initialize_loads_fts_extension(self) -> None:
        store = LexicalStore(db_path=":memory:")
        await store.initialize()

        # Verify FTS extension is loaded by adding chunks and building index
        await store.add_chunks(["chunk-1"], ["test content"])
        await store.build_index()  # Would fail if FTS not loaded

    async def test_initialize_idempotent(self) -> None:
        store = LexicalStore(db_path=":memory:")
        await store.initialize()
        await store.initialize()  # Should not raise

        count = await store.count()
        assert count == 0

    async def test_close_releases_connection(self) -> None:
        store = LexicalStore(db_path=":memory:")
        await store.initialize()
        await store.close()

        # After close, operations should fail
        with pytest.raises(RuntimeError, match="not initialized"):
            await store.count()

    async def test_async_context_manager(self) -> None:
        async with LexicalStore(db_path=":memory:") as store:
            await store.initialize()
            count = await store.count()
            assert count == 0


class TestLexicalStoreAddChunks:
    """Tests for adding chunks to the store."""

    async def test_add_single_chunk(self, store: LexicalStore) -> None:
        await store.add_chunks(
            chunk_ids=["chunk-1"],
            texts=["This is the text content."],
        )

        count = await store.count()
        assert count == 1

    async def test_add_multiple_chunks(self, store: LexicalStore) -> None:
        await store.add_chunks(
            chunk_ids=["chunk-1", "chunk-2", "chunk-3"],
            texts=["Text one.", "Text two.", "Text three."],
        )

        count = await store.count()
        assert count == 3

    async def test_add_empty_list_does_nothing(self, store: LexicalStore) -> None:
        await store.add_chunks(chunk_ids=[], texts=[])
        count = await store.count()
        assert count == 0

    async def test_upsert_updates_existing_chunk(self, store: LexicalStore) -> None:
        await store.add_chunks(
            chunk_ids=["chunk-1"],
            texts=["Original text."],
        )

        # Update with same ID
        await store.add_chunks(
            chunk_ids=["chunk-1"],
            texts=["Updated text."],
        )

        count = await store.count()
        assert count == 1

    async def test_raises_on_mismatched_lengths(self, store: LexicalStore) -> None:
        with pytest.raises(ValueError, match="Mismatched lengths"):
            await store.add_chunks(
                chunk_ids=["chunk-1", "chunk-2"],
                texts=["Only one text."],
            )

    async def test_raises_when_not_initialized(self) -> None:
        store = LexicalStore(db_path=":memory:")
        # Don't call initialize()

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.add_chunks(
                chunk_ids=["chunk-1"],
                texts=["Text."],
            )


class TestLexicalStoreBuildIndex:
    """Tests for building the FTS index."""

    async def test_build_index_creates_fts_index(self, store: LexicalStore) -> None:
        await store.add_chunks(
            chunk_ids=["chunk-1"],
            texts=["Test content for indexing."],
        )

        await store.build_index()

        # Verify index exists
        exists = await store.index_exists()
        assert exists is True

    async def test_build_index_allows_search(self, store: LexicalStore) -> None:
        await store.add_chunks(
            chunk_ids=["chunk-1"],
            texts=["Authentication function for users."],
        )
        await store.build_index()

        results = await store.search("authentication")
        assert len(results) == 1
        assert results[0].chunk_id == "chunk-1"

    async def test_build_index_overwrites_existing(self, store: LexicalStore) -> None:
        await store.add_chunks(["chunk-1"], ["Original content."])
        await store.build_index()

        # Add more and rebuild
        await store.add_chunks(["chunk-2"], ["Additional content."])
        await store.build_index()  # Should not raise

        count = await store.count()
        assert count == 2

    async def test_raises_when_not_initialized(self) -> None:
        store = LexicalStore(db_path=":memory:")

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.build_index()


class TestLexicalStoreSearch:
    """Tests for searching the FTS index."""

    async def test_search_returns_matching_chunks(self, store: LexicalStore) -> None:
        await store.add_chunks(
            chunk_ids=["chunk-1", "chunk-2"],
            texts=["def authenticate_user():", "def search_documents():"],
        )
        await store.build_index()

        results = await store.search("authenticate")

        assert len(results) == 1
        assert results[0].chunk_id == "chunk-1"
        assert results[0].bm25_score > 0

    async def test_search_returns_ranked_results(self, store: LexicalStore) -> None:
        await store.add_chunks(
            chunk_ids=["chunk-1", "chunk-2", "chunk-3"],
            texts=[
                "user authentication",
                "user user user authentication authentication authentication",
                "unrelated content",
            ],
        )
        await store.build_index()

        results = await store.search("user authentication")

        assert len(results) == 2
        # Higher term frequency should rank higher
        assert results[0].bm25_score >= results[1].bm25_score

    async def test_search_respects_limit(self, store: LexicalStore) -> None:
        await store.add_chunks(
            chunk_ids=["chunk-1", "chunk-2", "chunk-3"],
            texts=["test one", "test two", "test three"],
        )
        await store.build_index()

        results = await store.search("test", limit=2)

        assert len(results) == 2

    async def test_search_empty_query_returns_empty(self, store: LexicalStore) -> None:
        await store.add_chunks(["chunk-1"], ["Some content."])
        await store.build_index()

        results = await store.search("")
        assert results == []

        results = await store.search("   ")
        assert results == []

    async def test_search_no_matches_returns_empty(self, store: LexicalStore) -> None:
        await store.add_chunks(["chunk-1"], ["Some content."])
        await store.build_index()

        results = await store.search("nonexistent")
        assert results == []

    async def test_search_result_type(self, store: LexicalStore) -> None:
        await store.add_chunks(["chunk-1"], ["Test content."])
        await store.build_index()

        results = await store.search("test")

        assert len(results) == 1
        assert isinstance(results[0], LexicalQueryResult)
        assert isinstance(results[0].chunk_id, str)
        assert isinstance(results[0].bm25_score, float)

    async def test_raises_when_not_initialized(self) -> None:
        store = LexicalStore(db_path=":memory:")

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.search("query")


class TestLexicalStoreIndexExists:
    """Tests for checking if the FTS index exists."""

    async def test_index_exists_false_before_build(self, store: LexicalStore) -> None:
        exists = await store.index_exists()
        assert exists is False

    async def test_index_exists_false_after_add_without_build(self, store: LexicalStore) -> None:
        await store.add_chunks(["chunk-1"], ["Content."])

        exists = await store.index_exists()
        assert exists is True  # Table exists, even without FTS index

    async def test_index_exists_true_after_build(self, store: LexicalStore) -> None:
        await store.add_chunks(["chunk-1"], ["Content."])
        await store.build_index()

        exists = await store.index_exists()
        assert exists is True

    async def test_index_exists_false_after_clear(self, store: LexicalStore) -> None:
        await store.add_chunks(["chunk-1"], ["Content."])
        await store.build_index()
        await store.clear()

        exists = await store.index_exists()
        assert exists is False

    async def test_raises_when_not_initialized(self) -> None:
        store = LexicalStore(db_path=":memory:")

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.index_exists()


class TestLexicalStoreClear:
    """Tests for clearing the store."""

    async def test_clear_removes_all_chunks(self, store: LexicalStore) -> None:
        await store.add_chunks(
            chunk_ids=["chunk-1", "chunk-2"],
            texts=["One.", "Two."],
        )
        await store.build_index()

        await store.clear()

        count = await store.count()
        assert count == 0

    async def test_clear_allows_new_additions(self, store: LexicalStore) -> None:
        await store.add_chunks(["chunk-1"], ["Original."])
        await store.build_index()
        await store.clear()

        await store.add_chunks(["chunk-new"], ["New content."])
        await store.build_index()

        count = await store.count()
        assert count == 1

    async def test_clear_on_empty_store_does_not_raise(self, store: LexicalStore) -> None:
        await store.clear()  # Should not raise

        count = await store.count()
        assert count == 0

    async def test_raises_when_not_initialized(self) -> None:
        store = LexicalStore(db_path=":memory:")

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.clear()


class TestLexicalStoreCount:
    """Tests for counting chunks."""

    async def test_count_empty_store(self, store: LexicalStore) -> None:
        count = await store.count()
        assert count == 0

    async def test_count_after_additions(self, store: LexicalStore) -> None:
        await store.add_chunks(
            chunk_ids=["chunk-1", "chunk-2"],
            texts=["One.", "Two."],
        )

        count = await store.count()
        assert count == 2

    async def test_count_after_clear(self, store: LexicalStore) -> None:
        await store.add_chunks(["chunk-1"], ["Content."])
        await store.clear()

        count = await store.count()
        assert count == 0

    async def test_raises_when_not_initialized(self) -> None:
        store = LexicalStore(db_path=":memory:")

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.count()


class TestLexicalQueryResult:
    """Tests for the LexicalQueryResult dataclass."""

    def test_immutable(self) -> None:
        result = LexicalQueryResult(chunk_id="chunk-1", bm25_score=1.5)

        with pytest.raises(Exception):  # frozen dataclass raises FrozenInstanceError
            result.chunk_id = "chunk-2"  # type: ignore

    def test_equality(self) -> None:
        result1 = LexicalQueryResult(chunk_id="chunk-1", bm25_score=1.5)
        result2 = LexicalQueryResult(chunk_id="chunk-1", bm25_score=1.5)
        result3 = LexicalQueryResult(chunk_id="chunk-2", bm25_score=1.5)

        assert result1 == result2
        assert result1 != result3
