"""Factory functions for creating and wiring indexing services.

Provides production factories that create services with persistent storage
and test factories that use in-memory stores for fast, isolated testing.
"""

from pathlib import Path

import chromadb
import structlog

from txtsearch.services.chunker import Chunker
from txtsearch.services.file_walker import FileWalker
from txtsearch.services.index import IndexingService
from txtsearch.services.metadata_store import MetadataStore, create_async_engine_from_path
from txtsearch.services.vector_store import VectorStore

_TEST_COLLECTION_ID_LENGTH = 8


def create_indexing_service(
    output_dir: Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    collection_name: str = "chunks",
) -> IndexingService:
    """Create a production IndexingService with persistent storage.

    Sets up SQLite for metadata and ChromaDB for vector storage, both
    persisted to the specified output directory.

    Args:
        output_dir: Directory for storing index files (meta.db, semantic/).
        include_patterns: File patterns to include (e.g., ["*.py", "*.md"]).
        exclude_patterns: File patterns to exclude.
        chunk_size: Target chunk size in characters.
        chunk_overlap: Characters of overlap between chunks.
        collection_name: ChromaDB collection name.

    Returns:
        Configured IndexingService ready for use.
    """
    logger = structlog.get_logger(__name__)

    output_dir.mkdir(parents=True, exist_ok=True)

    db_path = output_dir / "meta.db"
    engine = create_async_engine_from_path(str(db_path))
    metadata_store = MetadataStore(engine=engine, logger=logger)

    chroma_path = output_dir / "semantic"
    chroma_client = chromadb.PersistentClient(path=str(chroma_path))
    vector_store = VectorStore(
        client=chroma_client,
        collection_name=collection_name,
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
        logger=logger,
    )


def create_test_indexing_service(
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    collection_name: str | None = None,
) -> IndexingService:
    """Create an IndexingService with in-memory storage for testing.

    Uses in-memory SQLite and ephemeral ChromaDB for fast, isolated tests.
    Each call creates independent storage, so tests don't interfere.

    Args:
        include_patterns: File patterns to include.
        exclude_patterns: File patterns to exclude.
        chunk_size: Target chunk size in characters.
        chunk_overlap: Characters of overlap between chunks.
        collection_name: ChromaDB collection name. If None, generates unique name.

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
