# Ripgrep Integration Research

Issue: https://github.com/mattjmcnaughton/txtsearch/issues/6

## Overview

This document captures research and architectural decisions for integrating ripgrep as a literal search strategy in txtsearch.

## Architecture Decision: File-Level vs Chunk-Level Results

**Decision: Start with file-level results for the MVP.**

### Trade-offs Considered

#### File-Level (chosen for MVP)

- Simpler - ripgrep naturally works at file level
- Faster - no chunk boundary lookups required
- Matches user expectations from grep-like tools
- Works even if files aren't indexed yet
- `SearchHit.chunk_id` is already optional in the schema

#### Chunk-Level (deferred)

- Would be consistent with `SemanticSearchService` which returns chunk-level results
- Would enable hybrid search (fuse literal + semantic at chunk level)
- But adds complexity: mapping ripgrep line numbers to chunk `line_start`/`line_end` ranges
- Edge cases like matches spanning chunk boundaries
- Requires files to be indexed first

### Implementation Approach

The `LiteralSearchService` will:

1. Shell out to ripgrep with `--json` output for machine-parseable results
2. Map file paths to `document_id` via `MetadataStore.get_document_by_uri()`
3. Return `SearchHit` objects with `chunk_id=None`
4. Use the `Highlight` model to capture precise line/character positions from ripgrep

The architecture will allow chunk-mapping to be added later if needed for hybrid search:

```python
async def search(self, query: Query, resolve_chunks: bool = False) -> list[SearchHit]:
```

---

## Service Design

### Recommended: `LiteralSearchService`

Follows the existing `SemanticSearchService` pattern:

- Implements `async def search(query: Query) -> list[SearchHit]`
- Uses `asyncio.create_subprocess_exec()` for async subprocess handling
- Injected dependencies: `MetadataStore` (optional for index-aware mode)

### Subprocess Execution Pattern

```python
async def _run_ripgrep(self, args: list[str]) -> tuple[str, str, int]:
    proc = await asyncio.create_subprocess_exec(
        "rg", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return stdout.decode(), stderr.decode(), proc.returncode
```

### Key Ripgrep Flags

| Flag | Purpose |
|------|---------|
| `--json` | Machine-parseable output (line-delimited JSON) |
| `-F` / `--fixed-strings` | Literal matching (no regex interpretation) |
| `-C <num>` | Context lines (before and after) |
| `--glob` / `-g` | Include patterns |
| `--iglob` with `!` | Exclude patterns |
| `-n` | Line numbers (included in JSON automatically) |
| `--max-count` | Limit matches per file |
| `-i` | Case insensitive |

---

## Output Parsing

Ripgrep's `--json` output gives structured data per line:

```json
{"type":"match","data":{"path":{"text":"src/foo.py"},"lines":{"text":"def search(query):"},"line_number":42,"submatches":[{"match":{"text":"search"},"start":4,"end":10}]}}
```

### Mapping to SearchHit

| Ripgrep Field | SearchHit Field |
|---------------|-----------------|
| `data.path.text` | Look up via `metadata_store.get_document_by_uri()` → `document_id` |
| `data.line_number` | `highlights[].line_start` |
| `data.submatches[].start/end` | `highlights[].char_start/char_end` |
| `data.lines.text` | `snippet` |

### Score Computation

Ripgrep doesn't provide relevance scores. Options:

1. Rank by match count per file
2. Use BM25 on matched lines
3. Leave `score=None` (simplest MVP approach)

**Decision:** Use `score=None` for MVP, rely on ripgrep's default ordering.

---

## Pattern/Filter Integration

### Include/Exclude Patterns

Map directly to ripgrep globs:

```python
for pattern in include_patterns:
    args.extend(["--glob", pattern])  # e.g., "*.py"
for pattern in exclude_patterns:
    args.extend(["--glob", f"!{pattern}"])  # e.g., "!*.bak"
```

### Document-Level Filtering

From `QueryFilters.document_ids`:

- Post-filter in Python after ripgrep returns
- Or: Generate explicit file list and pass to ripgrep

---

## Ripgrep Availability Detection

```python
import shutil

class LiteralSearchService:
    @classmethod
    def is_available(cls) -> bool:
        return shutil.which("rg") is not None

    async def search(self, query: Query) -> list[SearchHit]:
        if not self.is_available():
            raise RipgrepNotFoundError(
                "ripgrep (rg) not found. Install via: brew install ripgrep / apt install ripgrep"
            )
        ...
```

---

## Testing Strategy

### Unit Tests (with fakes)

```python
class FakeRipgrepExecutor:
    def __init__(self, responses: dict[str, str]):
        self._responses = responses  # query -> JSON output

    async def run(self, args: list[str]) -> tuple[str, str, int]:
        # Return canned response based on args
```

### Integration Tests

Marked with `@pytest.mark.slow`:

- Create temp directory with test files
- Run actual ripgrep
- Verify SearchHit output

### Edge Cases to Test

- Binary file handling (ripgrep skips by default)
- Unicode in filenames/content
- Very long lines (ripgrep truncates at 10MB by default)
- No matches found (return empty list)
- Ripgrep not installed (graceful error)

---

## Future Considerations

### Hybrid Search

Ripgrep as pre-filter for semantic search:

- Use ripgrep to find candidate files quickly
- Run semantic search only on those chunks
- Fuse results for "best of both worlds"

### Lexical (Regex) Strategy

The same `RipgrepSearchService` could handle both `LITERAL` and `LEXICAL` strategies:

- `LITERAL`: Use `-F` flag
- `LEXICAL`: Use default regex mode

This could be a future enhancement to avoid duplicate code.
