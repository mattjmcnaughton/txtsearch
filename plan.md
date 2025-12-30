# Plan: Integrate Literal Ripgrep Strategy

## Implementation Steps

### Step 1: Create LiteralSearchService Foundation
- Create `src/txtsearch/services/literal_search.py` following SemanticSearchService architecture pattern (src/txtsearch/services/semantic_search.py:1-237)
- Implement service class with constructor DI accepting `metadata_store`, `ripgrep_path`, and optional `logger`
- Add `_initialized` flag and async context manager methods (`__aenter__`, `__aexit__`)
- Create custom `RipgrepNotFoundError` exception with clear installation instructions for multiple platforms
- **Deliverable**: Service skeleton with proper initialization lifecycle and error types

### Step 2: Implement Ripgrep Binary Detection and Initialization
- Implement `initialize()` method using `asyncio.create_subprocess_exec()` to verify ripgrep availability
- Execute `rg --version` to check binary exists and is executable
- Parse version output and log with structlog (event: "ripgrep_initialized")
- Raise `RipgrepNotFoundError` with platform-specific install instructions on failure
- Set `_initialized = True` on success
- **Deliverable**: Robust initialization that fails fast with actionable error messages

### Step 3: Build Safe Command Construction
- Implement `_build_ripgrep_args(query: Query) -> list[str]` method
- Construct argument list (never string concatenation) with:
  - `--json` for structured output parsing
  - `--fixed-strings` for literal (non-regex) matching
  - `--max-count` from query.top_k to limit results per file
  - `--context` from query extras for context lines (if include_snippets enabled)
  - `--no-config` to ignore user ripgrep config
  - `--` separator before search pattern to prevent flag injection
- Add query.text as final argument after separator
- Handle search_root path determination (from metadata store or service initialization)
- **Deliverable**: Safe argument builder that prevents shell injection attacks

### Step 4: Execute Ripgrep with Async Subprocess
- Implement `_execute_ripgrep(args: list[str], query: Query) -> list[RipgrepMatch]` method
- Use `asyncio.create_subprocess_exec(*[self._ripgrep_path] + args)` with PIPE for stdout/stderr
- Never use `shell=True` (security critical)
- Handle ripgrep return codes: 0 (matches found), 1 (no matches), 2+ (error)
- Parse stdout using `_parse_ripgrep_output()` even on returncode=1 (no matches)
- Log execution with structlog (event: "executing_ripgrep", include query_id and args)
- Handle CancelledError for graceful cancellation
- **Deliverable**: Secure async subprocess execution with proper error handling

### Step 5: Parse Ripgrep JSON Output
- Create `RipgrepMatch` dataclass to hold intermediate match representation (file_path, line_number, column, match_text, context_before, context_after)
- Implement `_parse_ripgrep_output(output: str, query: Query) -> list[RipgrepMatch]` method
- Parse JSON line-by-line handling record types: "begin", "match", "context"
- Extract file paths from "begin" records
- Extract match details from "match" records (line_number, column, submatches)
- Accumulate context_before and context_after from "context" records
- Handle JSON parsing errors gracefully with warning logs
- **Deliverable**: Robust JSON parser that extracts all match metadata including context

