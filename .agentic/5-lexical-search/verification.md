# Verification Guide: Lexical Search Implementation

This guide outlines how to verify the lexical search implementation is working correctly.

## Prerequisites

Before running verification steps, ensure:
- Python 3.12+ installed
- Dependencies installed: `just install` or `uv sync --group dev`
- Working directory is repository root

## Step 1: Run Code Quality Checks

### Linting
```bash
just lint
```

**Expected Output**: No linting errors. All files should pass ruff checks.

**Why**: Ensures code follows project style guidelines and has no obvious issues.

### Formatting
```bash
just format-check
```

**Expected Output**: No formatting issues reported.

**Why**: Confirms code is formatted consistently with the project standard.

### Type Checking
```bash
just typecheck
```

**Expected Output**: No type errors.

**Why**: Validates type annotations are correct and catches potential type-related bugs.

## Step 2: Run Unit Tests

### All Unit Tests
```bash
just test-unit
```

**Expected Output**: All tests pass. Look for specific tests:
- `test_lexical_store.py`: ~11 tests passing
- `test_lexical_search.py`: ~13 tests passing (including new identical scores test)

**Why**: Unit tests verify individual components work correctly in isolation.

### Specific Lexical Tests Only
```bash
uv run pytest tests/unit/services/test_lexical_store.py -v
uv run pytest tests/unit/services/test_lexical_search.py -v
```

**Expected Output**: All lexical-specific tests pass with verbose output showing test names.

**Why**: Focused verification of lexical search components.

## Step 3: Run Integration Tests

```bash
just test-integration
```

**Expected Output**: All integration tests pass, including:
- `test_lexical_search_integration.py`: 3 tests passing
  - Test end-to-end search workflow
  - Test BM25 ranking prefers term frequency
  - Test stemming matches word variants

**Why**: Verifies real DuckDB FTS behavior works correctly.

**Note**: These tests are marked `@pytest.mark.slow` and will take longer.

## Step 4: Run E2E Tests

```bash
just test-e2e
```

**Expected Output**: All E2E tests pass, including:
- `test_lexical_search_command.py`: 2 tests passing
  - Test index and search workflow
  - Test lexical search without index raises error

**Why**: Validates the complete user workflow from CLI works end-to-end.

**Note**: These are the slowest tests as they exercise the full stack.

## Step 5: Manual Functional Testing

### Create Test Files
```bash
mkdir -p /tmp/txtsearch-test
cat > /tmp/txtsearch-test/auth.py << 'EOF'
def authenticate_user(username, password):
    """Authenticate user with username and password."""
    if not username or not password:
        raise ValueError("Username and password required")
    return verify_credentials(username, password)

def verify_credentials(username, password):
    """Verify user credentials against database."""
    return check_database(username, password)
EOF

cat > /tmp/txtsearch-test/utils.py << 'EOF'
def calculate_sum(a, b):
    """Calculate the sum of two numbers."""
    return a + b

def calculate_product(a, b):
    """Calculate the product of two numbers."""
    return a * b
EOF
```

### Index the Files
```bash
mkdir -p /tmp/txtsearch-index
uv run txtsearch index /tmp/txtsearch-test --output /tmp/txtsearch-index
```

**Expected Output**:
- Success message indicating files were indexed
- No errors
- Files created:
  - `/tmp/txtsearch-index/meta.db` (SQLite metadata)
  - `/tmp/txtsearch-index/semantic/` (ChromaDB vector store)
  - `/tmp/txtsearch-index/lexical.duckdb` (DuckDB FTS index)

**Why**: Verifies indexing creates all required artifacts including the new lexical.duckdb file.

### Search with Lexical Strategy
```bash
uv run txtsearch search --strategy lexical "authenticate password" /tmp/txtsearch-index
```

**Expected Output**:
- Search results showing matches from `auth.py`
- Results ranked by BM25 score
- Higher-ranked results contain both "authenticate" and "password"
- Scores between 0.0 and 1.0

**Sample Output**:
```
Found 2 results using lexical strategy:

1. auth.py (score: 0.95)
   def authenticate_user(username, password):

2. auth.py (score: 0.72)
   return verify_credentials(username, password)
```

**Why**: Confirms lexical search returns relevant results with proper BM25 ranking.

### Search with Semantic Strategy (Comparison)
```bash
uv run txtsearch search --strategy semantic "authenticate password" /tmp/txtsearch-index
```

**Expected Output**: Different results/ranking than lexical search, demonstrating the two strategies work differently.

**Why**: Verifies both strategies coexist and can be selected independently.

