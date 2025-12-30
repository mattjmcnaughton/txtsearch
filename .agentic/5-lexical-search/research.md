# Research: DuckDB Lexical Full-Text Search

## DuckDB Full-Text Search Overview

DuckDB provides a dedicated FTS extension that uses BM25 ranking (a probabilistic relevance framework commonly used in information retrieval).

### Installation & Setup

```python
import duckdb

# Connect to database (file-based or in-memory)
conn = duckdb.connect('lexical.duckdb')  # or ':memory:' for ephemeral

# Install and load the FTS extension
conn.execute("INSTALL fts")
conn.execute("LOAD fts")
```

### Creating FTS Tables

DuckDB FTS uses a special pragma to create full-text search indexes:

```sql
-- Method 1: Create FTS index on existing table
CREATE TABLE documents(
    document_id VARCHAR PRIMARY KEY,
    chunk_id VARCHAR,
    chunk_index INTEGER,
    file_path VARCHAR,
    content TEXT,
    extra JSON
);

-- Create FTS index with BM25 ranking
PRAGMA create_fts_index(
    'documents',           -- table name
    'document_id',         -- document id column
    'content',            -- text column(s) to index
    stemmer='porter',     -- optional: stemming algorithm
    stopwords='english',  -- optional: language for stopwords
    ignore='(\\.|[^a-z])+',  -- optional: regex for tokens to ignore
    strip_accents=1,      -- optional: normalize accented characters
    lower=1,              -- optional: lowercase normalization
    overwrite=1           -- optional: recreate if exists
);
```

### Querying with Ranking

DuckDB FTS provides the `fts_main_documents.match_bm25()` function for ranked search:

```sql
-- Basic ranked search
SELECT
    document_id,
    chunk_id,
    content,
    fts_main_documents.match_bm25(
        document_id,
        'search query terms'
    ) AS score
FROM documents
WHERE score IS NOT NULL
ORDER BY score DESC
LIMIT 10;

-- Advanced: with filters and conjunctions
SELECT
    d.document_id,
    d.chunk_id,
    d.chunk_index,
    d.file_path,
    d.content,
    fts_main_documents.match_bm25(
        d.document_id,
        'search terms',
        fields := 'content',
        conjunctive := 0  -- 0 = OR, 1 = AND
    ) AS score
FROM documents d
WHERE score IS NOT NULL
  AND d.file_path LIKE '%.py'  -- Additional filters
ORDER BY score DESC
LIMIT 20;
```

### BM25 Scoring

BM25 (Best Matching 25) is the default scoring algorithm. Key characteristics:
- Returns higher scores for better matches (unlike semantic search distance)
- Considers term frequency (TF) and inverse document frequency (IDF)
- Accounts for document length normalization
- Scores are unbounded (not 0-1 range), so normalization may be needed

**Score normalization options:**
```sql
-- Option 1: Min-max normalization (for 0-1 range)
WITH raw_scores AS (
    SELECT *, fts_main_documents.match_bm25(document_id, 'query') AS raw_score
    FROM documents
    WHERE raw_score IS NOT NULL
)
SELECT
    *,
    (raw_score - MIN(raw_score) OVER ()) /
    NULLIF(MAX(raw_score) OVER () - MIN(raw_score) OVER (), 0) AS normalized_score
FROM raw_scores
ORDER BY raw_score DESC;

-- Option 2: Sigmoid normalization (smoother, 0-1 range)
SELECT
    *,
    1.0 / (1.0 + EXP(-raw_score / 10.0)) AS normalized_score
FROM (
    SELECT *, fts_main_documents.match_bm25(document_id, 'query') AS raw_score
    FROM documents
    WHERE raw_score IS NOT NULL
)
ORDER BY raw_score DESC;
```

## Recommended Architecture for txtsearch

Based on the existing `SemanticSearchService` pattern and the repository guidelines:

### 1. Data Model (similar to semantic search)

