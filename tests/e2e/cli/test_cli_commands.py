"""End-to-end tests for CLI commands.

These tests exercise the happy path of CLI commands with real file I/O and storage.
They are marked as slow since they involve indexing and embedding operations.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from txtsearch.cli import app


runner = CliRunner()


@pytest.fixture
def sample_codebase(tmp_path: Path) -> Path:
    """Create a sample codebase with Python files for testing."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    (src_dir / "auth.py").write_text(
        '''"""Authentication module for user login."""

def authenticate_user(username: str, password: str) -> bool:
    """Authenticate a user with username and password.

    Args:
        username: The user's login name.
        password: The user's password.

    Returns:
        True if authentication succeeds, False otherwise.
    """
    return username == "admin" and password == "secret"
'''
    )

    (src_dir / "search.py").write_text(
        '''"""Search module for querying indexed documents."""

def semantic_search(query: str, top_k: int = 10) -> list:
    """Perform semantic search over indexed documents.

    Args:
        query: Natural language search query.
        top_k: Maximum number of results to return.

    Returns:
        List of search results with scores.
    """
    return []
'''
    )

    return tmp_path


@pytest.mark.slow
@pytest.mark.external
class TestCLIHappyPath:
    """Happy path tests for the CLI index and search workflow."""

    def test_index_and_search_workflow(self, sample_codebase: Path) -> None:
        """Full workflow: index a directory and search it."""
        src_dir = sample_codebase / "src"

        # Index the directory
        index_result = runner.invoke(app, ["index", str(src_dir)])
        assert index_result.exit_code == 0
        assert "Indexed" in index_result.output

        # Verify index was created
        index_dir = src_dir / ".txtsearch"
        assert index_dir.exists()
        assert (index_dir / "meta.db").exists()
        assert (index_dir / "semantic").exists()

        # Search with human-readable output
        search_result = runner.invoke(
            app,
            ["search", "authentication", "--directory", str(src_dir)],
        )
        assert search_result.exit_code == 0

    def test_search_json_output(self, sample_codebase: Path) -> None:
        """Search with JSON output returns valid structured data."""
        src_dir = sample_codebase / "src"

        # Index first
        runner.invoke(app, ["index", str(src_dir)])

        # Search with JSON output
        result = runner.invoke(
            app,
            ["search", "search query", "--directory", str(src_dir), "--json"],
        )

        assert result.exit_code == 0

        output = json.loads(result.output)
        assert "query" in output
        assert "strategy" in output
        assert output["strategy"] == "semantic"
        assert "result_count" in output
        assert "results" in output
        assert isinstance(output["results"], list)
