"""Serve command for starting the REST API server."""

from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict, Field


class ServeInput(BaseModel):
    """Input for the serve command."""

    directory: Path
    host: str = "127.0.0.1"
    port: int = Field(default=8000, gt=0, lt=65536)

    model_config = ConfigDict(frozen=True)


class ServeOutput(BaseModel):
    """Output from the serve command (placeholder)."""

    message: str

    model_config = ConfigDict(frozen=True)


class ServeCommand:
    """Command to start the REST API server."""

    def __init__(
        self,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._logger = logger or structlog.get_logger(__name__)

    async def run(self, input: ServeInput) -> ServeOutput:
        """Start the REST API server.

        Args:
            input: ServeInput with host, port, and directory.

        Returns:
            ServeOutput with status message.

        Raises:
            IndexNotFoundError: If index does not exist.
        """
        index_dir = input.directory / ".txtsearch"

        if not index_dir.exists():
            from txtsearch.commands.search import IndexNotFoundError

            raise IndexNotFoundError(f"No index found at {index_dir}")

        self._logger.info(
            "serve_command_started",
            host=input.host,
            port=input.port,
            directory=str(input.directory),
        )

        raise NotImplementedError("REST API server is not yet implemented")
