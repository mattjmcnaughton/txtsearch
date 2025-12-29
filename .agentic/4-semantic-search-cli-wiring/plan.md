# Implementation Plan: Wire CLI index/search Semantic Flow

## Overview

This plan implements the `search` command in the CLI, wiring it to the existing `SemanticSearchService`. The index command is already implemented.

## Implementation Steps

### Step 1: Add Required Imports to cli.py

Add imports for the search service factory and models:
- `create_semantic_search_service` from factory
- `Query` from models/query
- `SearchHit` from models/hit
- `SearchStrategy as ModelSearchStrategy` from models/enums
- `json` for JSON output

### Step 2: Add JSON Output Flag to Search Command

Add a `--json` / `-j` boolean option to the search command signature for structured output.

### Step 3: Implement Search Command Logic

Replace the TODO placeholder with actual implementation:

1. **Validate index exists** (already done)
2. **Convert CLI enum to model enum**:
   ```python
   from txtsearch.models.enums import SearchStrategy as ModelSearchStrategy
   model_strategy = ModelSearchStrategy(strategy.value)
   ```
3. **Create Query object**:
   ```python
   query_obj = Query(
       text=query,
       strategy=model_strategy,
       top_k=limit,
       include_snippets=True,
   )
   ```
4. **Execute search in async context**:
   ```python
   async def run_search() -> list[SearchHit]:
       async with create_semantic_search_service(index_dir=index_dir) as service:
           await service.initialize()
           return await service.search(query_obj)

   hits = asyncio.run(run_search())
   ```
5. **Output results** (human-readable or JSON)

### Step 4: Implement Human-Readable Output

Format search results for terminal display:
- Show result count
- For each hit, display:
  - Rank and score (formatted as percentage)
  - Document URI or path
  - Snippet preview (truncated if needed)
- Handle zero results gracefully

### Step 5: Implement JSON Output

When `--json` flag is set:
- Use `SearchHit.model_dump()` for each hit
- Output as a JSON array
- Include metadata like query text, strategy, result count

### Step 6: Error Handling

Add error handling for:
- Empty query text (ValueError from Query validation)
- Strategy not supported (currently only semantic works)
- Index exists but is empty/corrupt

### Step 7: Write Unit Tests

Create `tests/unit/test_cli.py` with tests for:
- Search command invokes factory correctly
- Human-readable output format
- JSON output format
- Error cases (missing index, empty query)

### Step 8: Write Integration Test

Create `tests/integration/test_cli_search.py`:
- Index a test directory
- Run search command
- Verify results

## Files Modified

| File | Change |
|------|--------|
| `src/txtsearch/cli.py` | Implement search command |
| `tests/unit/test_cli.py` | Add CLI unit tests (new file) |

## Verification

After implementation, verify with:

```bash
# Create test data
mkdir -p /tmp/test-txtsearch
echo "def authenticate_user(username, password): pass" > /tmp/test-txtsearch/auth.py

# Index the directory
uv run txtsearch index /tmp/test-txtsearch

# Search with semantic strategy
uv run txtsearch search "authentication"

# Search with JSON output
uv run txtsearch search --json "authentication"

# Run tests
just test
```

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Enum mismatch between CLI and models | Explicit conversion with clear error message |
| ChromaDB not initialized | Factory handles initialization |
| Large result sets | Limit parameter already in place |
