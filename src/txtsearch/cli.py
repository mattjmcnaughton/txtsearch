"""Text search and indexing CLI.

Provides indexing and search commands for directories with semantic search,
llm.txt style search, and grep-based search capabilities.
"""

import asyncio
import sys
from enum import Enum
from pathlib import Path
from typing import Optional

import structlog
import typer

from txtsearch.services.factory import create_indexing_service, parse_file_pattern
from txtsearch.services.index import IndexingResult


class SearchStrategy(str, Enum):
    """Available search strategies."""

    LITERAL = "literal"
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    AGENTIC = "agentic"


structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    logger_factory=lambda name: structlog.PrintLogger(file=sys.stderr),
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

app = typer.Typer(
    name="txtsearch",
    help="""Index directories and search with multiple strategies (literal, lexical, semantic, agentic).

Examples:

  # Index a directory
  uv run txtsearch index ./src/

  # Search with a specific strategy
  uv run txtsearch search --strategy semantic "function that handles authentication"

  # Start REST API server
  uv run txtsearch serve --port 8000

  # Start MCP server
  uv run txtsearch mcp""",
    rich_markup_mode="markdown",
)


@app.command()
def index(
    directory: str = typer.Argument(
        ...,
        help="Directory to index for search",
    ),
    output_dir: Optional[str] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Directory to store index files (default: .txtsearch in target directory)",
    ),
    file_pattern: Optional[str] = typer.Option(
        "*.{py,js,ts,md,txt,json,yaml,yml}",
        "--file-pattern",
        "-f",
        help="File patterns to include in index",
    ),
    exclude: Optional[str] = typer.Option(
        None,
        "--exclude",
        "-e",
        help="Patterns to exclude from indexing",
    ),
) -> None:
    """Index a directory for search capabilities."""
    target_dir = Path(directory)

    if not target_dir.exists():
        logger.error("directory_not_found", directory=str(target_dir))
        raise typer.Exit(1)

    index_dir = Path(output_dir) if output_dir else target_dir / ".txtsearch"

    include_patterns = parse_file_pattern(file_pattern) if file_pattern else None
    exclude_patterns = parse_file_pattern(exclude) if exclude else None

    async def run_indexing() -> IndexingResult:
        async with create_indexing_service(
            output_dir=index_dir,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        ) as service:
            return await service.index_directory(target_dir)

    result = asyncio.run(run_indexing())

    if result.errors:
        for error in result.errors:
            logger.warning("indexing_error", error=error)

    typer.echo(
        f"Indexed {result.files_processed} files ({result.chunks_created} chunks, {result.files_skipped} skipped)"
    )
    if result.errors:
        typer.echo(f"Encountered {len(result.errors)} errors")


@app.command()
def search(
    query: str = typer.Argument(
        ...,
        help="Search query",
    ),
    directory: Optional[str] = typer.Option(
        None,
        "--directory",
        "-d",
        help="Directory with index to search (default: current directory)",
    ),
    strategy: SearchStrategy = typer.Option(
        SearchStrategy.SEMANTIC,
        "--strategy",
        "-s",
        help="Search strategy to use",
    ),
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        help="Maximum number of results to return",
    ),
    context: int = typer.Option(
        0,
        "--context",
        "-C",
        help="Show N lines of context around matches",
    ),
) -> None:
    """Search indexed directory using various search methods."""
    search_dir = Path(directory) if directory else Path.cwd()
    index_dir = search_dir / ".txtsearch"

    if not index_dir.exists():
        logger.error("index_not_found", index_dir=str(index_dir))
        typer.echo("No index found. Run 'txtsearch index' first.")
        raise typer.Exit(1)

    logger.info(
        "starting_search",
        query=query,
        strategy=strategy.value,
        directory=str(search_dir),
        limit=limit,
    )

    # TODO: Implement search functionality
    typer.echo(f"Searching for '{query}' using {strategy.value} strategy")
    typer.echo("Search functionality will be implemented here.")


@app.command()
def serve(
    directory: Optional[str] = typer.Option(
        None,
        "--directory",
        "-d",
        help="Directory with index to serve (default: current directory)",
    ),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="Port to serve on",
    ),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        "-h",
        help="Host to serve on",
    ),
) -> None:
    """Start REST API server for search functionality."""
    search_dir = Path(directory) if directory else Path.cwd()
    index_dir = search_dir / ".txtsearch"

    if not index_dir.exists():
        logger.error("index_not_found", index_dir=str(index_dir))
        typer.echo("No index found. Run 'txtsearch index' first.")
        raise typer.Exit(1)

    logger.info("starting_api_server", host=host, port=port, directory=str(search_dir))

    # TODO: Implement FastAPI server
    typer.echo(f"Starting API server on {host}:{port}")
    typer.echo("REST API functionality will be implemented here.")


@app.command()
def mcp(
    directory: Optional[str] = typer.Option(
        None,
        "--directory",
        "-d",
        help="Directory with index to serve (default: current directory)",
    ),
) -> None:
    """Start MCP server for search functionality."""
    search_dir = Path(directory) if directory else Path.cwd()
    index_dir = search_dir / ".txtsearch"

    if not index_dir.exists():
        logger.error("index_not_found", index_dir=str(index_dir))
        typer.echo("No index found. Run 'txtsearch index' first.")
        raise typer.Exit(1)

    logger.info("starting_mcp_server", directory=str(search_dir))

    # TODO: Implement MCP server
    typer.echo("Starting MCP server")
    typer.echo("MCP functionality will be implemented here.")


@app.command()
def version() -> None:
    """Show version information."""
    from txtsearch import __version__

    typer.echo(f"txtsearch {__version__}")
