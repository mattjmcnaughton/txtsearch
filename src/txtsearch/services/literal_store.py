"""Literal store service for ripgrep-based pattern search.

Ripgrep is synchronous, so we use asyncio.to_thread() to wrap blocking
subprocess calls and maintain async consistency with other services.
"""

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog


@dataclass(frozen=True)
class LiteralQueryResult:
    """Result of a literal pattern search."""

    path: str
    line_number: int
    line_text: str
    submatches: list[tuple[int, int]]  # List of (start, end) offset pairs


class RipgrepNotFoundError(Exception):
    """Raised when the ripgrep binary is not found on the system."""

    def __init__(self, message: str | None = None) -> None:
        if message is None:
            message = "Ripgrep (rg) not found. Install it from https://github.com/BurntSushi/ripgrep"
        super().__init__(message)


class LiteralStore:
    """Searches files using ripgrep for exact pattern matching.

    Wraps ripgrep subprocess calls with async interface using asyncio.to_thread().
    """

    def __init__(
        self,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        """Initialize the literal store.

        Args:
            logger: Optional structured logger.
        """
        self._logger = logger or structlog.get_logger(__name__)

    async def check_available(self) -> bool:
        """Check if ripgrep binary is available on the system.

        Returns:
            True if ripgrep is installed and accessible, False otherwise.
        """
        return await asyncio.to_thread(self._sync_check_available)

    def _sync_check_available(self) -> bool:
        """Synchronous check for ripgrep availability."""
        return shutil.which("rg") is not None

    async def search(
        self,
        pattern: str,
        directory: Path,
        limit: int = 10,
    ) -> list[LiteralQueryResult]:
        """Search for pattern matches in the specified directory.

        Args:
            pattern: Search pattern (interpreted as regex by ripgrep).
            directory: Directory to search within.
            limit: Maximum number of results to return.

        Returns:
            List of LiteralQueryResult with file paths, line numbers, and text.

        Raises:
            RipgrepNotFoundError: If ripgrep is not installed.
            subprocess.CalledProcessError: If ripgrep encounters an error.
        """
        return await asyncio.to_thread(
            self._sync_search,
            pattern,
            directory,
            limit,
        )

    def _sync_search(
        self,
        pattern: str,
        directory: Path,
        limit: int,
    ) -> list[LiteralQueryResult]:
        """Synchronous ripgrep search."""
        if not self._sync_check_available():
            raise RipgrepNotFoundError()

        result = subprocess.run(
            [
                "rg",
                "--json",
                "--max-count",
                str(limit),
                pattern,
                str(directory),
            ],
            capture_output=True,
            text=True,
        )

        # Exit codes: 0 = matches found, 1 = no matches, 2+ = error
        if result.returncode == 1:
            self._logger.debug(
                "literal_search_no_matches",
                pattern_length=len(pattern),
            )
            return []
        elif result.returncode >= 2:
            self._logger.error(
                "ripgrep_error",
                returncode=result.returncode,
                stderr=result.stderr,
            )
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                result.stdout,
                result.stderr,
            )

        results = self._parse_json_output(result.stdout, limit)

        self._logger.debug(
            "literal_search_executed",
            pattern_length=len(pattern),
            directory=str(directory),
            result_count=len(results),
        )

        return results

    def _parse_json_output(
        self,
        stdout: str,
        limit: int,
    ) -> list[LiteralQueryResult]:
        """Parse ripgrep JSON Lines output into structured results."""
        results: list[LiteralQueryResult] = []

        for line in stdout.strip().split("\n"):
            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue

            if message.get("type") != "match":
                continue

            data = message.get("data", {})

            # Extract path (handles both "text" and "bytes" formats)
            path_data = data.get("path", {})
            path = path_data.get("text") or path_data.get("bytes", "")

            # Extract line text
            lines_data = data.get("lines", {})
            line_text = lines_data.get("text") or lines_data.get("bytes", "")
            line_text = line_text.rstrip("\n")

            # Extract line number
            line_number = data.get("line_number", 0)

            # Extract submatches
            submatches: list[tuple[int, int]] = []
            for submatch in data.get("submatches", []):
                start = submatch.get("start", 0)
                end = submatch.get("end", 0)
                submatches.append((start, end))

            results.append(
                LiteralQueryResult(
                    path=path,
                    line_number=line_number,
                    line_text=line_text,
                    submatches=submatches,
                )
            )

            if len(results) >= limit:
                break

        return results
