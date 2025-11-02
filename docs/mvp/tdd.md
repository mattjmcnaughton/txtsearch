# txtsearch MVP Technical Design

## 1. Architectural Overview
- txtsearch is a local-first CLI with optional REST and MCP servers that reuse the same core services.
- No background daemon: users invoke `index` to build or refresh state, and `search`/`serve`/`mcp` consume that state.
- Core services are organized into three layers:
  - **Interface layer**: Typer CLI commands plus FastAPI and FastMCP adapters.
  - **Application layer**: indexing and search services orchestrating storage and search strategy selection.
  - **Data layer**: Sqlite (metadata), DuckDB (lexical FTS), ChromaDB (semantic vectors), external LLM/agent endpoints via LiteLLM + pydantic-ai.
- All layers share the same core logic; CLI persists indexes to disk while API/MCP interfaces may request ephemeral in-memory stores for their processes.

## 2. Component Responsibilities
### 2.1 CLI Commands (`txtsearch/commands/*.py`)
- `index`: orchestrates indexing pipeline and always writes a persisted index (default `~/.txtsearch` or provided `--output-dir`).
- `search`: selects strategy (literal, lexical, semantic, agentic), executes via search service, formats output (text/JSON), and can trigger indexing via `--ingest-if-missing`.
- `serve`: runs FastAPI app exposing `/index` and `/search`, bridging to the same services; supports `--memory` to use ephemeral stores.
- `mcp`: hosts FastMCP tools wrapping index/search operations; supports `--memory` mirroring REST behavior.
- `version`: reports package version (and optionally dependency versions).

### 2.2 Indexing Service
- Walks directories honoring include/exclude globs, filters out binary files.
- Collects file metadata (path, size, mtime, hash) into Sqlite/SqlModel.
- Ingests textual content:
  - Literal search: no preprocessing; ripgrep will read files directly.
  - Lexical search: loads content into DuckDB FTS tables.
  - Semantic search: generates or refreshes embeddings in ChromaDB.
- Supports modes:
  - **Persisted**: default path `~/.txtsearch` (or user-specified directory), storing Sqlite, DuckDB, and Chroma artifacts; used by CLI flows.
  - **Ephemeral**: keep handles in memory (e.g., `:memory:` connections) for API/MCP sessions launched with `--memory`; lifetime tied to server process.
- Handles full reindex only (no incremental updates). Existing data stores are replaced atomically (write to temp path then swap).
- Records metadata (schema version, timestamp, enabled strategies) for consumers.

### 2.3 Search Service
- Accepts query, strategy, and limits; reads index metadata to confirm available stores.
- Literal strategy: shells out to `rg`/ripgrep with safe command construction, parses results into common schema.
- Lexical strategy: executes DuckDB FTS query, scores/ranks results, adds context lines by re-reading files as needed.
- Semantic strategy: queries ChromaDB embeddings; if embeddings absent, returns strategy unavailable error.
- Agentic strategy:
  - Uses LiteLLM to call user-configured `ollama/qwen3:1.7b` (default recommended).
  - pydantic-ai orchestration performs retrieval-augmented reasoning, possibly chaining other strategies.
  - Must detect missing ollama/model and hard-fail with actionable error message.
- When `--ingest-if-missing` is provided, the service invokes the indexing pipeline before executing the search if no stored index exists.
- Normalizes responses into unified result objects (Pydantic models) containing file path, line span, snippet, score, strategy, index metadata, timestamps.
- Output renderers:
  - Text mode (default): table-like format with optional highlighted context lines.
  - JSON mode: structured list for scripting (exact schema TBD).

### 2.4 REST API (FastAPI in `txtsearch/api/`)
- Endpoints:
  - `POST /index`: accepts same parameters as CLI, triggers indexing task synchronously (consider background task queue later).
  - `POST /search`: accepts query payload mirroring CLI, returns JSON results.
- Runs async event loop; uses shared services; ensures thread-safe connections (per-request session management).
- Binds to `127.0.0.1` by default; host override allowed.

