"""Unit tests for the LiteralStore service."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from txtsearch.services.literal_store import (
    LiteralQueryResult,
    LiteralStore,
    RipgrepNotFoundError,
)


class TestLiteralStoreCheckAvailable:
    """Tests for checking ripgrep availability."""

    async def test_check_available_returns_true_when_rg_found(self) -> None:
        store = LiteralStore()

        with patch("shutil.which", return_value="/usr/bin/rg"):
            available = await store.check_available()

        assert available is True

    async def test_check_available_returns_false_when_rg_not_found(self) -> None:
        store = LiteralStore()

        with patch("shutil.which", return_value=None):
            available = await store.check_available()

        assert available is False


class TestLiteralStoreSearch:
    """Tests for searching with ripgrep."""

    async def test_search_raises_when_ripgrep_not_available(self) -> None:
        store = LiteralStore()

        with patch("shutil.which", return_value=None):
            with pytest.raises(RipgrepNotFoundError):
                await store.search("pattern", Path("/tmp"), limit=10)

    async def test_search_returns_empty_on_no_matches(self) -> None:
        store = LiteralStore()

        mock_result = MagicMock()
        mock_result.returncode = 1  # ripgrep exit code for no matches
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("shutil.which", return_value="/usr/bin/rg"),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            results = await store.search("nonexistent", Path("/tmp"), limit=10)

        assert results == []
        mock_run.assert_called_once()

    async def test_search_parses_match_results(self) -> None:
        store = LiteralStore()

        json_output = """{"type":"begin","data":{"path":{"text":"/tmp/test.py"}}}
{"type":"match","data":{"path":{"text":"/tmp/test.py"},"lines":{"text":"def test_function():\\n"},"line_number":42,"absolute_offset":100,"submatches":[{"match":{"text":"test"},"start":4,"end":8}]}}
{"type":"end","data":{"path":{"text":"/tmp/test.py"},"stats":{"matched_lines":1}}}"""

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json_output
        mock_result.stderr = ""

        with (
            patch("shutil.which", return_value="/usr/bin/rg"),
            patch("subprocess.run", return_value=mock_result),
        ):
            results = await store.search("test", Path("/tmp"), limit=10)

        assert len(results) == 1
        assert results[0].path == "/tmp/test.py"
        assert results[0].line_number == 42
        assert results[0].line_text == "def test_function():"
        assert results[0].submatches == [(4, 8)]

    async def test_search_respects_limit(self) -> None:
        store = LiteralStore()

        # Generate output with multiple matches
        matches = ""
        for i in range(5):
            matches += f'{{"type":"match","data":{{"path":{{"text":"/tmp/test.py"}},"lines":{{"text":"line {i}\\n"}},"line_number":{i + 1},"submatches":[]}}}}\n'

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = matches
        mock_result.stderr = ""

        with (
            patch("shutil.which", return_value="/usr/bin/rg"),
            patch("subprocess.run", return_value=mock_result),
        ):
            results = await store.search("line", Path("/tmp"), limit=3)

        assert len(results) == 3

    async def test_search_passes_correct_args_to_ripgrep(self) -> None:
        store = LiteralStore()

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("shutil.which", return_value="/usr/bin/rg"),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            await store.search("my_pattern", Path("/some/dir"), limit=5)

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "rg" in args[0]
        assert "--json" in args
        assert "--max-count" in args
        assert "5" in args
        assert "my_pattern" in args
        assert "/some/dir" in args

    async def test_search_raises_on_ripgrep_error(self) -> None:
        store = LiteralStore()

        mock_result = MagicMock()
        mock_result.returncode = 2  # ripgrep exit code for errors
        mock_result.stdout = ""
        mock_result.stderr = "error: unknown flag"
        mock_result.args = ["rg", "--json", "pattern", "/tmp"]

        with (
            patch("shutil.which", return_value="/usr/bin/rg"),
            patch("subprocess.run", return_value=mock_result),
        ):
            with pytest.raises(Exception):  # CalledProcessError
                await store.search("pattern", Path("/tmp"), limit=10)


class TestLiteralStoreJsonParsing:
    """Tests for JSON output parsing."""

    async def test_parse_handles_multiple_matches_in_same_file(self) -> None:
        store = LiteralStore()

        json_output = """{"type":"match","data":{"path":{"text":"/tmp/test.py"},"lines":{"text":"line one\\n"},"line_number":1,"submatches":[]}}
{"type":"match","data":{"path":{"text":"/tmp/test.py"},"lines":{"text":"line two\\n"},"line_number":2,"submatches":[]}}"""

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json_output
        mock_result.stderr = ""

        with (
            patch("shutil.which", return_value="/usr/bin/rg"),
            patch("subprocess.run", return_value=mock_result),
        ):
            results = await store.search("line", Path("/tmp"), limit=10)

        assert len(results) == 2
        assert results[0].line_number == 1
        assert results[1].line_number == 2

    async def test_parse_handles_matches_across_multiple_files(self) -> None:
        store = LiteralStore()

        json_output = """{"type":"match","data":{"path":{"text":"/tmp/a.py"},"lines":{"text":"match in a\\n"},"line_number":1,"submatches":[]}}
{"type":"match","data":{"path":{"text":"/tmp/b.py"},"lines":{"text":"match in b\\n"},"line_number":5,"submatches":[]}}"""

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json_output
        mock_result.stderr = ""

        with (
            patch("shutil.which", return_value="/usr/bin/rg"),
            patch("subprocess.run", return_value=mock_result),
        ):
            results = await store.search("match", Path("/tmp"), limit=10)

        assert len(results) == 2
        assert results[0].path == "/tmp/a.py"
        assert results[1].path == "/tmp/b.py"

    async def test_parse_handles_multiple_submatches(self) -> None:
        store = LiteralStore()

        json_output = """{"type":"match","data":{"path":{"text":"/tmp/test.py"},"lines":{"text":"test test test\\n"},"line_number":1,"submatches":[{"match":{"text":"test"},"start":0,"end":4},{"match":{"text":"test"},"start":5,"end":9},{"match":{"text":"test"},"start":10,"end":14}]}}"""

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json_output
        mock_result.stderr = ""

        with (
            patch("shutil.which", return_value="/usr/bin/rg"),
            patch("subprocess.run", return_value=mock_result),
        ):
            results = await store.search("test", Path("/tmp"), limit=10)

        assert len(results) == 1
        assert results[0].submatches == [(0, 4), (5, 9), (10, 14)]

    async def test_parse_skips_non_match_messages(self) -> None:
        store = LiteralStore()

        json_output = """{"type":"begin","data":{"path":{"text":"/tmp/test.py"}}}
{"type":"match","data":{"path":{"text":"/tmp/test.py"},"lines":{"text":"match\\n"},"line_number":1,"submatches":[]}}
{"type":"end","data":{"path":{"text":"/tmp/test.py"}}}
{"type":"summary","data":{"elapsed_total":{"secs":0}}}"""

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json_output
        mock_result.stderr = ""

        with (
            patch("shutil.which", return_value="/usr/bin/rg"),
            patch("subprocess.run", return_value=mock_result),
        ):
            results = await store.search("match", Path("/tmp"), limit=10)

        # Should only have the one match, not begin/end/summary
        assert len(results) == 1

    async def test_parse_handles_empty_output(self) -> None:
        store = LiteralStore()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("shutil.which", return_value="/usr/bin/rg"),
            patch("subprocess.run", return_value=mock_result),
        ):
            results = await store.search("match", Path("/tmp"), limit=10)

        assert results == []

    async def test_parse_handles_invalid_json_lines(self) -> None:
        store = LiteralStore()

        json_output = """not valid json
{"type":"match","data":{"path":{"text":"/tmp/test.py"},"lines":{"text":"valid match\\n"},"line_number":1,"submatches":[]}}
also not valid"""

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json_output
        mock_result.stderr = ""

        with (
            patch("shutil.which", return_value="/usr/bin/rg"),
            patch("subprocess.run", return_value=mock_result),
        ):
            results = await store.search("match", Path("/tmp"), limit=10)

        # Should skip invalid lines and return the valid match
        assert len(results) == 1
        assert results[0].path == "/tmp/test.py"


class TestLiteralQueryResult:
    """Tests for the LiteralQueryResult dataclass."""

    def test_immutable(self) -> None:
        result = LiteralQueryResult(
            path="/tmp/test.py",
            line_number=1,
            line_text="test",
            submatches=[],
        )

        with pytest.raises(Exception):  # frozen dataclass raises FrozenInstanceError
            result.path = "/other/path.py"  # type: ignore

    def test_equality(self) -> None:
        result1 = LiteralQueryResult(
            path="/tmp/test.py",
            line_number=1,
            line_text="test",
            submatches=[(0, 4)],
        )
        result2 = LiteralQueryResult(
            path="/tmp/test.py",
            line_number=1,
            line_text="test",
            submatches=[(0, 4)],
        )
        result3 = LiteralQueryResult(
            path="/tmp/other.py",
            line_number=1,
            line_text="test",
            submatches=[(0, 4)],
        )

        assert result1 == result2
        assert result1 != result3


class TestRipgrepNotFoundError:
    """Tests for the RipgrepNotFoundError exception."""

    def test_default_message(self) -> None:
        error = RipgrepNotFoundError()
        assert "Ripgrep" in str(error)
        assert "rg" in str(error)

    def test_custom_message(self) -> None:
        error = RipgrepNotFoundError("Custom error message")
        assert str(error) == "Custom error message"