### Step 6: Convert to SearchHit Schema
- Implement `_parse_results(rg_matches: list[RipgrepMatch], query: Query) -> list[SearchHit]` method
- For each RipgrepMatch, look up document_id via `_get_document_id_by_path()` using metadata store
- Build snippet from context_before + match_text + context_after if query.include_snippets
- Calculate highlights with character offsets if query.include_highlights
- Create SearchHit objects with:
  - strategy = SearchStrategy.LITERAL
  - chunk_id = None (literal search doesn't use chunks)
  - score = None (ripgrep doesn't provide scores)
  - rank = sequential from 0 (reranked later)
  - extra = {"file_path": ..., "line_number": ..., "column": ...}
- Skip matches for files not found in metadata store (log warning)
- **Deliverable**: SearchHit converter maintaining schema consistency with semantic search

### Step 7: Apply Metadata Filters and Reranking
- Implement `_apply_post_filters(query: Query, hits: list[SearchHit]) -> list[SearchHit]` following semantic search pattern (src/txtsearch/services/semantic_search.py:184-230)
- Bulk-fetch documents from metadata store to avoid N+1 queries
- Filter by source_types if specified in query.filters
- Filter by ingested_after if specified in query.filters
- Implement `_rerank(hits: list[SearchHit]) -> list[SearchHit]` to reassign sequential ranks after filtering
- Create new SearchHit instances with updated ranks (SearchHit is frozen)
- **Deliverable**: Post-filtering and reranking that matches semantic search behavior

### Step 8: Implement Main Search Method
- Implement `async search(query: Query) -> list[SearchHit]` method
- Validate query.text is not empty (raise ValueError if empty/whitespace)
- Check `_initialized` flag (raise RuntimeError if not initialized)
- Log search_started event with query_id and query_text
- Orchestrate: build args → execute ripgrep → parse output → convert to hits → apply filters → rerank
- Log search_completed event with query_id and hit_count
- Return final list of SearchHit objects
- **Deliverable**: Complete search method integrating all components with proper validation and logging

### Step 9: Create Unit Tests with Fakes
- Create `tests/unit/services/test_literal_search.py`
- Use class-based test organization (e.g., `TestLiteralSearchService`)
- Implement test cases:
  - `test_empty_query_raises_error`: Verify ValueError on empty query text
  - `test_ripgrep_not_found_raises_error`: Verify RipgrepNotFoundError with invalid ripgrep_path
  - `test_context_manager_lifecycle`: Verify initialization via async context manager
  - `test_search_with_no_matches`: Verify empty list returned (not error) when ripgrep finds nothing
- Reuse `FakeMetadataStore` from semantic search tests
- Mock subprocess execution to avoid external ripgrep dependency
- Ensure tests run fast (never marked @pytest.mark.slow)
- **Deliverable**: Fast unit tests with 100% isolation using test doubles

### Step 10: Create Integration Tests
- Create integration test class marked with `@pytest.mark.slow` and `@pytest.mark.external`
- Implement `test_basic_search` using tmp_path fixture:
  - Create test files with known content
  - Index files with metadata store
  - Execute literal search and verify results match expected SearchHit schema
- Verify strategy field is SearchStrategy.LITERAL
- Verify chunk_id is None and score is None
- Verify snippet contains expected text
- Use real ripgrep binary (tests will be skipped if ripgrep not available)
- **Deliverable**: Integration tests validating end-to-end functionality with real ripgrep

### Step 11: Wire to CLI Search Command
- Update `src/txtsearch/commands/search.py` to support SearchStrategy.LITERAL
- Ensure `--strategy literal` flag routes to LiteralSearchService
- Add factory function `create_literal_search_service()` in `src/txtsearch/services/factory.py`
- Wire factory to return LiteralSearchService when strategy is LITERAL
- Ensure all existing search command flags work (--limit, --context, --json)
- Maintain consistent output format with semantic search results
- **Deliverable**: CLI integration allowing `txtsearch search "query" --strategy literal`

### Step 12: Verify Acceptance Tests 1-6
- Manually test verification scenario 1: Basic literal search finds matches
- Manually test verification scenario 2: Context lines appear in snippets
- Manually test verification scenario 3: Top-K limiting works correctly
- Manually test verification scenario 4: No matches returns empty list
- Verify scenario 5: RipgrepNotFoundError via unit test (already covered in Step 9)
- Verify scenario 6: Empty query ValueError via unit test (already covered in Step 9)
- Document any deviations or issues in test results
- **Deliverable**: Verified functionality against acceptance criteria 1-6

## Testing Strategy

### Unit Testing Approach
- **Framework**: pytest with pytest-asyncio (asyncio_mode = "auto" per CLAUDE.md)
- **Isolation**: Use `FakeMetadataStore` and mock `asyncio.create_subprocess_exec()` to avoid external dependencies
- **Speed**: All unit tests must be fast (<100ms each) and never marked @pytest.mark.slow
- **Class Organization**: Group related tests into classes (e.g., `TestLiteralSearchService`, `TestRipgrepArgumentConstruction`, `TestRipgrepOutputParsing`)
- **Coverage Areas**:
  - Service initialization and lifecycle (context manager)
  - Binary detection error handling (missing ripgrep)
  - Input validation (empty queries, invalid parameters)
  - Argument construction safety (no shell injection)
  - Output parsing (JSON format, edge cases)
  - SearchHit conversion (schema compliance)
  - Post-filtering and reranking logic

### Integration Testing Approach
- **Framework**: pytest with `@pytest.mark.slow` and `@pytest.mark.external` markers
- **Real Dependencies**: Use actual ripgrep binary (skip if not available)
- **Test Data**: Create temporary directories with known file content using tmp_path fixture
- **Metadata Store**: Use real SQLite database (in-memory or temp file)
- **Coverage Areas**:
  - End-to-end search workflow (index → search → results)
  - JSON output format consistency with semantic search
  - Context line extraction
  - Result limiting (top_k)
  - No matches scenario (empty results, not error)

### Edge Cases and Error Scenarios
- **Empty/whitespace query**: Should raise ValueError
- **Ripgrep not installed**: Should raise RipgrepNotFoundError with install instructions
- **Ripgrep execution failure**: Should log error and raise RuntimeError
- **No matches found**: Should return empty list (returncode=1 is not error)
- **Invalid JSON output**: Should log warning and skip malformed lines
- **File not in metadata store**: Should log warning and skip match
- **Concurrent searches**: Should handle multiple async searches safely

### Test Execution
- Run unit tests frequently during development: `just test` (or pytest command from justfile)
- Run integration tests before final commit: `pytest -m slow`
- Ensure all tests pass before marking issue complete
- Follow test pyramid: more unit tests, fewer integration tests

### Validation Against Acceptance Criteria
- **Test 1 (Basic Search)**: Integration test with real file containing "TODO"
- **Test 2 (Context Lines)**: Integration test verifying multi-line snippets
- **Test 3 (Top-K Limiting)**: Integration test verifying result count matches --limit
- **Test 4 (No Matches)**: Integration test with nonexistent search term returns []
- **Test 5 (Error Handling)**: Unit test with invalid ripgrep_path raises RipgrepNotFoundError
- **Test 6 (Empty Query)**: Unit test verifying ValueError on empty string

All acceptance tests 1-6 must pass before implementation is considered complete.
