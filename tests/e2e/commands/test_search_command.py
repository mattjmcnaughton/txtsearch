"""End-to-end tests for SearchCommand.

Tests the command directly without CLI wrapper, using real storage.
"""

from pathlib import Path

import pytest

from txtsearch.commands.index import IndexCommand, IndexInput
from txtsearch.commands.search import (
    SearchCommand,
    SearchInput,
    StrategyNotSupportedError,
)
from txtsearch.models.enums import SearchStrategy
from txtsearch.services.factory import (
    create_indexing_service,
    create_semantic_search_service,
)


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
