"""End-to-end tests for lexical search command."""

import tempfile
from pathlib import Path

import pytest

from txtsearch.commands.index import IndexCommand, IndexInput
from txtsearch.commands.search import SearchCommand, SearchInput
from txtsearch.models.enums import SearchStrategy


@pytest.mark.slow
@pytest.mark.external
class TestLexicalSearchCommandE2E:
    """End-to-end tests for lexical search through CLI commands."""

    async def test_index_and_search_workflow(self):
        """Test full workflow: index files -> search with lexical strategy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            test_file = tmpdir_path / "test.py"
            test_file.write_text(
                "def authenticate_user(username, password):\n"
                "    '''Authenticate user with username and password.'''\n"
                "    return verify_credentials(username, password)\n"
            )

            another_file = tmpdir_path / "utils.py"
            another_file.write_text(
                "def calculate_sum(a, b):\n"
                "    '''Calculate the sum of two numbers.'''\n"
                "    return a + b\n"
            )

            output_dir = tmpdir_path / "index"
            output_dir.mkdir()

            index_input = IndexInput(
                directory=tmpdir_path,
                output_directory=output_dir,
                include_patterns=["*.py"],
            )

            from txtsearch.services.factory import create_indexing_service

            indexing_service = create_indexing_service(
                output_dir=output_dir,
                include_patterns=["*.py"],
                enable_lexical=True,
            )

            async with indexing_service:
                result = await indexing_service.index_directory(tmpdir_path)

            assert result.files_processed > 0
            assert result.chunks_created > 0

            lexical_db = output_dir / "lexical.duckdb"
            assert lexical_db.exists()

            search_input = SearchInput(
                query="authenticate password",
                directory=output_dir,
                strategy=SearchStrategy.LEXICAL,
                limit=10,
            )

            search_command = SearchCommand()
            search_output = await search_command.run(search_input)

            assert search_output.strategy == SearchStrategy.LEXICAL
            assert len(search_output.hits) > 0
            assert all(hit.strategy == SearchStrategy.LEXICAL for hit in search_output.hits)
            assert all(0.0 <= hit.score <= 1.0 for hit in search_output.hits)

    async def test_lexical_search_without_index_raises_error(self):
        """Test that searching without lexical index raises helpful error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            search_input = SearchInput(
                query="test query",
                directory=output_dir,
                strategy=SearchStrategy.LEXICAL,
            )

            search_command = SearchCommand()

            from txtsearch.commands.search import IndexNotFoundError

            with pytest.raises(IndexNotFoundError) as exc_info:
                await search_command.run(search_input)

            assert "lexical.duckdb" in str(exc_info.value).lower()
            assert "index" in str(exc_info.value).lower()
