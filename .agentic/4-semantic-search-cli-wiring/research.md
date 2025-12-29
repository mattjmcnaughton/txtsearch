# Research Report: CLI Integration with SemanticSearchService and IndexingService

## 1. Current CLI Implementation

### Structure (src/txtsearch/cli.py)
- **Framework**: Typer (Python's modern CLI framework)
- **Configuration**: Structured with app-level help text and markdown rendering
- **Pattern**: Command functions decorated with `@app.command()`

### Existing Commands

#### Index Command (IMPLEMENTED)
```python
@app.command()
def index(
    directory: str = typer.Argument(...),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o"),
    file_pattern: Optional[str] = typer.Option("*.{py,js,ts,md,txt,json,yaml,yml}"),
    exclude: Optional[str] = typer.Option(None, "--exclude", "-e"),
) -> None:
```

**Key Implementation Details**:
- Takes `directory` as positional argument (required)
- Optional `output_dir` defaults to `.txtsearch/` in target directory
- Parses file patterns using `parse_file_pattern()` factory helper
- Uses `asyncio.run()` to execute async operation
- Returns results via `typer.echo()`

**Error Handling Pattern**:
```python
if not target_dir.exists():
    logger.error("directory_not_found", directory=str(target_dir))
    raise typer.Exit(1)
```

**Async Pattern Used**:
```python
async def run_indexing() -> IndexingResult:
    async with create_indexing_service(...) as service:
        return await service.index_directory(target_dir)

result = asyncio.run(run_indexing())
```

#### Search Command (TODO - NEEDS IMPLEMENTATION)
```python
@app.command()
def search(
    query: str = typer.Argument(...),
    directory: Optional[str] = typer.Option(None, "--directory", "-d"),
    strategy: SearchStrategy = typer.Option(SearchStrategy.SEMANTIC, "--strategy", "-s"),
    limit: int = typer.Option(10, "--limit", "-n"),
    context: int = typer.Option(0, "--context", "-C"),
) -> None:
```

**Current Status**: Placeholder implementation with logging setup ready.

### Structlog Configuration
```python
structlog.configure(...)
logger = structlog.get_logger(__name__)
```

**Usage Pattern in CLI**:
- `logger.info("starting_search", query=query, strategy=strategy.value, ...)`
- `logger.error("index_not_found", index_dir=str(index_dir))`

---

## 2. Services Available

### SemanticSearchService

#### Constructor & Dependencies
```python
def __init__(
    self,
    vector_store: VectorStore,
    metadata_store: MetadataStore,
    logger: structlog.stdlib.BoundLogger | None = None,
) -> None:
```

#### Async Context Manager Support
```python
async def __aenter__(self) -> "SemanticSearchService":
    return self

async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
    await self.close()
```

#### Key Methods
- **`async initialize()`**: Initializes both metadata and vector stores
- **`async search(query: Query) -> list[SearchHit]`**: Main search method
  - Takes a `Query` object with text, strategy, top_k, filters
  - Returns sorted list of `SearchHit` objects
  - Raises `ValueError` if query text is empty

### IndexingService

#### Constructor & Dependencies
```python
def __init__(
    self,
    file_walker: FileWalker,
    metadata_store: MetadataStore,
    vector_store: VectorStore,
    chunker: Chunker,
    logger: structlog.stdlib.BoundLogger | None = None,
) -> None:
```

#### Key Method
- **`async index_directory(directory: Path) -> IndexingResult`**
  - Returns `IndexingResult(files_processed, files_skipped, chunks_created, errors)`

---

## 3. Factory Module (src/txtsearch/services/factory.py)

### Production Factories

#### create_indexing_service()
```python
def create_indexing_service(
    output_dir: Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    collection_name: str = "chunks",
) -> IndexingService:
```

#### create_semantic_search_service()
```python
def create_semantic_search_service(
    index_dir: Path,
    collection_name: str = "chunks",
) -> SemanticSearchService:
```

**Returns**: Fully wired `SemanticSearchService` for search
- Reads from existing index at `index_dir`
- Expects `meta.db` and `semantic/` subdirectory to exist

### Helper Function

#### parse_file_pattern()
```python
def parse_file_pattern(pattern: str) -> list[str]:
    # "*.{py,js,ts}" -> ["*.py", "*.js", "*.ts"]
```

---

## 4. Models

### Query Model
**Location**: `src/txtsearch/models/query.py`

```python
class Query(RecordModel):
    query_id: str = Field(default_factory=lambda: str(uuid4()))
    text: str  # Validated non-empty
    strategy: SearchStrategy
    top_k: int = Field(default=10, gt=0)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    include_snippets: bool = True
    include_highlights: bool = False
```

### SearchHit Model
**Location**: `src/txtsearch/models/hit.py`

```python
class SearchHit(RecordModel):
    hit_id: str
    query_id: str
    document_id: str
    chunk_id: str | None = None
    rank: int = Field(ge=0)
    score: float | None = Field(default=None)
    strategy: SearchStrategy
    snippet: str | None = None
    highlights: list[Highlight] | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
```

---

## 5. Existing Patterns

### Async CLI Pattern (Follow Index Command)
```python
async def run_search() -> list[SearchHit]:
    async with create_semantic_search_service(index_dir=index_dir) as service:
        query = Query(
            text=query_text,
            strategy=model_strategy,
            top_k=limit,
        )
        return await service.search(query)

results = asyncio.run(run_search())
```

### Enum Mismatch to Resolve
**CLI has its own SearchStrategy enum** (In cli.py)
**Models have different one** (In models/enums.py)

**Conversion needed**:
```python
from txtsearch.models.enums import SearchStrategy as ModelSearchStrategy
model_strategy = ModelSearchStrategy(strategy.value)
```

---

## 6. Test Patterns

### Fake Dependencies Pattern
```python
class FakeVectorStore:
    def __init__(self) -> None:
        self.initialized = False
        self.query_results: list[VectorQueryResult] = []
        # ...

    async def initialize(self) -> None:
        self.initialized = True

    async def query(...) -> list[VectorQueryResult]:
        # ...
```

### Test Class Organization
```python
class TestSemanticSearchServiceInitialization:
    # ...

class TestSemanticSearchServiceHappyPath:
    # ...
```

---

## 7. Best Practices from CLAUDE.md

- **Absolute imports only**
- **Functions 10-40 lines**
- **Comprehensive type annotations**
- **Services performing I/O should be async**
- **Use async context managers for resource cleanup**
- **Use `structlog` everywhere with snake_case event names**
- **Allow exceptions to bubble up**

---

## 8. Recommended Implementation Strategy

### Steps:

1. **Create Query object from CLI arguments**
2. **Load service and execute search using async context manager**
3. **Format and output results (human-readable and JSON)**
4. **Handle error scenarios gracefully**

### Key Imports
```python
from txtsearch.services.factory import create_semantic_search_service
from txtsearch.models.query import Query
from txtsearch.models.enums import SearchStrategy as ModelSearchStrategy
from txtsearch.models.hit import SearchHit
```

### Error Scenarios to Handle
1. Index directory not found
2. Empty query text
3. Invalid strategy enum
4. Database/vector store errors

---

## 9. Key Files Summary

| File | Purpose |
|------|---------|
| `src/txtsearch/cli.py` | CLI commands |
| `src/txtsearch/services/factory.py` | Service wiring |
| `src/txtsearch/services/semantic_search.py` | Search orchestration |
| `src/txtsearch/services/index.py` | Indexing orchestration |
| `src/txtsearch/models/query.py` | Search input |
| `src/txtsearch/models/hit.py` | Search output |
| `src/txtsearch/models/enums.py` | Enums |
