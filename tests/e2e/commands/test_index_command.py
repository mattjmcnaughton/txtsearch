"""End-to-end tests for IndexCommand.

Tests the command directly without CLI wrapper, using real storage.
"""

from pathlib import Path

import pytest

from txtsearch.commands.index import IndexCommand, IndexInput
from txtsearch.services.factory import create_indexing_service


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


@pytest.mark.slow
@pytest.mark.external
class TestIndexCommandHappyPath:
    """Happy path tests for IndexCommand."""

    async def test_index_directory(self, sample_codebase: Path) -> None:
        """Index a directory and verify results."""
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
            output = await command.run(input_dto)

        assert output.result.files_processed == 2
        assert output.result.chunks_created >= 2
        assert output.result.files_skipped == 0
        assert output.result.errors == []
        assert output.index_dir == index_dir
        assert index_dir.exists()
        assert (index_dir / "meta.db").exists()
        assert (index_dir / "semantic").exists()

    async def test_index_empty_directory(self, tmp_path: Path) -> None:
        """Index an empty directory returns zero counts."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        index_dir = empty_dir / ".txtsearch"

        input_dto = IndexInput(
            directory=empty_dir,
            output_dir=index_dir,
        )

        async with create_indexing_service(
            output_dir=index_dir,
        ) as service:
            command = IndexCommand(indexing_service=service)
            output = await command.run(input_dto)

        assert output.result.files_processed == 0
        assert output.result.chunks_created == 0


@pytest.mark.slow
@pytest.mark.external
class TestIndexCommandErrors:
    """Error handling tests for IndexCommand."""

    async def test_raises_on_nonexistent_directory(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError for nonexistent directory."""
        nonexistent = tmp_path / "nonexistent"
        index_dir = tmp_path / ".txtsearch"

        input_dto = IndexInput(
            directory=nonexistent,
            output_dir=index_dir,
        )

        async with create_indexing_service(output_dir=index_dir) as service:
            command = IndexCommand(indexing_service=service)

            with pytest.raises(FileNotFoundError):
                await command.run(input_dto)

    async def test_raises_on_file_instead_of_directory(self, tmp_path: Path) -> None:
        """Raises NotADirectoryError when path is a file."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")
        index_dir = tmp_path / ".txtsearch"

        input_dto = IndexInput(
            directory=file_path,
            output_dir=index_dir,
        )

        async with create_indexing_service(output_dir=index_dir) as service:
            command = IndexCommand(indexing_service=service)

            with pytest.raises(NotADirectoryError):
                await command.run(input_dto)