### 2.5 MCP Server (FastMCP in `txtsearch/mcp/`)
- Exposes `index` and `search` tools mirroring CLI/API semantics.
- Shares Pydantic request/response models with other interfaces.
- Designed for local agent frameworks; inherits local-only guarantees.

### 2.6 Services Layer (`txtsearch/services/`)
- Houses business logic for indexing, search strategies, and shared utilities.
- Services are instantiated per request (CLI/API/MCP) and injected where needed to support testability.
- Each service receives its dependent stores/clients (Sqlite session, DuckDB handle, Chroma collection, LiteLLM client, etc.) via constructor injection or provider functions.
- Logging responsibility lives inside services (structlog) while orchestration stays in commands/API endpoints.

### 2.7 Data Models (`txtsearch/models/`)
- Pydantic models define domain entities (file metadata, chunk records, search hits, strategy configs).
- Separate submodules for shared models vs. interface-specific request/response schemas.
- Models enforce validation and provide `.model_dump()` for structured outputs, guaranteeing consistent JSON across CLI/API/MCP.

## 3. Data Storage & Layout
```
~/.txtsearch/
  <dataset-id>/
    meta.db          # Sqlite (SqlModel) for file metadata, schema history
    lexical.duckdb   # DuckDB FTS tables
    semantic/        # ChromaDB collection files
    config.json      # (optional) stored settings, version info
```
- In-memory mode instantiates equivalent stores with `:memory:` URIs or temporary directories per API/MCP session.
- Schema versioning stored in Sqlite; migrations handled via Alembic-like scripts or SqlModel migration helpers.
- Reindex pipeline writes to a temporary sibling directory (e.g., `~/.txtsearch.tmp/`) and swaps to avoid corruption.

## 4. Search Strategy Details
- **Literal**: Wrap ripgrep via subprocess, restricted to indexed directory; options for case sensitivity, globs, context lines. Falls back to reading from filesystem even in persisted mode.
- **Lexical**: DuckDB FTS on normalized documents; maintain table of `(doc_id, content, tokens)` plus snippet extraction helper.
- **Semantic**: ChromaDB collection keyed by file + chunk ID; embeddings generated via configured model (default remote embedding provider TBD). Track embedding model name/version in metadata.
- **Agentic**: pydantic-ai orchestrates multi-step reasoning, potentially combining lexical/semantic retrieval underneath. All outbound LLM calls routed through LiteLLM; environment variables configure endpoints.

## 5. Concurrency & Async Model
- CLI commands remain synchronous but leverage asyncio internally where beneficial (e.g., concurrent file reads, embedding generation). Consider `asyncio.run` wrappers.
- REST API uses FastAPI’s async stack; ensure data layer components (DuckDB/Sqlite/Chroma) are accessed via async-compatible adapters or run in thread pool executors.
- MCP server follows async design; reuse same async service functions.
- Indexing may use multiprocessing/thread pools for CPU-bound steps (hashing, embedding generation) while respecting local resource limits.

## 6. External Dependencies & Configuration
- Sqlite3 + SqlModel, DuckDB, ChromaDB, Typer, structlog, FastAPI, FastMCP, Pydantic, LiteLLM, pydantic-ai.
- ripgrep must be installed; commands detect absence and hard-fail with guidance instead of bundling binaries.
- Ollama required for default agentic model (`ollama/qwen3:1.7b`); likewise, fail fast with actionable messaging when not detected.
- Apply the same pattern to any other external executables or services—surface a clear error and exit rather than attempting inline installation.
- Embedding model chosen via environment variables or CLI flags; default points to a remote provider (decision pending).
- All network calls require explicit user configuration; default behavior stays offline.

## 10. Open Decisions / Risks
- Final JSON schema for structured search output (fields, nesting, ordering).
- Default embedding provider/model that balances local vs. remote requirements.
- Async integration with DuckDB/Chroma (may require thread pools or wrappers).
- Packaging strategy for ripgrep dependency (startup check vs. bundling).
