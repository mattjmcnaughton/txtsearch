"""Unit tests for the FileWalker service."""

from pathlib import Path

import pytest

from txtsearch.services.file_walker import FileWalker


@pytest.fixture
def tmp_directory_with_files(tmp_path: Path) -> Path:
    """Create a temporary directory with sample files for testing."""
    (tmp_path / "file1.py").write_text("print('hello')")
    (tmp_path / "file2.txt").write_text("some text")
    (tmp_path / "file3.md").write_text("# Markdown")
    (tmp_path / "file4.js").write_text("console.log('hi')")
    (tmp_path / "ignored.bin").write_text("binary data")

    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "nested.py").write_text("def foo(): pass")
    (subdir / "nested.txt").write_text("nested text")

    return tmp_path


async def _collect_files(walker: FileWalker, directory: Path) -> list[Path]:
    """Helper to collect all files from async walker."""
    return [path async for path in walker.walk(directory)]


class TestFileWalkerPatternMatching:
    """Tests for pattern matching behavior."""

    async def test_discovers_files_matching_patterns(self, tmp_directory_with_files: Path) -> None:
        walker = FileWalker(include_patterns=["*.py"])
        files = await _collect_files(walker, tmp_directory_with_files)

        assert len(files) == 2
        file_names = {f.name for f in files}
        assert file_names == {"file1.py", "nested.py"}

    async def test_uses_default_patterns(self, tmp_directory_with_files: Path) -> None:
        walker = FileWalker()
        files = await _collect_files(walker, tmp_directory_with_files)

        file_names = {f.name for f in files}
        assert "file1.py" in file_names
        assert "file2.txt" in file_names
        assert "file3.md" in file_names
        assert "file4.js" in file_names
        assert "ignored.bin" not in file_names

    async def test_excludes_matching_patterns(self, tmp_directory_with_files: Path) -> None:
        walker = FileWalker(
            include_patterns=["*.py", "*.txt"],
            exclude_patterns=["subdir/*"],
        )
        files = await _collect_files(walker, tmp_directory_with_files)

        file_names = {f.name for f in files}
        assert "file1.py" in file_names
        assert "file2.txt" in file_names
        assert "nested.py" not in file_names
        assert "nested.txt" not in file_names


class TestFileWalkerErrorHandling:
    """Tests for error handling."""

    async def test_raises_on_nonexistent_directory(self) -> None:
        walker = FileWalker()
        with pytest.raises(FileNotFoundError):
            await _collect_files(walker, Path("/nonexistent/path"))

    async def test_raises_on_file_instead_of_directory(self, tmp_path: Path) -> None:
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("content")

        walker = FileWalker()
        with pytest.raises(NotADirectoryError):
            await _collect_files(walker, file_path)


class TestFileWalkerEdgeCases:
    """Tests for edge cases."""

    async def test_handles_empty_directory(self, tmp_path: Path) -> None:
        walker = FileWalker()
        files = await _collect_files(walker, tmp_path)
        assert files == []

    async def test_yields_absolute_paths(self, tmp_directory_with_files: Path) -> None:
        walker = FileWalker(include_patterns=["*.py"])
        files = await _collect_files(walker, tmp_directory_with_files)

        for file_path in files:
            assert file_path.is_absolute()
