# txtsearch MVP Tickets

## Semantic Slice First
- title: `feat: establish shared search models`
  description: Define Pydantic models representing documents, chunks, queries, and search hits, including schema version metadata. Capture relationships between files and chunks so all interfaces can reuse the same structures. Provide helper serialization utilities and ensure type coverage aligns with planned storage backends.
  labels: `mvp`, `01-epic-semantic-slice-first`
- title: `feat: build semantic indexing service`
  description: Implement an indexing service that walks directories, records file metadata in Sqlite/SqlModel, and writes embeddings into Chroma. Handle chunking, hashing, and schema version stamping so subsequent searches know which strategies are available. Add structlog events for key milestones and expose a clean API for callers to trigger indexing.
  labels: `mvp`, `01-epic-semantic-slice-first`
- title: `feat: implement semantic search service`
  description: Query Chroma for nearest neighbors, hydrate results with file metadata, and rank them for consumption by higher layers. Normalize response objects using the shared models, including confidence scores, strategy metadata, and optional context snippets. Surface actionable errors when embeddings are missing or Chroma connectivity fails.
  labels: `mvp`, `01-epic-semantic-slice-first`
- title: `feat: wire CLI index/search semantic flow`
  description: Connect Typer commands to the new services so `uvx txtsearch index` and `uvx txtsearch search --strategy semantic` run end-to-end. Produce both human-readable and JSON outputs using shared renderers, and ensure logging adheres to structlog conventions. Add basic error handling for missing directories, indexes, or embeddings.
  labels: `mvp`, `01-epic-semantic-slice-first`

## Expand Strategies
- title: `feat: add lexical strategy with DuckDB`
  description: Extend the indexing service to populate DuckDB FTS tables and wire a lexical search path that produces ranked matches. Support context line extraction, scoring, and response normalization via the shared models. Confirm the CLI can toggle the strategy and that errors guide users when DuckDB artifacts are missing.
  labels: `mvp`, `02-epic-expand-strategies`
- title: `feat: integrate literal ripgrep strategy`
  description: Shell out to ripgrep with safe command construction to deliver fast literal searches, parsing output back into our result schema. Respect include and exclude patterns and apply context handling consistent with other strategies. Detect missing ripgrep binaries and return clear guidance without crashing the process.
  labels: `mvp`, `02-epic-expand-strategies`
- title: `feat: add agentic search orchestration`
  description: Implement an agentic strategy using LiteLLM and pydantic-ai that can invoke other strategies for retrieval. Handle configuration, environment variable wiring, and missing model scenarios with explicit error messages. Ensure responses conform to shared models and the CLI can select the agentic mode.
  labels: `mvp`, `02-epic-expand-strategies`
- title: `refactor: unify strategy registry`
  description: Centralize strategy discovery and configuration so CLI, REST, and MCP share a single registry for available search modes. Provide extension points for future strategies while enforcing validation of required dependencies. Update existing callers to use the registry instead of ad-hoc branching.
  labels: `mvp`, `02-epic-expand-strategies`

## Persistence & Ops Hardening
- title: `feat: finalize persisted index layout`
  description: Implement the final on-disk structure under `~/.txtsearch`, including Sqlite metadata, DuckDB files, and Chroma artifacts. Add temp-directory swap logic to avoid corrupting existing indexes during reindexing. Record schema versions, timestamps, and available strategies so consumers can validate state before use.
  labels: `mvp`, `03-epic-persistence-ops-hardening`
- title: `feat: support in-memory stores`
  description: Provide constructors for ephemeral Sqlite, DuckDB, and Chroma instances that live only for the server process lifetime. Ensure the indexing and search services can detect and operate in memory mode without leaking resources. Add options to CLI, API, and MCP wiring to request in-memory execution and document limitations.
  labels: `mvp`, `03-epic-persistence-ops-hardening`
- title: `chore: add dependency and capability checks`
  description: Detect required executables and services—ripgrep, LiteLLM targets, and Ollama—and emit actionable errors if they are missing. Integrate checks into command startup and service initialization while keeping them fast. Provide structured log events that make troubleshooting straightforward for users.
  labels: `mvp`, `03-epic-persistence-ops-hardening`
- title: `chore: expand service unit coverage with fakes`
  description: Introduce lightweight fakes for storage layers and external clients so unit tests can cover indexing and search services thoroughly. Author unit tests that assert expected behaviors, error conditions, and logging output. Integrate the suite into CI to guard regressions as we add strategies.
  labels: `mvp`, `03-epic-persistence-ops-hardening`
- title: `refactor: add structlog instrumentation`
  description: Audit services and add structured logging for major milestones, errors, and performance-relevant metrics. Ensure events use consistent snake_case keys and include contextual information like strategy, directory, and timings. Validate via tests or snapshots that logs appear as expected.
  labels: `mvp`, `03-epic-persistence-ops-hardening`

## Interfaces Beyond CLI
- title: `feat: ship FastAPI adapter`
  description: Build a FastAPI app exposing POST `/index` and `/search` that reuse the shared models and service layer. Manage dependency injection for storage providers, handling both persisted and in-memory modes. Add request validation, error translation, and minimal documentation for curl usage.
  labels: `mvp`, `04-epic-interfaces-beyond-cli`
- title: `feat: ship FastMCP server`
  description: Implement a FastMCP server that registers `index` and `search` tools backed by the core services and models. Support configuration for in-memory operation and ensure tool metadata is documented for agent frameworks. Handle graceful shutdown and error propagation consistent with other interfaces.
  labels: `mvp`, `04-epic-interfaces-beyond-cli`
- title: `refactor: introduce wiring factory module`
  description: Create a dedicated module that assembles service dependencies—storage handles, strategy registry, and logging—for CLI, API, and MCP. Replace ad-hoc constructors with calls into this wiring layer so configuration stays centralized. Cover the module with tests to ensure each interface receives the correct dependencies.
  labels: `mvp`, `04-epic-interfaces-beyond-cli`
- title: `chore: document adapter usage & examples`
  description: Write documentation showing how to run the REST and MCP adapters, including sample requests and expected responses. Highlight configuration options, memory-mode caveats, and troubleshooting tips. Link docs from the main README or CLI help so users can find them easily.
  labels: `mvp`, `04-epic-interfaces-beyond-cli`

## Polish & Packaging
- title: `feat: finalize structured output schema`
  description: Decide on the JSON schema for search results, update renderers accordingly, and communicate the contract in docs and tests. Ensure all strategies populate the same fields and add integration tests to prevent regressions. Document any versioning or backward-compatibility plans for the schema.
  labels: `mvp`, `05-epic-polish-packaging`
- title: `feat: implement version command & metadata`
  description: Fill out the `version` CLI command to report package version plus notable dependency versions when useful. Hook into the wiring layer to provide consistent metadata across CLI, API, and MCP. Add tests that assert the command works even when optional dependencies are missing.
  labels: `mvp`, `05-epic-polish-packaging`
- title: `chore: prepare uvx distribution`
  description: Update packaging configuration, dependency pins, and entry points to support installation via `uvx`. Verify the published bundle runs the full CLI and document install steps in project docs. Address any packaging lint or CI checks required for release.
  labels: `mvp`, `05-epic-polish-packaging`
- title: `chore: set up release automation`
  description: Configure semantic-release or an equivalent workflow to manage version bumps, changelog generation, and tagging. Integrate the pipeline into CI and document the release process for contributors. Test the setup with a dry run to ensure it can publish the MVP without surprises.
  labels: `mvp`, `05-epic-polish-packaging`
