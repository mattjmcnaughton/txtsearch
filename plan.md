# Plan: Add Lexical Strategy with DuckDB

## Implementation Steps

### Step 1: Create DuckDB Table Models
- Add `DocumentChunkTable` SQLModel class in `src/txtsearch/models/tables.py` for DuckDB schema
- Define fields: `document_id` (primary key), `chunk_id`, `chunk_index`, `content`, `file_path`, `source_type`, `ingested_at`, `extra` (JSON)
- Follow existing patterns: use `table=True`, separate from immutable domain models, use `sa_type=JSON` for dict fields
- **Deliverable**: Table definition ready for DuckDB FTS indexing

### Step 2: Implement LexicalStore Service
- Create `src/txtsearch/services/lexical_store.py` with async DuckDB wrapper
- Implement async context manager with `__aenter__`/`__aexit__` for resource cleanup
- Wrap all DuckDB operations in `asyncio.to_thread()` since DuckDB is synchronous
- Implement `initialize()`: connect to DuckDB, install/load FTS extension, create schema, create FTS index with BM25
- Use `PRAGMA create_fts_index()` with stemmer='porter', stopwords='english', lower=1
- Implement `index_chunks()`: bulk insert chunks using executemany for efficiency
- Implement `search()`: execute BM25-ranked queries with `match_bm25()`, support filters, return raw scores
- Implement `close()`: properly close connection to avoid process hanging
- Use structlog for all operations with snake_case event names
- **Deliverable**: Fully async DuckDB store service following codebase patterns from `src/txtsearch/services/vector_store.py` and `src/txtsearch/services/metadata_store.py`

### Step 3: Implement LexicalSearchService
- Create `src/txtsearch/services/lexical_search.py` following `src/txtsearch/services/semantic_search.py` structure
- Inject `LexicalStore` and `MetadataStore` via constructor for DI
- Implement async context manager with resource cleanup
- Implement `initialize()`: initialize both lexical and metadata stores
- Implement `search()`: accept `Query` object, validate non-empty text, call `lexical_store.search()`
- Implement `_hydrate_results()`: convert DuckDB results to `SearchHit` objects with normalized scores
- Normalize BM25 scores to 0-1 range using min-max normalization: `(raw_score - min) / (max - min)`
- Store original BM25 score in `SearchHit.extra["bm25_score"]` for debugging
- Set `strategy=SearchStrategy.LEXICAL` on all hits
- Implement `_apply_post_filters()`: filter by source_types and ingested_after using metadata store (avoid N+1 queries)
- Implement `_rerank()`: reassign sequential ranks after filtering (SearchHit is frozen, create new instances)
- **Deliverable**: Lexical search service returning same `SearchHit` shape as semantic search

### Step 4: Extend IndexingService for DuckDB
- Modify `src/txtsearch/services/index.py` to accept optional `LexicalStore` dependency
- Update `__init__()` to store lexical_store reference (nullable for backward compatibility)
- Update `initialize()` in `index_directory()` to initialize lexical store if present
- Update `_persist_document()`: after persisting to vector/metadata stores, also persist to lexical store if present
- Convert `DocumentChunk` objects to dict format expected by `LexicalStore.index_chunks()`
- Map fields: chunk.chunk_id -> document_id, chunk.chunk_id -> chunk_id, chunk.text -> content, etc.
- **Deliverable**: IndexingService populates both semantic and lexical indexes when lexical store is provided

### Step 5: Add Factory Functions for Lexical Services
- Modify `src/txtsearch/services/factory.py` to add DuckDB wiring
- Add constant: `LEXICAL_DB_FILENAME = "lexical.db"`
- Implement `create_lexical_search_service(index_dir: Path)`: create DuckDB connection at `index_dir / LEXICAL_DB_FILENAME`, return `LexicalSearchService`
- Implement `create_test_lexical_search_service()`: use `:memory:` for in-memory DuckDB, return test service
- Update `create_indexing_service()`: instantiate `LexicalStore` at `output_dir / LEXICAL_DB_FILENAME`, inject into `IndexingService`
- Update `create_test_indexing_service()`: instantiate in-memory `LexicalStore`, inject into test service
- Follow existing DI patterns from `create_semantic_search_service()` and `create_indexing_service()`
- **Deliverable**: Factory functions for production and test lexical services with proper DI

### Step 6: Wire Lexical Strategy in SearchCommand
- Modify `src/txtsearch/commands/search.py` to support strategy routing
- Update `SearchCommand.__init__()` to accept optional `lexical_search_service` parameter (nullable)
- Update `run()`: remove hardcoded `StrategyNotSupportedError` for lexical strategy
- Add strategy routing logic: if `input.strategy == SearchStrategy.LEXICAL`, use lexical_search_service
- Raise `StrategyNotSupportedError` if lexical strategy requested but service not provided
- Keep semantic as default; maintain backward compatibility
- Initialize appropriate service based on strategy before calling search
- **Deliverable**: SearchCommand routes to correct service based on strategy parameter

