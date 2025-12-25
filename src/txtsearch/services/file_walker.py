"""File walker service for discovering files in directories."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import structlog


class FileWalker:
    """Walks directories to discover files matching specified patterns.

    Supports include and exclude patterns using glob syntax.
    Uses asyncio.to_thread to avoid blocking the event loop during I/O.
    """

    def __init__(
        self,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._include_patterns = include_patterns or [
            "*.py",
            "*.js",
            "*.ts",
            "*.md",
            "*.txt",
            "*.json",
            "*.yaml",
            "*.yml",
        ]
        self._exclude_patterns = exclude_patterns or []
        self._logger = logger or structlog.get_logger(__name__)

    async def walk(self, directory: Path) -> AsyncIterator[Path]:
        """Walk directory and yield files matching include patterns.

        Args:
            directory: Root directory to walk.

        Yields:
            Path objects for matching files.

        Raises:
            FileNotFoundError: If directory does not exist.
            NotADirectoryError: If path is not a directory.
        """
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {directory}")

        self._logger.info(
            "directory_walk_started",
            directory=str(directory),
            include_patterns=self._include_patterns,
            exclude_patterns=self._exclude_patterns,
        )

        file_count = 0
        async for file_path in self._discover_files(directory):
            file_count += 1
            yield file_path

        self._logger.info(
            "directory_walk_completed",
            directory=str(directory),
            file_count=file_count,
        )

    async def _discover_files(self, directory: Path) -> AsyncIterator[Path]:
        """Discover files matching include patterns, excluding matches."""
        for pattern in self._include_patterns:
            files = await asyncio.to_thread(self._glob_pattern, directory, pattern)
            for file_path in files:
                yield file_path

    def _glob_pattern(self, directory: Path, pattern: str) -> list[Path]:
        """Synchronously glob a pattern and filter results."""
        return [
            file_path
            for file_path in directory.rglob(pattern)
            if file_path.is_file() and not self._is_excluded(file_path, directory)
        ]

    def _is_excluded(self, file_path: Path, root: Path) -> bool:
        """Check if file matches any exclude pattern."""
        if not self._exclude_patterns:
            return False

        relative_path = file_path.relative_to(root)
        for pattern in self._exclude_patterns:
            if relative_path.match(pattern):
                return True
        return False
