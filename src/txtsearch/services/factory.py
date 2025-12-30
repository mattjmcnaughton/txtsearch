"""Factory functions for creating and wiring services.

Provides production factories that create services with persistent storage
and test factories that use in-memory stores for fast, isolated testing.
"""

from pathlib import Path

import chromadb
import structlog

from txtsearch.services.chunker import Chunker
from txtsearch.services.file_walker import FileWalker
from txtsearch.services.index import IndexingService
from txtsearch.services.lexical_search import LexicalSearchService
from txtsearch.services.lexical_store import LexicalStore
from txtsearch.services.metadata_store import MetadataStore, create_async_engine_from_path
from txtsearch.services.semantic_search import SemanticSearchService
from txtsearch.services.vector_store import VectorStore

_TEST_COLLECTION_ID_LENGTH = 8

# Storage path constants
METADATA_DB_FILENAME = "meta.db"
VECTOR_STORE_DIRNAME = "semantic"
LEXICAL_DB_FILENAME = "lexical.duckdb"
DEFAULT_COLLECTION_NAME = "chunks"


def create_indexing_service(
    output_dir: Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    enable_lexical: bool = True,
) -> IndexingService:
    """Create a production IndexingService with persistent storage.

    Sets up SQLite for metadata, ChromaDB for vector storage, and optionally
    DuckDB for lexical search, all persisted to the specified output directory.

    Args:
        output_dir: Directory for storing index files (meta.db, semantic/, lexical.duckdb).
        include_patterns: File patterns to include (e.g., ["*.py", "*.md"]).
        exclude_patterns: File patterns to exclude.
        chunk_size: Target chunk size in characters.
        chunk_overlap: Characters of overlap between chunks.
        collection_name: ChromaDB collection name.
        enable_lexical: Whether to enable lexical search indexing.

    Returns:
        Configured IndexingService ready for use.
    """
    logger = structlog.get_logger(__name__)

    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = output_dir / METADATA_DB_FILENAME
    engine = create_async_engine_from_path(str(db_path))
    metadata_store = MetadataStore(engine=engine, logger=logger)

    chroma_path = output_dir / VECTOR_STORE_DIRNAME
    chroma_client = chromadb.PersistentClient(path=str(chroma_path))
    vector_store = VectorStore(
        client=chroma_client,
        collection_name=collection_name,
        logger=logger,
    )

    lexical_store = None
    if enable_lexical:
        lexical_db_path = output_dir / LEXICAL_DB_FILENAME
        lexical_store = LexicalStore(
            db_path=lexical_db_path,
            logger=logger,
        )

    file_walker = FileWalker(
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        logger=logger,
    )

    chunker = Chunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        logger=logger,
    )

    return IndexingService(
        file_walker=file_walker,
        metadata_store=metadata_store,
        vector_store=vector_store,
        chunker=chunker,
        lexical_store=lexical_store,
        logger=logger,
    )


def create_test_indexing_service(
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    collection_name: str | None = None,
    enable_lexical: bool = True,
) -> IndexingService:
    """Create an IndexingService with in-memory storage for testing.

    Uses in-memory SQLite, ephemeral ChromaDB, and in-memory DuckDB for
    fast, isolated tests. Each call creates independent storage.

    Args:
        include_patterns: File patterns to include.
        exclude_patterns: File patterns to exclude.
        chunk_size: Target chunk size in characters.
        chunk_overlap: Characters of overlap between chunks.
        collection_name: ChromaDB collection name. If None, generates unique name.
        enable_lexical: Whether to enable lexical search indexing.

    Returns:
        Configured IndexingService with in-memory storage.
    """
    from uuid import uuid4

    logger = structlog.get_logger(__name__)

    engine = create_async_engine_from_path(":memory:")
    metadata_store = MetadataStore(engine=engine, logger=logger)

    chroma_client = chromadb.EphemeralClient()
    effective_collection_name = collection_name or f"test_{uuid4().hex[:_TEST_COLLECTION_ID_LENGTH]}"
    vector_store = VectorStore(
        client=chroma_client,
        collection_name=effective_collection_name,
        logger=logger,
    )

    lexical_store = None
    if enable_lexical:
        lexical_store = LexicalStore(
            db_path=":memory:",
            logger=logger,
        )

    file_walker = FileWalker(
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        logger=logger,
    )

    chunker = Chunker(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        logger=logger,
    )

    return IndexingService(
        file_walker=file_walker,
        metadata_store=metadata_store,
        vector_store=vector_store,
        chunker=chunker,
        lexical_store=lexical_store,
        logger=logger,
    )