```python
# In models/tables.py (SQLModel table for DuckDB)
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
from datetime import datetime, timezone

class DocumentChunkTable(SQLModel, table=True):
    """DuckDB table for lexical FTS."""
    __tablename__ = "document_chunks"

    # Primary identifiers
    document_id: str = Field(primary_key=True)
    chunk_id: str = Field(index=True)
    chunk_index: int = Field(ge=0)

    # Content for FTS
    content: str = Field(index=False)

    # Metadata for hydration
    file_path: str
    source_type: str
    ingested_at: datetime

    # Flexible storage for additional metadata
    extra: dict = Field(default_factory=dict, sa_type=JSON)
```

### 2. DuckDB Store Service

```python
# In services/lexical_store.py
from pathlib import Path
import duckdb
from typing import AsyncIterator
import asyncio
import structlog

class LexicalStore:
    """Manages DuckDB FTS index for lexical search."""

    def __init__(
        self,
        db_path: Path | str,
        logger: structlog.stdlib.BoundLogger | None = None
    ):
        self._db_path = str(db_path) if db_path != ":memory:" else ":memory:"
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._logger = logger or structlog.get_logger(__name__)

    async def __aenter__(self) -> "LexicalStore":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def initialize(self) -> None:
        """Initialize connection and FTS extension."""
        # DuckDB is synchronous, wrap in thread
        self._conn = await asyncio.to_thread(duckdb.connect, self._db_path)

        # Load FTS extension
        await asyncio.to_thread(self._conn.execute, "INSTALL fts")
        await asyncio.to_thread(self._conn.execute, "LOAD fts")

        # Create schema
        await self._create_schema()

        self._logger.info("lexical_store_initialized", db_path=self._db_path)

    async def _create_schema(self) -> None:
        """Create tables and FTS index."""
        schema_sql = """
        CREATE TABLE IF NOT EXISTS document_chunks(
            document_id VARCHAR PRIMARY KEY,
            chunk_id VARCHAR NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            file_path VARCHAR NOT NULL,
            source_type VARCHAR NOT NULL,
            ingested_at TIMESTAMP NOT NULL,
            extra JSON
        );
        """
        await asyncio.to_thread(self._conn.execute, schema_sql)

        # Create FTS index
        fts_sql = """
        PRAGMA create_fts_index(
            'document_chunks',
            'document_id',
            'content',
            stemmer='porter',
            stopwords='english',
            lower=1,
            overwrite=1
        );
        """
        await asyncio.to_thread(self._conn.execute, fts_sql)

    async def index_chunks(
        self,
        chunks: list[dict]
    ) -> int:
        """Bulk insert chunks for indexing."""
        if not chunks:
            return 0

        # Use prepared statement for efficiency
        insert_sql = """
        INSERT OR REPLACE INTO document_chunks
        (document_id, chunk_id, chunk_index, content, file_path, source_type, ingested_at, extra)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """

        rows = [
            (
                chunk["document_id"],
                chunk["chunk_id"],
                chunk["chunk_index"],
                chunk["content"],
                chunk["file_path"],
                chunk["source_type"],
                chunk["ingested_at"],
                chunk.get("extra", {})
            )
            for chunk in chunks
        ]

        await asyncio.to_thread(self._conn.executemany, insert_sql, rows)

        self._logger.info("chunks_indexed", count=len(chunks))
        return len(chunks)

    async def search(
        self,
        query_text: str,
        top_k: int = 10,
        filters: dict | None = None
    ) -> list[dict]:
        """Execute BM25-ranked full-text search."""
        # Build filter clause
        where_clauses = ["score IS NOT NULL"]
        params = {"query": query_text, "limit": top_k}

        if filters:
            if "document_ids" in filters:
                placeholders = ",".join(f"${i+3}" for i in range(len(filters["document_ids"])))
                where_clauses.append(f"document_id IN ({placeholders})")
                for i, doc_id in enumerate(filters["document_ids"]):
                    params[f"param_{i+3}"] = doc_id

        where_clause = " AND ".join(where_clauses)

        search_sql = f"""
        SELECT
            document_id,
            chunk_id,
            chunk_index,
            content,
            file_path,
            source_type,
            ingested_at,
            extra,
            fts_main_document_chunks.match_bm25(document_id, $query) AS score
        FROM document_chunks
        WHERE {where_clause}
        ORDER BY score DESC
        LIMIT $limit
        """

        result = await asyncio.to_thread(
            self._conn.execute(search_sql, params).fetchall
        )

        # Convert to dict format
        columns = ["document_id", "chunk_id", "chunk_index", "content",
                   "file_path", "source_type", "ingested_at", "extra", "score"]

        return [dict(zip(columns, row)) for row in result]

    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._logger.info("lexical_store_closed")
```