### Step 7: Update CLI Integration
- Modify CLI wiring code that instantiates `SearchCommand` to provide both search services
- Use `factory.create_semantic_search_service()` and `factory.create_lexical_search_service()`
- Pass both services to `SearchCommand` constructor for strategy selection
- Ensure CLI already accepts `--strategy` parameter (verify in `src/txtsearch/cli.py`)
- Add error handling: if lexical index missing, raise `IndexNotFoundError` with guidance to run indexing first
- **Deliverable**: CLI command `txtsearch search --strategy lexical "query"` works end-to-end

### Step 8: Add Unit Tests for LexicalStore
- Create `tests/unit/services/test_lexical_store.py` following `tests/unit/services/test_vector_store.py` structure
- Use class-based organization: `TestLexicalStoreInitialization`, `TestLexicalStoreIndexing`, `TestLexicalStoreSearch`
- Use in-memory DuckDB (`:memory:`) for fast, isolated tests - do NOT mark as slow or external
- Test schema creation and FTS index creation in initialization
- Test bulk chunk insertion with `index_chunks()`
- Test BM25 search with various queries, verify score ordering
- Test search with filters (document_ids)
- Test empty results handling
- **Deliverable**: Comprehensive unit tests for LexicalStore with no external dependencies

### Step 9: Add Unit Tests for LexicalSearchService
- Create `tests/unit/services/test_lexical_search.py` following `tests/unit/services/test_semantic_search.py` structure
- Create `FakeLexicalStore` test double similar to `FakeVectorStore` pattern
- Use class-based organization: `TestLexicalSearchBasic`, `TestLexicalSearchFiltering`, `TestLexicalSearchHydration`
- Test query validation (empty text should raise ValueError)
- Test result hydration to SearchHit objects
- Test score normalization (verify 0-1 range, min-max formula)
- Test post-filters (source_types, ingested_after)
- Test reranking after filtering
- Do NOT mark as slow or external - use fakes for all dependencies
- **Deliverable**: Unit tests for LexicalSearchService using DI with fakes

### Step 10: Add Integration Tests
- Create `tests/integration/services/test_lexical_search_integration.py` following `tests/integration/services/test_semantic_search_integration.py`
- Use real DuckDB with temp file (not in-memory) to test actual FTS behavior
- Test full pipeline: create store, index chunks, search, verify BM25 ranking
- Test that stemming works (e.g., "running" matches "run")
- Test that stopwords are filtered
- Test multi-word queries and ranking
- Mark with `@pytest.mark.slow` since using real DuckDB
- **Deliverable**: Integration tests verifying real DuckDB FTS behavior

### Step 11: Add End-to-End Tests
- Modify `tests/e2e/commands/test_search_command.py` to add lexical strategy tests
- Add class `TestSearchCommandLexicalStrategy` following existing `TestSearchCommandHappyPath` pattern
- Reuse `indexed_codebase` fixture or create new fixture that indexes with lexical support
- Test: search with `strategy=SearchStrategy.LEXICAL` returns results
- Test: lexical finds exact term matches (e.g., "authenticate_user" function name)
- Test: verify SearchHit structure matches semantic search output
- Focus on happy path only - error cases covered by unit tests
- Mark with `@pytest.mark.slow` and `@pytest.mark.external`
- **Deliverable**: E2E test proving lexical search works end-to-end from command to results

### Step 12: Add Error Handling and User Guidance
- Add clear error messages when DuckDB index is missing
- Update `factory.create_lexical_search_service()`: check if `lexical.db` exists, raise `IndexNotFoundError` with message
- Error message should guide users: "Lexical index not found. Run 'txtsearch index' to create the index first."
- Add similar check in CLI layer before instantiating lexical search service
- Ensure `StrategyNotSupportedError` messages are clear and actionable
- **Deliverable**: User-friendly errors that guide users to correct workflow

## Testing Strategy

The testing approach follows the established pyramid (unit > integration > e2e) as specified in CLAUDE.md:

### Unit Tests
- All unit tests use in-memory storage (`:memory:` for DuckDB) and fake dependencies
- Never mark unit tests as slow or external
- Focus on isolated component behavior with DI and test doubles
- Test edge cases: empty queries, no results, filtering logic, score normalization
- Use class-based organization to group related tests

### Integration Tests
- Test component interactions with real DuckDB using temp files
- Verify actual FTS behavior: BM25 ranking, stemming, stopwords
- Mark with `@pytest.mark.slow` since using real external systems
- Keep focused on specific integration points (store + FTS)

### End-to-End Tests
- Test full workflow from SearchCommand through to results
- Only test happy path - verify main user workflow works
- Reuse existing fixtures for indexed codebases
- Mark with `@pytest.mark.slow` and `@pytest.mark.external`
- Validate that lexical search produces correct SearchHit structure matching semantic search

### Test Scenarios
- Query validation (empty text)
- Basic search with BM25 ranking
- Score normalization to 0-1 range
- Filter application (document_ids, source_types, ingested_after)
- Reranking after filtering
- Missing index error handling
- Strategy routing in SearchCommand
- Full indexing + search pipeline
- Stemming behavior (porter stemmer)
- Stopword filtering
- Multi-word query handling
