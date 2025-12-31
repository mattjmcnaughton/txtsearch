"""Text search and indexing CLI.

Thin Typer wrapper that delegates to Command classes.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import structlog
import typer

from txtsearch.commands.index import IndexCommand, IndexInput, IndexOutput
from txtsearch.commands.mcp import McpCommand, McpInput
from txtsearch.commands.search import (
    IndexNotFoundError,
    SearchCommand,
    SearchInput,
    SearchOutput,
    StrategyNotSupportedError,
)
from txtsearch.commands.serve import ServeCommand, ServeInput
from txtsearch.models.enums import SearchStrategy
from txtsearch.services.factory import (
    create_indexing_service,
    create_lexical_search_service,
    create_semantic_search_service,
    parse_file_pattern,
)
from txtsearch.services.lexical_search import LexicalIndexNotFoundError


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


async def _run_index_command(
    input: IndexInput,
    output_dir: Path,
    include_patterns: list[str] | None,
    exclude_patterns: list[str] | None,
) -> IndexOutput:
    """Execute the index command with the given input."""
    async with create_indexing_service(
        output_dir=output_dir,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    ) as service:
        command = IndexCommand(indexing_service=service)
        return await command.run(input)


async def _run_search_command(
    input: SearchInput,
    index_dir: Path,
) -> SearchOutput:
    """Execute the search command with the given input."""
    if input.strategy == SearchStrategy.LEXICAL:
        async with create_lexical_search_service(index_dir=index_dir) as service:
            command = SearchCommand(search_service=service)
            return await command.run(input)
    else:
        async with create_semantic_search_service(index_dir=index_dir) as service:
            command = SearchCommand(search_service=service)
            return await command.run(input)


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
    index_dir = Path(output_dir) if output_dir else target_dir / ".txtsearch"

    include_patterns = parse_file_pattern(file_pattern) if file_pattern else None
    exclude_patterns = parse_file_pattern(exclude) if exclude else None

    input_dto = IndexInput(
        directory=target_dir,
        output_dir=index_dir,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    )

    try:
        output = asyncio.run(_run_index_command(input_dto, index_dir, include_patterns, exclude_patterns))
    except FileNotFoundError:
        logger.error("directory_not_found", directory=str(target_dir))
        raise typer.Exit(1)

    result = output.result
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
        help="Search strategy to use (semantic, literal, lexical, agentic)",
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
    output_json: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output results as JSON",
    ),
) -> None:
    """Search indexed directory using various search methods."""
    search_dir = Path(directory) if directory else Path.cwd()
    index_dir = search_dir / ".txtsearch"

    if not index_dir.exists():
        logger.error("index_not_found", index_dir=str(index_dir))
        typer.echo("No index found. Run 'txtsearch index' first.", err=True)
        raise typer.Exit(1)

    input_dto = SearchInput(
        query=query,
        directory=search_dir,
        strategy=strategy,
        limit=limit,
        include_snippets=True,
    )

    try:
        output = asyncio.run(_run_search_command(input_dto, index_dir))
    except IndexNotFoundError:
        # This shouldn't happen since we check above, but handle it gracefully
        logger.error("index_not_found", index_dir=str(index_dir))
        typer.echo("No index found. Run 'txtsearch index' first.", err=True)
        raise typer.Exit(1)
    except LexicalIndexNotFoundError as e:
        logger.error("lexical_index_not_found", index_dir=str(index_dir))
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    except StrategyNotSupportedError as e:
        logger.error("strategy_not_implemented", strategy=strategy)
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    except ValueError as e:
        logger.error("invalid_query", error=str(e))
        typer.echo(f"Invalid query: {e}", err=True)
        raise typer.Exit(1)

    if output_json:
        _output_json_results(output)
    else:
        _output_human_results(output)


def _output_json_results(output: SearchOutput) -> None:
    """Output search results as JSON."""
    data = {
        "query": output.query,
        "strategy": output.strategy.value,
        "result_count": output.result_count,
        "results": [hit.model_dump(mode="json") for hit in output.hits],
    }
    typer.echo(json.dumps(data, indent=2))


def _output_human_results(output: SearchOutput) -> None:
    """Output search results in human-readable format."""
    if not output.hits:
        typer.echo(f"No results found for '{output.query}'")
        return

    typer.echo(f"Found {output.result_count} result(s) for '{output.query}' using {output.strategy.value} strategy:\n")

    for hit in output.hits:
        score_str = f"{hit.score:.1%}" if hit.score is not None else "N/A"
        typer.echo(f"[{hit.rank + 1}] Score: {score_str}")

        doc_uri = hit.extra.get("uri", hit.document_id)
        typer.echo(f"    File: {doc_uri}")

        if hit.snippet:
            snippet_preview = hit.snippet[:200].replace("\n", " ")
            if len(hit.snippet) > 200:
                snippet_preview += "..."
            typer.echo(f"    Snippet: {snippet_preview}")

        typer.echo("")


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

    input_dto = ServeInput(
        directory=search_dir,
        host=host,
        port=port,
    )

    async def run() -> None:
        command = ServeCommand()
        output = await command.run(input_dto)
        typer.echo(f"Starting API server on {host}:{port}")
        typer.echo(output.message)

    try:
        asyncio.run(run())
    except NotImplementedError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    except IndexNotFoundError:
        logger.error("index_not_found", index_dir=str(search_dir / ".txtsearch"))
        typer.echo("No index found. Run 'txtsearch index' first.")
        raise typer.Exit(1)


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

    input_dto = McpInput(directory=search_dir)

    async def run() -> None:
        command = McpCommand()
        output = await command.run(input_dto)
        typer.echo("Starting MCP server")
        typer.echo(output.message)

    try:
        asyncio.run(run())
    except NotImplementedError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    except IndexNotFoundError:
        logger.error("index_not_found", index_dir=str(search_dir / ".txtsearch"))
        typer.echo("No index found. Run 'txtsearch index' first.")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    from txtsearch import __version__

    typer.echo(f"txtsearch {__version__}")