### 3. Lexical Search Service (parallel to SemanticSearchService)

```python
# In services/lexical_search.py
from uuid import uuid4
import structlog

from txtsearch.models.enums import SearchStrategy
from txtsearch.models.hit import SearchHit
from txtsearch.models.query import Query
from txtsearch.services.lexical_store import LexicalStore
from txtsearch.services.metadata_store import MetadataStore

class LexicalSearchService:
    """Performs BM25-ranked lexical search over indexed documents."""

    def __init__(
        self,
        lexical_store: LexicalStore,
        metadata_store: MetadataStore,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._lexical_store = lexical_store
        self._metadata_store = metadata_store
        self._logger = logger or structlog.get_logger(__name__)

    async def close(self) -> None:
        """Close all resources."""
        await self._lexical_store.close()
        await self._metadata_store.close()

    async def __aenter__(self) -> "LexicalSearchService":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def initialize(self) -> None:
        """Initialize underlying stores."""
        await self._lexical_store.initialize()
        await self._metadata_store.initialize_schema()
        self._logger.info("lexical_search_service_initialized")

    async def search(self, query: Query) -> list[SearchHit]:
        """Search using BM25 lexical matching.

        Args:
            query: Query object with search text and filters.

        Returns:
            List of SearchHit objects ranked by BM25 score.
        """
        if not query.text or not query.text.strip():
            raise ValueError("Query text cannot be empty")

        self._logger.info(
            "lexical_search_started",
            query_id=query.query_id,
            text_length=len(query.text),
            top_k=query.top_k,
        )

        # Build filters
        filters = {}
        if query.filters.document_ids:
            filters["document_ids"] = query.filters.document_ids

        # Execute DuckDB FTS query
        results = await self._lexical_store.search(
            query_text=query.text,
            top_k=query.top_k,
            filters=filters
        )

        if not results:
            self._logger.info("lexical_search_completed", query_id=query.query_id, hit_count=0)
            return []

        # Convert to SearchHit objects
        hits = await self._hydrate_results(query, results)

        # Apply post-filters (source_types, ingested_after)
        hits = await self._apply_post_filters(query, hits)

        # Re-rank after filtering
        hits = self._rerank(hits)

        self._logger.info(
            "lexical_search_completed",
            query_id=query.query_id,
            hit_count=len(hits)
        )

        return hits

    async def _hydrate_results(
        self,
        query: Query,
        results: list[dict]
    ) -> list[SearchHit]:
        """Convert DuckDB results to SearchHit objects."""
        # Normalize BM25 scores to 0-1 range using min-max
        scores = [r["score"] for r in results]
        min_score = min(scores)
        max_score = max(scores)
        score_range = max_score - min_score if max_score > min_score else 1.0

        hits: list[SearchHit] = []
        for i, result in enumerate(results):
            # Normalize score to 0-1
            raw_score = result["score"]
            normalized_score = (raw_score - min_score) / score_range

            snippet = None
            if query.include_snippets:
                snippet = result["content"]

            hit = SearchHit(
                hit_id=str(uuid4()),
                query_id=query.query_id,
                document_id=result["document_id"],
                chunk_id=result["chunk_id"],
                rank=i,
                score=normalized_score,
                strategy=SearchStrategy.LEXICAL,
                snippet=snippet,
                extra={
                    "bm25_score": raw_score,
                    "chunk_index": result["chunk_index"],
                },
            )
            hits.append(hit)

        return hits

    async def _apply_post_filters(
        self,
        query: Query,
        hits: list[SearchHit],
    ) -> list[SearchHit]:
        """Filter by metadata that requires document lookup."""
        if not query.filters.source_types and not query.filters.ingested_after:
            return hits

        # Bulk fetch documents (avoid N+1)
        unique_doc_ids = list({hit.document_id for hit in hits})
        documents = await self._metadata_store.get_documents_by_ids(unique_doc_ids)
        docs_by_id = {doc.document_id: doc for doc in documents}

        filtered_hits: list[SearchHit] = []
        for hit in hits:
            document = docs_by_id.get(hit.document_id)
            if document is None:
                continue

            if query.filters.source_types:
                if document.source_type not in query.filters.source_types:
                    continue

            if query.filters.ingested_after:
                if document.ingested_at < query.filters.ingested_after:
                    continue

            filtered_hits.append(hit)

        return filtered_hits

    def _rerank(self, hits: list[SearchHit]) -> list[SearchHit]:
        """Re-assign sequential ranks after filtering."""
        return [
            SearchHit(
                hit_id=hit.hit_id,
                query_id=hit.query_id,
                document_id=hit.document_id,
                chunk_id=hit.chunk_id,
                rank=i,
                score=hit.score,
                strategy=hit.strategy,
                snippet=hit.snippet,
                highlights=hit.highlights,
                extra=hit.extra,
            )
            for i, hit in enumerate(hits)
        ]
```

