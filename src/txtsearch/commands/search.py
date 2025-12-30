"""Search command for searching indexed directories."""

from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict, Field

from txtsearch.models.enums import SearchStrategy
from txtsearch.models.hit import SearchHit
from txtsearch.models.query import Query
from txtsearch.services.factory import create_lexical_search_service, create_semantic_search_service


class SearchInput(BaseModel):
    """Input for the search command."""

    query: str
    directory: Path
    strategy: SearchStrategy = SearchStrategy.SEMANTIC
    limit: int = Field(default=10, gt=0)
    include_snippets: bool = True

    model_config = ConfigDict(frozen=True)


class SearchOutput(BaseModel):
    """Output from the search command."""

    query: str
    strategy: SearchStrategy
    hits: list[SearchHit]

    model_config = ConfigDict(frozen=True)

    @property
    def result_count(self) -> int:
        return len(self.hits)


class IndexNotFoundError(Exception):
    """Raised when the search index does not exist."""

    pass


class StrategyNotSupportedError(Exception):
    """Raised when a search strategy is not yet implemented."""

    pass


class SearchCommand:
    """Command to search indexed documents.

    Supports multiple search strategies (semantic, lexical) by routing to
    the appropriate search service. Services are instantiated on-demand
    based on the requested strategy.
    """

    def __init__(
        self,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._logger = logger or structlog.get_logger(__name__)

    async def run(self, input: SearchInput) -> SearchOutput:
        """Search for documents matching the query.

        Args:
            input: SearchInput with query and options.

        Returns:
            SearchOutput with search hits.

        Raises:
            IndexNotFoundError: If required index files don't exist.
            StrategyNotSupportedError: If strategy is not implemented.
        """
        self._logger.info(
            "search_command_started",
            query=input.query,
            strategy=input.strategy.value,
            directory=str(input.directory),
        )

        if input.strategy == SearchStrategy.SEMANTIC:
            search_service = create_semantic_search_service(index_dir=input.directory)
        elif input.strategy == SearchStrategy.LEXICAL:
            lexical_db = input.directory / "lexical.duckdb"
            if not lexical_db.exists():
                raise IndexNotFoundError(
                    f"Lexical index not found at {lexical_db}. "
                    "Run 'txtsearch index' to create the lexical search index."
                )
            search_service = create_lexical_search_service(index_dir=input.directory)
        else:
            raise StrategyNotSupportedError(
                f"Strategy '{input.strategy.value}' is not yet implemented. "
                "Use 'semantic' or 'lexical' strategy."
            )

        try:
            await search_service.initialize()

            query_obj = Query(
                text=input.query,
                strategy=input.strategy,
                top_k=input.limit,
                include_snippets=input.include_snippets,
            )

            hits = await search_service.search(query_obj)

            self._logger.info(
                "search_command_completed",
                result_count=len(hits),
            )

            return SearchOutput(
                query=input.query,
                strategy=input.strategy,
                hits=hits,
            )
        finally:
            await search_service.close()
