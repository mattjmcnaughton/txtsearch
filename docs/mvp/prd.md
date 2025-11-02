# txtsearch MVP PRD

## Product Overview
txtsearch is a local-only text search utility distributed through `uvx` that combines fast indexing, multi-strategy querying (literal, lexical, semantic, agentic), and ergonomic outputs for technical users. The MVP delivers a single CLI and mirrored local APIs (REST + MCP) so engineers can index arbitrary text collections and run high-signal searches without relying on remote services. Success is measured by engineers adopting txtsearch as their default “all-in-one” text search tool and completing common search workflows without leaving their terminal.

## Target Users & Jobs
- Technical practitioners who already use tools like DuckDB, Chroma, and CLI-oriented workflows.
- Jobs:
  - Quickly build an index over local project directories or datasets.
  - Execute different search strategies (keyword, fuzzy, semantic, agentic) and compare results.
  - Pipe structured results into other Unix-friendly tools or scripts.
  - Start local services (REST, MCP) that reuse the same indexes for programmatic or agent-driven searches.

## Goals
- Provide a single `uvx txtsearch ...` interface that covers indexing, searching, serving, and version reporting.
- Support any text-readable file discoverable via `cat`, with sensible defaults for code and documentation extensions.
- Ensure search results are available in both human-readable console output and structured formats for downstream tooling.
- Keep everything local by default, with no implicit network calls; must be agnostic to the specific LLM being used.

## In Scope (MVP)
- CLI commands: `index`, `search`, `serve`, `mcp`, `version`, matching the scaffolding in `src/txtsearch/cli.py`.
- Mirrored REST (FastAPI) and MCP (FastMCP) endpoints covering `index` and `search`.
- Index storage options: persisted on disk by default (`~/.txtsearch`) with optional in-memory mode exposed through API and MCP servers.
- Strategy-aware search pipeline selecting literal/lexical/semantic/agentic backends.
- Output modes: console-friendly table with optional context lines, and JSON (or similar) for scripting.
- Dependency use: Sqlite3 + SqlModel for metadata, DuckDB/ChromaDB as storage/embedding engines, Typer CLI, Pydantic + LiteLLM/pydantic-ai for agentic flows.

## Out of Scope (Non-Goals)
- Remote indexing or cloud-hosted services.
- Performance tuning beyond basic responsiveness; no indexing sharding or distributed execution.
- Plugin system, custom analyzers, or language packs.
- Configuration files or user-defined profiles (not needed until post-MVP).
- Telemetry or analytics beyond local logs.

## User Workflows
1. **Index a directory**
   `uvx txtsearch index ./project --output-dir ./project/.txtsearch --file-pattern "*.{py,md}" --exclude "node_modules"`
   Tool validates directory, logs start/end, creates or refreshes the on-disk index.
2. **Search indexed content**
   `uvx txtsearch search "init database" --strategy semantic --limit 10 --context 3 --ingest-if-missing`
   Reads `.txtsearch` (or supplied index path), optionally re-runs indexing when the flag is set, runs strategy-specific search, prints formatted hits, and optionally emits JSON (`--output json`).
3. **Start REST API**
   `uvx txtsearch serve --port 8000 --directory ./project --memory`
   Serves FastAPI endpoints `/index` and `/search` mirroring CLI parameters; local-only binding by default, with optional in-memory stores.
4. **Start MCP server**
   `uvx txtsearch mcp --directory ./project --memory`
   Exposes the same operations for agent frameworks via FastMCP, leveraging LiteLLM for any LLM calls and supporting ephemeral in-memory indexes.
5. **Check version**
   `uvx txtsearch version` outputs semantic version and embedded dependency versions when helpful.

## Functional Requirements
### CLI Experience
- Typer-powered CLI with rich help strings and examples (already scaffolded).
- Consistent options across commands (`--directory`, `--output-dir`, `--strategy`, `--limit`, `--context`).
- Helpful error handling (missing directory/index, unsupported strategy, read failures) with `structlog` events.
- Support for glob patterns and exclusions; defaults cover common code/text extensions.