## Key Best Practices

1. **Async Wrapper Pattern**: DuckDB is synchronous, so wrap all operations in `asyncio.to_thread()` per the CLAUDE.md guidelines.

2. **Resource Management**: Implement async context managers (`__aenter__`/`__aexit__`) and always call `conn.close()` to avoid hanging processes.

3. **Score Normalization**: BM25 returns unbounded scores. Normalize to 0-1 range for consistency with `SearchHit.score` validation (must be between 0 and 1).

4. **Bulk Operations**: Use `executemany()` for indexing and bulk document fetches to avoid N+1 queries.

5. **Structured Logging**: Follow the existing pattern with structlog, using snake_case event names and contextual information.

6. **Shared Models**: Reuse `SearchHit`, `Query`, `QueryFilters` - the lexical service should return the same shape as semantic search.

7. **Error Handling**: When DuckDB artifacts are missing, raise clear errors that guide users to run indexing first.

8. **Testing**: Create unit tests with in-memory DuckDB (`:memory:`) for fast, deterministic tests without external dependencies.

## Next Steps for Implementation

Following the ticket description and existing patterns:

1. **Extend IndexingService** (`services/index.py`):
   - Add DuckDB store instantiation
   - Populate FTS tables during indexing alongside ChromaDB
   - Store in `~/.txtsearch/<dataset-id>/lexical.duckdb`

2. **Create LexicalSearchService** (`services/lexical_search.py`):
   - Implement the service shown above
   - Mirror the semantic search API surface

3. **Wire Strategy Selection**:
   - Update search commands to route `--strategy lexical` to the new service
   - Add factory pattern in `services/factory.py` for DI

4. **CLI Integration**:
   - Ensure `txtsearch search --strategy lexical "query"` works end-to-end
   - Handle missing DuckDB index with actionable error messages

5. **Testing**:
   - Unit tests with in-memory DuckDB
   - Integration tests with real file indexing
   - Verify score normalization and ranking consistency

## Additional Resources

The DuckDB FTS extension documentation covers:
- Advanced stemming and stopword configurations
- Multi-field search (searching across multiple columns)
- Phrase queries and boolean operators
- Performance tuning for large datasets

For this project, the basic setup shown above should handle the MVP requirements effectively while maintaining consistency with the semantic search implementation.
