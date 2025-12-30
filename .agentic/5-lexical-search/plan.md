# Plan: Lexical Search with DuckDB

## Implementation Steps

### Step 1: Create DuckDB Document Chunk Table Model
- Add `DocumentChunkLexical` table model in `src/txtsearch/models/tables.py`
- Define schema with fields: `document_id` (PK), `chunk_id`, `chunk_index`, `content`, `file_path`, `source_type`, `ingested_at`, `extra` (JSON)
- Follow existing `DocumentRecord` and `ChunkRecord` patterns
- Ensure compatibility with Pydantic domain models for conversion
- **Deliverable**: Table model ready for DuckDB FTS indexing

### Step 2: Implement LexicalStore Service
- Create `src/txtsearch/services/lexical_store.py`
- Implement async context manager with `__aenter__`/`__aexit__`
- Wrap all DuckDB operations with `asyncio.to_thread()` (synchronous library)
- Implement `initialize()`: load FTS extension, create schema, create FTS index
- Implement `index_chunks()`: bulk insert chunks using prepared statements
- Implement `search()`: execute BM25 queries with optional filters
- Implement `close()`: cleanup connection (critical to avoid hangs)
- Use structured logging with snake_case event names
- **Deliverable**: Production-ready lexical store service

### Step 3: Implement LexicalSearchService
- Create `src/txtsearch/services/lexical_search.py`
- Mirror `SemanticSearchService` architecture and API surface
- Inject `LexicalStore` and `MetadataStore` via constructor
- Implement async context manager for resource management
- Implement `initialize()`: setup underlying stores
- Implement `search()`: orchestrate BM25 search with hydration and filtering
- Implement `_hydrate_results()`: convert DuckDB results to `SearchHit` objects
- Normalize BM25 scores to 0-1 range using min-max normalization
- Implement `_apply_post_filters()`: filter by source_types and ingested_after
- Implement `_rerank()`: re-assign sequential ranks after filtering
- Use `SearchStrategy.LEXICAL` for all hits
- **Deliverable**: Search service compatible with existing Query/SearchHit contracts

### Step 4: Extend IndexingService for DuckDB Population
- Modify `src/txtsearch/services/index.py`
- Add optional `lexical_store: LexicalStore | None` parameter to constructor
- In `index_directory()`, populate DuckDB alongside ChromaDB when lexical_store is present
- Convert chunks to format expected by `lexical_store.index_chunks()`
- Ensure atomic operations (both stores succeed or fail together)
- Log lexical indexing progress separately
- **Deliverable**: Indexing service populates both semantic and lexical stores

### Step 5: Add Factory Functions for Lexical Services
- Extend `src/txtsearch/services/factory.py`
- Add `LEXICAL_DB_FILENAME = "lexical.duckdb"` constant
- Implement `create_lexical_search_service(index_dir: Path)` for production
- Implement `create_test_lexical_search_service()` using in-memory DuckDB (`:memory:`)
- Update `create_indexing_service()` to optionally instantiate `LexicalStore`
- Update `create_test_indexing_service()` similarly for tests
- Follow existing patterns for engine/connection management
- **Deliverable**: Factory functions enabling DI for lexical services

### Step 6: Wire Lexical Strategy in SearchCommand
- Modify `src/txtsearch/commands/search.py`
- Update command routing to detect `strategy == SearchStrategy.LEXICAL`
- Instantiate `LexicalSearchService` via factory when lexical strategy selected
- Ensure proper resource cleanup in finally blocks
- Handle `FileNotFoundError` when lexical.duckdb missing with actionable error
- Maintain existing semantic search path unchanged
- **Deliverable**: CLI routes lexical queries to LexicalSearchService

### Step 7: Update CLI Integration and Error Handling
- Verify `src/txtsearch/cli.py` supports `--strategy lexical` option
- Add error handling for missing lexical index in search command
- Provide clear user guidance: "Lexical index not found. Run 'txtsearch index' to create it."
- Ensure `txtsearch index` populates lexical.duckdb by default
- Test end-to-end CLI workflow: index -> search with lexical strategy
- **Deliverable**: Complete CLI integration with helpful error messages

### Step 8: Write Unit Tests for LexicalStore
- Create `tests/unit/services/test_lexical_store.py`
- Use in-memory DuckDB (`:memory:`) for all tests
- Test class: `TestLexicalStoreInitialization`
  - Verify FTS extension loads
  - Verify schema creation