### Test Error Handling
```bash
mkdir -p /tmp/txtsearch-empty
uv run txtsearch search --strategy lexical "test" /tmp/txtsearch-empty
```

**Expected Output**:
- Error message mentioning "lexical.duckdb" not found
- Guidance to run "txtsearch index" first
- Non-zero exit code

**Why**: Confirms helpful error messages when lexical index is missing.

## Step 6: Verify Code Changes

### Verify New Files Exist
```bash
ls -la src/txtsearch/services/lexical*.py
ls -la tests/unit/services/test_lexical*.py
ls -la tests/integration/services/test_lexical*.py
ls -la tests/e2e/commands/test_lexical*.py
ls -la .agentic/5-lexical-search/
```

**Expected Output**: All new files present.

**Why**: Confirms all implementation and documentation files were created.

### Verify Git History
```bash
git log --oneline -5
```

**Expected Output**:
- Commit for review fixes
- Commit for test suite
- Commit for core implementation

**Why**: Validates proper git history with meaningful commit messages.

## Step 7: Performance Sanity Check

### Index Larger Dataset
```bash
# Index this repository
mkdir -p /tmp/txtsearch-repo-index
uv run txtsearch index . --output /tmp/txtsearch-repo-index --include "*.py"
```

**Expected Output**:
- Completes in reasonable time (< 1 minute for txtsearch codebase)
- Creates lexical.duckdb file
- No memory issues or crashes

### Search Performance
```bash
time uv run txtsearch search --strategy lexical "async function" /tmp/txtsearch-repo-index
```

**Expected Output**:
- Results returned in < 1 second
- BM25 scores properly normalized
- Relevant Python async functions ranked highly

**Why**: Confirms performance is acceptable for real-world usage.

## Step 8: Cleanup

```bash
rm -rf /tmp/txtsearch-test /tmp/txtsearch-index /tmp/txtsearch-empty /tmp/txtsearch-repo-index
```

## Verification Checklist

Use this checklist to track verification progress:

- [ ] ✅ Linting passes (`just lint`)
- [ ] ✅ Formatting passes (`just format-check`)
- [ ] ✅ Type checking passes (`just typecheck`)
- [ ] ✅ Unit tests pass (`just test-unit`)
- [ ] ✅ Integration tests pass (`just test-integration`)
- [ ] ✅ E2E tests pass (`just test-e2e`)
- [ ] ✅ Manual indexing creates lexical.duckdb
- [ ] ✅ Lexical search returns ranked results
- [ ] ✅ Error handling works (missing index)
- [ ] ✅ Both strategies (lexical and semantic) work independently
- [ ] ✅ Performance is acceptable (< 1s search, < 1min index for moderate codebase)
- [ ] ✅ All documentation files present in `.agentic/5-lexical-search/`

## Expected Test Results Summary

**Total Tests**: ~30+ new tests
- Unit tests (LexicalStore): ~11 tests
- Unit tests (LexicalSearchService): ~13 tests
- Integration tests: ~3 tests
- E2E tests: ~2 tests

**All tests should pass** with no warnings or errors.

## Troubleshooting

### Issue: DuckDB FTS extension not found
**Solution**: Ensure DuckDB version >= 1.4.1. Check `pyproject.toml` dependencies.

### Issue: Tests fail with "Connection not closed" warnings
**Solution**: Verify all tests properly call `await service.close()` in cleanup.

### Issue: Score normalization fails
**Solution**: Check that all scores are in 0.0-1.0 range. Review `_hydrate_results()` logic.

### Issue: lexical.duckdb not created during indexing
**Solution**: Verify `enable_lexical=True` in factory functions and IndexingService receives LexicalStore.

## Success Criteria

The implementation is verified and ready for merge when:

1. **All automated tests pass** (unit, integration, E2E)
2. **Code quality checks pass** (lint, format, typecheck)
3. **Manual testing confirms**:
   - Lexical indexing creates lexical.duckdb
   - Lexical search returns BM25-ranked results
   - Scores are normalized to 0-1 range
   - Error messages are helpful
4. **Performance is acceptable**:
   - Search < 1s for moderate codebases
   - Indexing < 1min for moderate codebases
5. **Documentation is complete**:
   - research.md, goal.md, plan.md, diary.md
   - review.md, review-response.md, verification.md

## Notes

- Unit tests are fast and should complete in seconds
- Integration/E2E tests are slower due to real I/O operations
- Manual testing verifies user experience, not just code correctness
- Performance benchmarks are sanity checks, not strict requirements
