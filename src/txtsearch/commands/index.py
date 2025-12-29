"""Index command for indexing directories."""

from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict

from txtsearch.services.index import IndexingResult, IndexingService


class IndexInput(BaseModel):
    """Input for the index command."""

    directory: Path
    output_dir: Path | None = None
    include_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None

    model_config = ConfigDict(frozen=True)


class IndexOutput(BaseModel):
    """Output from the index command."""

    result: IndexingResult
    index_dir: Path

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class IndexCommand:
    """Command to index a directory for search."""

    def __init__(
        self,
        indexing_service: IndexingService,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._indexing_service = indexing_service
        self._logger = logger or structlog.get_logger(__name__)

    async def run(self, input: IndexInput) -> IndexOutput:
        """Index the specified directory.

        Args:
            input: IndexInput with directory and options.

        Returns:
            IndexOutput with indexing results.

        Raises:
            FileNotFoundError: If directory does not exist.
            NotADirectoryError: If path is not a directory.
        """
        if not input.directory.exists():
            raise FileNotFoundError(f"Directory not found: {input.directory}")

        if not input.directory.is_dir():
            raise NotADirectoryError(f"Not a directory: {input.directory}")

        index_dir = input.output_dir or (input.directory / ".txtsearch")

        self._logger.info(
            "index_command_started",
            directory=str(input.directory),
            index_dir=str(index_dir),
        )

        result = await self._indexing_service.index_directory(input.directory)

        self._logger.info(
            "index_command_completed",
            files_processed=result.files_processed,
            chunks_created=result.chunks_created,
        )

        return IndexOutput(result=result, index_dir=index_dir)
