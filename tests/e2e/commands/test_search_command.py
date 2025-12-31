"""End-to-end tests for SearchCommand.

Tests the command directly without CLI wrapper, using real storage.
"""

from pathlib import Path

import duckdb
import pytest

from txtsearch.commands.index import IndexCommand, IndexInput
from txtsearch.commands.search import (
    SearchCommand,
    SearchInput,
    StrategyNotSupportedError,
)
from txtsearch.models.enums import SearchStrategy
from txtsearch.services.factory import (
    LEXICAL_DB_FILENAME,
    create_indexing_service,
    create_lexical_search_service,
    create_semantic_search_service,
)
from txtsearch.services.lexical_search import LexicalIndexNotFoundError


@pytest.fixture
def sample_codebase(tmp_path: Path) -> Path:
    """Create a sample codebase with Python files for testing."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    (src_dir / "auth.py").write_text(
        '''"""Authentication module for user login."""

def authenticate_user(username: str, password: str) -> bool:
    """Authenticate a user with username and password."""
    return username == "admin" and password == "secret"
'''
    )

    (src_dir / "search.py").write_text(
        '''"""Search module for querying indexed documents."""

def semantic_search(query: str, top_k: int = 10) -> list:
    """Perform semantic search over indexed documents."""
    return []
'''
    )

    return tmp_path


@pytest.fixture
async def indexed_codebase(sample_codebase: Path) -> Path:
    """Create and index a sample codebase."""
    src_dir = sample_codebase / "src"
    index_dir = src_dir / ".txtsearch"

    input_dto = IndexInput(
        directory=src_dir,
        output_dir=index_dir,
        include_patterns=["*.py"],
    )

    async with create_indexing_service(
        output_dir=index_dir,
        include_patterns=["*.py"],
    ) as service:
        command = IndexCommand(indexing_service=service)
        await command.run(input_dto)

    return sample_codebase


@pytest.mark.slow
@pytest.mark.external
class TestSearchCommandHappyPath:
    """Happy path tests for SearchCommand."""

    async def test_search_indexed_directory(self, indexed_codebase: Path) -> None:
        """Search an indexed directory returns results."""
        src_dir = indexed_codebase / "src"
        index_dir = src_dir / ".txtsearch"

        input_dto = SearchInput(
            query="authentication",
            directory=src_dir,
            strategy=SearchStrategy.SEMANTIC,
            limit=10,
        )

        async with create_semantic_search_service(index_dir=index_dir) as service:
            command = SearchCommand(search_service=service)
            output = await command.run(input_dto)

        assert output.query == "authentication"
        assert output.strategy == SearchStrategy.SEMANTIC
        assert isinstance(output.hits, list)
        assert output.result_count >= 0

    async def test_search_returns_structured_output(self, indexed_codebase: Path) -> None:
        """Search output has expected structure."""
        src_dir = indexed_codebase / "src"
        index_dir = src_dir / ".txtsearch"

        input_dto = SearchInput(
            query="search query",
            directory=src_dir,
            strategy=SearchStrategy.SEMANTIC,
            limit=5,
        )

        async with create_semantic_search_service(index_dir=index_dir) as service:
            command = SearchCommand(search_service=service)
            output = await command.run(input_dto)

        assert output.query == "search query"
        assert output.strategy == SearchStrategy.SEMANTIC

        for hit in output.hits:
            assert hit.document_id is not None
            assert hit.score is not None
            assert 0.0 <= hit.score <= 1.0


@pytest.mark.slow
@pytest.mark.external
class TestSearchCommandErrors:
    """Error handling tests for SearchCommand."""

    async def test_raises_on_unsupported_strategy(self, indexed_codebase: Path) -> None:
        """Raises StrategyNotSupportedError for non-semantic strategies."""
        src_dir = indexed_codebase / "src"
        index_dir = src_dir / ".txtsearch"

        input_dto = SearchInput(
            query="test",
            directory=src_dir,
            strategy=SearchStrategy.LITERAL,
        )

        async with create_semantic_search_service(index_dir=index_dir) as service:
            command = SearchCommand(search_service=service)

            with pytest.raises(StrategyNotSupportedError):
                await command.run(input_dto)


@pytest.mark.slow
@pytest.mark.external
class TestLexicalSearchIndexCreation:
    """Test that indexing creates DuckDB FTS tables (Acceptance Criterion #1)."""

    async def test_index_creates_duckdb_fts_tables(self, indexed_codebase: Path) -> None:
        """After indexing, DuckDB lexical.db exists with FTS index."""
        src_dir = indexed_codebase / "src"
        index_dir = src_dir / ".txtsearch"
        lexical_db_path = index_dir / LEXICAL_DB_FILENAME

        # Verify lexical.db file exists
        assert lexical_db_path.exists(), "lexical.db should exist after indexing"

        # Connect to DuckDB and verify FTS table and content
        conn = duckdb.connect(str(lexical_db_path), read_only=True)
        try:
            # Verify chunks_fts table exists and has data
            result = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()
            assert result is not None
            chunk_count = result[0]
            assert chunk_count > 0, "chunks_fts table should contain indexed chunks"

            # Verify FTS index exists by checking for fts_main_chunks_fts schema
            tables = conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'fts_main_chunks_fts'"
            ).fetchall()
            assert len(tables) > 0, "FTS index tables should exist in fts_main_chunks_fts schema"
        finally:
            conn.close()