def parse_file_pattern(pattern: str) -> list[str]:
    """Parse brace-expansion patterns into individual glob patterns.

    Expands patterns like "*.{py,js,ts}" into ["*.py", "*.js", "*.ts"].
    Patterns without braces are returned as single-element lists.

    Args:
        pattern: Glob pattern, possibly with brace expansion.

    Returns:
        List of individual glob patterns.
    """
    if "{" not in pattern or "}" not in pattern:
        return [pattern]

    brace_start = pattern.index("{")
    brace_end = pattern.index("}")

    prefix = pattern[:brace_start]
    suffix = pattern[brace_end + 1 :]
    alternatives = pattern[brace_start + 1 : brace_end].split(",")

    return [f"{prefix}{alt.strip()}{suffix}" for alt in alternatives]


def create_semantic_search_service(
    index_dir: Path,
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> SemanticSearchService:
    """Create a production SemanticSearchService with persistent storage.

    Uses the same SQLite and ChromaDB storage as the indexing service,
    allowing search over previously indexed documents.

    Args:
        index_dir: Directory containing index files (meta.db, semantic/).
        collection_name: ChromaDB collection name.

    Returns:
        Configured SemanticSearchService ready for use.
    """
    logger = structlog.get_logger(__name__)

    db_path = index_dir / METADATA_DB_FILENAME
    engine = create_async_engine_from_path(str(db_path))
    metadata_store = MetadataStore(engine=engine, logger=logger)

    chroma_path = index_dir / VECTOR_STORE_DIRNAME
    chroma_client = chromadb.PersistentClient(path=str(chroma_path))
    vector_store = VectorStore(
        client=chroma_client,
        collection_name=collection_name,
        logger=logger,
    )

    return SemanticSearchService(
        vector_store=vector_store,
        metadata_store=metadata_store,
        logger=logger,
    )


def create_test_semantic_search_service(
    collection_name: str | None = None,
) -> SemanticSearchService:
    """Create a SemanticSearchService with in-memory storage for testing.

    Uses in-memory SQLite and ephemeral ChromaDB for fast, isolated tests.
    Each call creates independent storage, so tests don't interfere.

    Args:
        collection_name: ChromaDB collection name. If None, generates unique name.

    Returns:
        Configured SemanticSearchService with in-memory storage.
    """
    from uuid import uuid4

    logger = structlog.get_logger(__name__)

    engine = create_async_engine_from_path(":memory:")
    metadata_store = MetadataStore(engine=engine, logger=logger)

    chroma_client = chromadb.EphemeralClient()
    effective_collection_name = collection_name or f"test_{uuid4().hex[:_TEST_COLLECTION_ID_LENGTH]}"
    vector_store = VectorStore(
        client=chroma_client,
        collection_name=effective_collection_name,
        logger=logger,
    )

    return SemanticSearchService(
        vector_store=vector_store,
        metadata_store=metadata_store,
        logger=logger,
    )


def create_lexical_search_service(
    index_dir: Path,
) -> LexicalSearchService:
    """Create a production LexicalSearchService with persistent storage.

    Uses the same SQLite metadata store as indexing/semantic search, plus
    DuckDB for lexical FTS queries. Both must exist in the index directory.

    Args:
        index_dir: Directory containing index files (meta.db, lexical.duckdb).

    Returns:
        Configured LexicalSearchService ready for use.

    Raises:
        FileNotFoundError: If lexical.duckdb doesn't exist.
    """
    logger = structlog.get_logger(__name__)

    db_path = index_dir / METADATA_DB_FILENAME
    engine = create_async_engine_from_path(str(db_path))
    metadata_store = MetadataStore(engine=engine, logger=logger)

    lexical_db_path = index_dir / LEXICAL_DB_FILENAME
    lexical_store = LexicalStore(
        db_path=lexical_db_path,
        logger=logger,
    )

    return LexicalSearchService(
        lexical_store=lexical_store,
        metadata_store=metadata_store,
        logger=logger,
    )


def create_test_lexical_search_service() -> LexicalSearchService:
    """Create a LexicalSearchService with in-memory storage for testing.

    Uses in-memory SQLite and DuckDB for fast, isolated tests.
    Each call creates independent storage, so tests don't interfere.

    Returns:
        Configured LexicalSearchService with in-memory storage.
    """
    logger = structlog.get_logger(__name__)

    engine = create_async_engine_from_path(":memory:")
    metadata_store = MetadataStore(engine=engine, logger=logger)

    lexical_store = LexicalStore(
        db_path=":memory:",
        logger=logger,
    )

    return LexicalSearchService(
        lexical_store=lexical_store,
        metadata_store=metadata_store,
        logger=logger,
    )