- Test class: `TestLexicalStoreIndexing`
  - Test bulk chunk insertion
  - Test duplicate handling (INSERT OR REPLACE)
  - Verify chunk count returns
- Test class: `TestLexicalStoreSearch`
  - Test basic BM25 search
  - Test empty results
  - Test filtering by document_ids
  - Verify score ordering (descending)
- Never mark unit tests as `@pytest.mark.slow` or `@pytest.mark.external`
- **Deliverable**: Comprehensive unit test coverage for LexicalStore

### Step 9: Write Unit Tests for LexicalSearchService
- Create `tests/unit/services/test_lexical_search.py`
- Use in-memory dependencies (mock LexicalStore, fake MetadataStore)
- Test class: `TestLexicalSearchBasic`
  - Test successful search with results
  - Test empty query raises ValueError
  - Test empty results handling
- Test class: `TestLexicalSearchHydration`
  - Test score normalization (BM25 -> 0-1 range)
  - Test SearchHit construction
  - Test snippet inclusion when requested
- Test class: `TestLexicalSearchFiltering`
  - Test source_types filtering
  - Test ingested_after filtering
  - Test re-ranking after filters
- **Deliverable**: Unit tests ensuring business logic correctness

### Step 10: Write Integration Tests for Lexical Search
- Create `tests/integration/services/test_lexical_search_integration.py`
- Mark with `@pytest.mark.slow` (involves real DuckDB operations)
- Use temporary directories for database files
- Test class: `TestLexicalSearchIntegration`
  - Test end-to-end: index chunks -> search -> verify results
  - Test BM25 ranking order with real FTS
  - Test stemming behavior (e.g., "running" matches "run")
  - Test stopword filtering (common words ignored)
- Verify integration between LexicalStore and MetadataStore
- **Deliverable**: Integration tests proving component interactions work

### Step 11: Write E2E Tests for Lexical Search Command
- Create `tests/e2e/commands/test_lexical_search_command.py`
- Mark with `@pytest.mark.slow` and `@pytest.mark.external`
- Focus on happy path only (error cases covered by unit tests)
- Test workflow:
  1. Index sample files using `IndexCommand`
  2. Search with `--strategy lexical` using `SearchCommand`
  3. Verify SearchHit results are returned
  4. Verify BM25 ranking (exact term matches rank higher)
- Use temp directory fixtures for isolation
- **Deliverable**: E2E test validating full user workflow

### Step 12: Add Comprehensive Error Handling and User Guidance
- In `SearchCommand`, catch specific exceptions:
  - `FileNotFoundError`: "Lexical index not found at {path}. Run 'txtsearch index' first."
  - `duckdb.Error`: "DuckDB query failed: {error}. Index may be corrupted."
- In `LexicalStore.initialize()`, catch extension loading errors
- Add validation for empty search queries in service layer
- Log all errors with structured context (file paths, query text)
- Ensure error messages guide users toward resolution
- **Deliverable**: Production-ready error handling with helpful messages

## Testing Strategy

### Unit Tests (Fast, No External Dependencies)
- Use in-memory DuckDB (`:memory:`) for LexicalStore tests
- Use mock/fake dependencies for LexicalSearchService tests
- Never mark as `@pytest.mark.slow` or `@pytest.mark.external`
- Focus on business logic, edge cases, error handling
- Target: > 90% code coverage for new services

### Integration Tests (Moderate Speed, Real Components)
- Use temporary file-based DuckDB for realistic FTS behavior
- Test component interactions (store + service + metadata)
- Mark with `@pytest.mark.slow` since they perform I/O
- Verify FTS features work correctly (stemming, stopwords, BM25)
- Test concurrent operations if applicable

### E2E Tests (Slow, Full Workflow)
- Mark with `@pytest.mark.slow` and `@pytest.mark.external`
- Cover only the happy path (user indexes, then searches)
- Skip trivial scenarios and error cases (unit tests handle those)
- Use real CLI commands via `IndexCommand` and `SearchCommand`
- Verify end-to-end integration across all layers

### Test Organization
- Use class-based organization (e.g., `TestLexicalStoreSearch`, `TestScoreNormalization`)
- Group related test cases into logical test classes
- Follow existing patterns from semantic search tests
- Reuse fixtures for temp directories, fake clients, in-memory databases

### Validation Points
- BM25 scores are properly normalized to 0-1 range
- SearchHit objects match semantic search structure exactly
- Filtering and re-ranking behave identically to semantic search
- Error messages are clear and actionable
- Performance is acceptable (< 1s for moderate datasets)