### Index Command
- Walk target directory, honor include/exclude patterns, and skip binaries.
- Build embeddings/metadata using Sqlite3/SqlModel + DuckDB/ChromaDB.
- Store index metadata (schema version, timestamp, strategies available) inside `.txtsearch`.
- Chunk text for embeddings; Sqlite tracks relationships of documents to chunks and chunk metadata.
- Emit summary stats (files indexed, tokens processed, elapsed time).

### Search Command
- Accept literal | lexical | semantic | agentic strategies (`SearchStrategy` enum).
- Provide optional `--context` lines (default 0) and `--limit` results (default 10).
- Offer `--ingest-if-missing` to trigger indexing when no index is available for the target directory.
- Output:
  - Human-readable mode: file path, line number, snippet with highlighting, optional context.
  - Structured mode: JSON array with metadata (score, strategy, index version, timestamps).
- Provide exit codes (`0` success, `1` errors, `2` no results if helpful).
- Agentic strategy routes through LiteLLM + pydantic-ai, respecting local-only policy; hard-fail with clear messaging when models or endpoints are unavailable.

### Serve Command (REST API)
- FastAPI app exposing:
  - `POST /index` with payload mirroring CLI options; responds with stats.
  - `POST /search` with JSON payload; returns JSON results identical to CLI structured output.
- Supports `--memory` flag to operate entirely in-memory for short-lived sessions.
- Defaults to `127.0.0.1` binding; explicit `--host` to change.
- Logging via structlog; graceful shutdown; health endpoint optional.

### MCP Command
- FastMCP server exposing `index` and `search` tools.
- Supports `--memory` flag mirroring REST behavior.
- Reuse same business logic layer as CLI/REST; ensure consistent validation and output schema.
- Document how agent frameworks should invoke commands.

### Shared Components
- Core indexing/search services reused across CLI, REST, MCP to avoid divergence.
- Result schema defined with Pydantic models.
- All disk paths resolved relative to provided directory; guard against traversing outside allowed tree.
- No network calls without explicit user opt-in (e.g., providing remote model URL).

## Data & Architecture
- Data sources: any text file accessible via filesystem (`cat` friendly). Binary detection/use heuristics to skip.
- Index persisted inside `.txtsearch` by default, with subdirectories for metadata, embeddings, caches.
- Use Sqlite3/SqlModel for metadata, DuckDB for analytical queries, ChromaDB for vector storage.
- API and MCP commands may operate in-memory using the same stores; CLI remains on-disk.
- Config file support deferred; expose CLI/API flags for critical settings.

## UX & Interaction Details
- CLI output should be pipe-friendly (no color by default; consider `--color/--no-color` if needed).
- Provide `--output json` (structured) and `--output text` (default) switches.
- Include `--verbose` flag to surface structlog events; default logs to stderr, results to stdout to play well with Unix pipelines.
- Document example pipelines (e.g., piping JSON to `jq`).

## Performance & Reliability
- Prioritize correctness over speed; no strict latency targets yet.
- Must handle medium-sized codebases (tens of thousands of files) without crashing.
- Graceful handling of partially built indexes; atomic writes or temp directories to avoid corruption.
- Provide clear messaging when strategies are unavailable (e.g., missing embeddings).

## Integrations & Dependencies
- Tight integration with Unix pipelines; avoid hidden state outside filesystem.
- Ensure uv/uvx distribution is smooth (document install steps).
- Dependencies: Typer, structlog, Sqlite3, SqlModel, DuckDB, ChromaDB, FastAPI, FastMCP, Pydantic, LiteLLM, pydantic-ai; pin minimum versions compatible with uv.
- Expose simple Python API for embedding into other scripts via REST/MCP (no direct package import MVP).

## Privacy & Licensing
- Local-only by default; no telemetry or remote calls unless user explicitly provides credentials/flags.
- Follow open-source licensing (e.g., Apache 2.0); ensure third-party deps compatible.
- Contribution model: standard OSS workflow (issues, PRs); document in README post-MVP.

## Open Questions
- What specific JSON schema do downstream tools expect for search results (field names, ordering)?
- Which embedding provider/model should we use by default when none is configured locally?

## Future Work
- Support AI summarization of text during indexing.
- Utilize docling (or similar) to support PDF and other rich-document search.
- Add incremental indexing or file-watching to reduce repeated full reindexing.