@pytest.mark.slow
@pytest.mark.external
class TestLexicalSearchHappyPath:
    """Test lexical search returns ranked results (Acceptance Criterion #2)."""

    async def test_lexical_search_returns_ranked_results(self, indexed_codebase: Path) -> None:
        """Lexical search returns relevance-scored matches with snippets."""
        src_dir = indexed_codebase / "src"
        index_dir = src_dir / ".txtsearch"

        input_dto = SearchInput(
            query="authenticate",
            directory=src_dir,
            strategy=SearchStrategy.LEXICAL,
            limit=10,
        )

        async with create_lexical_search_service(index_dir=index_dir) as service:
            command = SearchCommand(search_service=service)
            output = await command.run(input_dto)

        assert output.query == "authenticate"
        assert output.strategy == SearchStrategy.LEXICAL
        assert isinstance(output.hits, list)
        assert output.result_count > 0, "Should find matches for 'authenticate'"

        # Verify results have expected structure
        for hit in output.hits:
            assert hit.document_id is not None
            assert hit.score is not None
            assert 0.0 <= hit.score <= 1.0, "Score should be normalized to 0-1 range"
            # Verify extra contains lexical-specific fields
            assert "bm25_score" in hit.extra
            assert hit.extra["bm25_score"] > 0

    async def test_lexical_search_returns_snippets(self, indexed_codebase: Path) -> None:
        """Lexical search includes content snippets in results."""
        src_dir = indexed_codebase / "src"
        index_dir = src_dir / ".txtsearch"

        input_dto = SearchInput(
            query="password",
            directory=src_dir,
            strategy=SearchStrategy.LEXICAL,
            limit=10,
        )

        async with create_lexical_search_service(index_dir=index_dir) as service:
            command = SearchCommand(search_service=service)
            output = await command.run(input_dto)

        assert output.result_count > 0
        # Verify snippets are present
        for hit in output.hits:
            assert hit.snippet is not None, "Hit should include snippet"
            assert len(hit.snippet) > 0, "Snippet should not be empty"

    async def test_lexical_search_results_are_ranked(self, indexed_codebase: Path) -> None:
        """Lexical search results are ordered by relevance (highest score first)."""
        src_dir = indexed_codebase / "src"
        index_dir = src_dir / ".txtsearch"

        input_dto = SearchInput(
            query="search",
            directory=src_dir,
            strategy=SearchStrategy.LEXICAL,
            limit=10,
        )

        async with create_lexical_search_service(index_dir=index_dir) as service:
            command = SearchCommand(search_service=service)
            output = await command.run(input_dto)

        if len(output.hits) > 1:
            # Verify scores are in descending order
            scores = [hit.score for hit in output.hits]
            assert scores == sorted(scores, reverse=True), "Results should be ranked by score"


@pytest.mark.slow
@pytest.mark.external
class TestLexicalSearchMissingIndex:
    """Test error handling when lexical index is missing (Acceptance Criterion #3)."""

    async def test_lexical_search_missing_index_raises_error(self, sample_codebase: Path) -> None:
        """Lexical search on non-indexed directory raises LexicalIndexNotFoundError."""
        src_dir = sample_codebase / "src"
        index_dir = src_dir / ".txtsearch"

        # Create the index directory but do NOT run indexing
        index_dir.mkdir(parents=True, exist_ok=True)

        input_dto = SearchInput(
            query="authenticate",
            directory=src_dir,
            strategy=SearchStrategy.LEXICAL,
            limit=10,
        )

        async with create_lexical_search_service(index_dir=index_dir) as service:
            command = SearchCommand(search_service=service)

            with pytest.raises(LexicalIndexNotFoundError) as exc_info:
                await command.run(input_dto)

            # Verify error message is helpful
            error_message = str(exc_info.value)
            assert "index" in error_message.lower()
            assert "txtsearch" in error_message.lower()
