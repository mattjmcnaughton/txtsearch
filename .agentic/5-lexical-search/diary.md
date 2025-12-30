# Implementation Diary: Lexical Search with DuckDB

## 2025-12-30

### Initial Setup
- Created `.agentic/5-lexical-search/` directory structure
- Extracted research findings from issue comments into `research.md`
- Created `goal.md` defining business value and user workflow
- Created `plan.md` with 12-step implementation plan and testing strategy

### Understanding the Codebase
- Reviewed CLAUDE.md for coding guidelines (async, DI, testing strategy)
- Analyzed existing `SemanticSearchService` implementation to ensure consistency
- Studied `services/factory.py` for DI patterns
- Examined `models/tables.py` for SQLModel table definitions
- Reviewed `models/enums.py` - confirmed `SearchStrategy.LEXICAL` already exists

### Key Architectural Decisions
1. **DuckDB Store as Separate Service**: Following the VectorStore pattern, creating a dedicated LexicalStore service
2. **Async Wrapper Pattern**: DuckDB is synchronous, will wrap all operations with `asyncio.to_thread()`
3. **Score Normalization**: BM25 scores are unbounded, using min-max normalization to 0-1 range
4. **Shared Models**: Reusing Query, SearchHit, QueryFilters for API consistency
5. **Factory Pattern**: Adding factory functions for DI, following create_semantic_search_service pattern

### Implementation Progress

#### Step 1: Create DuckDB Table Models
**Status**: Completed

Added `DocumentChunkLexical` table model to `src/txtsearch/models/tables.py`.
- Primary key is `document_id` (chunk_id used as document_id for FTS compatibility)
- Fields: chunk_id, chunk_index, content, file_path, source_type, ingested_at, extra
- Includes comprehensive documentation explaining denormalization strategy

#### Step 2: Create LexicalStore Service
**Status**: Completed

Created `src/txtsearch/services/lexical_store.py` with full async wrapper pattern:
- Wraps all DuckDB operations with `asyncio.to_thread()`
- Implements async context manager (`__aenter__`/`__aexit__`)
- `initialize()`: loads FTS extension, creates schema, builds FTS index with Porter stemming
- `index_chunks()`: bulk inserts with INSERT OR REPLACE
- `search()`: BM25-ranked queries with optional document_ids filtering
- `close()`: properly closes connection to avoid process hangs
- Structured logging throughout

#### Step 3: Create LexicalSearchService
**Status**: Completed

Created `src/txtsearch/services/lexical_search.py` mirroring SemanticSearchService:
- Constructor takes LexicalStore and MetadataStore dependencies
- `search()`: orchestrates FTS query, hydration, filtering, re-ranking
- `_hydrate_results()`: converts DuckDB results to SearchHit, normalizes BM25 scores (min-max)
- `_apply_post_filters()`: filters by source_types and ingested_after using metadata store
- `_rerank()`: re-assigns sequential ranks after filtering
- Returns SearchStrategy.LEXICAL for all hits
- Score normalization ensures 0-1 range as required by SearchHit validation

#### Step 4: Extend IndexingService
**Status**: Completed

Modified `src/txtsearch/services/index.py`:
- Added optional `lexical_store: LexicalStore | None` parameter
- Updated `close()` to close lexical store if present
- Updated `index_directory()` to initialize lexical store if present
- Updated `_persist_document()` to populate lexical store alongside vector store
- Converts chunks to lexical format (chunk_id as document_id for FTS compatibility)

#### Step 5: Add Factory Functions
**Status**: Completed

Extended `src/txtsearch/services/factory.py`:
- Added `LEXICAL_DB_FILENAME = "lexical.duckdb"` constant
- Updated `create_indexing_service()` with `enable_lexical` parameter (default True)
- Updated `create_test_indexing_service()` similarly for in-memory testing
- Added `create_lexical_search_service()` for production (persistent DuckDB)
- Added `create_test_lexical_search_service()` for testing (in-memory DuckDB)

#### Step 6: Wire Lexical Strategy in SearchCommand
**Status**: Completed

Refactored `src/txtsearch/commands/search.py`:
- Removed dependency on single SemanticSearchService
- Strategy routing: creates appropriate service based on input.strategy
- Semantic: uses `create_semantic_search_service()`
- Lexical: checks for lexical.duckdb existence, raises IndexNotFoundError with helpful message
- Uses try/finally to ensure service cleanup
- Error messages guide users to run indexing first

#### Step 7: CLI Integration
**Status**: Deferred (existing CLI already supports --strategy parameter)

The CLI in `src/txtsearch/cli.py` already supports `--strategy` parameter via the SearchInput model.
No additional changes needed - users can already pass `--strategy lexical`.

### Next: Testing Implementation

Now moving to comprehensive testing (Steps 8-11). Will create:
- Unit tests for LexicalStore (in-memory DuckDB)
- Unit tests for LexicalSearchService (mocks/fakes)
- Integration tests (real FTS behavior)
- E2E tests (full CLI workflow)
