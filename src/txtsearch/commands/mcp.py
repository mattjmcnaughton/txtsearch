"""MCP command for starting the MCP server."""

from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict


class McpInput(BaseModel):
    """Input for the MCP command."""

    directory: Path

    model_config = ConfigDict(frozen=True)


class McpOutput(BaseModel):
    """Output from the MCP command (placeholder)."""

    message: str

    model_config = ConfigDict(frozen=True)


class McpCommand:
    """Command to start the MCP server."""

    def __init__(
        self,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._logger = logger or structlog.get_logger(__name__)

    async def run(self, input: McpInput) -> McpOutput:
        """Start the MCP server.

        Args:
            input: McpInput with directory.

        Returns:
            McpOutput with status message.

        Raises:
            IndexNotFoundError: If index does not exist.
        """
        index_dir = input.directory / ".txtsearch"

        if not index_dir.exists():
            from txtsearch.commands.search import IndexNotFoundError

            raise IndexNotFoundError(f"No index found at {index_dir}")

        self._logger.info(
            "mcp_command_started",
            directory=str(input.directory),
        )

        raise NotImplementedError("MCP server is not yet implemented")
