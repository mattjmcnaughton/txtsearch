# Agent Guidelines

This document guides AI agents and contributors.

## Dev Workflow
- The `justfile` documents the canonical commands for installing dependencies, running tests, linting, and other development tasks—prefer using these recipes to stay aligned with the project workflow.

## Repository Shape
- Place command-line entrypoints under `commands/`.
- Keep reusable domain models and Pydantic schemas in `models/`.
- Implement core business logic in `services/`; expose narrow function/class APIs.
- Host HTTP adapters under `api/` and MCP integrations under `mcp/`.
- Mirror this structure inside `tests/` (e.g., `tests/unit/services/test_index.py` for `services/index.py`).

## Dependency Injection
- Instantiate services in a dedicated wiring module or factory, then inject them into commands, API handlers, and MCP tools.
- Prefer constructor or explicit function parameter injection over globals to keep components swappable in tests.
- Provide lightweight test doubles (fakes, stubs) living alongside unit tests.

## Pydantic Usage
- Define all request/response contracts with Pydantic models; share them across CLI, REST, and MCP layers to guarantee shape parity.
- Keep domain entities (metadata records, search hits, strategy configs) as Pydantic models with rich type annotations.
- Rely on `.model_dump()` / `.model_validate()` to enforce structured outputs and inputs.

## Logging & Errors
- Use `structlog` everywhere; adopt snake_case event names and include structured context.
- Allow exceptions to bubble up so callers capture full stack traces; only catch errors when adding meaningful recovery or context.
- Keep logging side effects inside services; commands/adapters coordinate control flow.

## Code Style
- Absolute imports only; no runtime-conditional or guarded imports.
- Prefer functions/methods of roughly 10–40 lines that do one thing; extract helpers for clarity.
- Maintain comprehensive type annotations (inputs, outputs, attributes).
- Avoid trivial comments; reserve them for nuanced rationale or non-obvious decisions.
- We are using Python 3.12+ (i.e. there is no need for `from __future__ import annotations`)
- Do not use `__all__` declarations in modules; keep exports implicit.

## Async
- Services performing I/O (file reading, network calls, database) should be async.
- Use `asyncio.to_thread()` to wrap synchronous/blocking I/O operations (e.g., file reads, directory traversal).
- For database operations, use native async with `aiosqlite` and SQLAlchemy's async support:
  - Use `create_async_engine("sqlite+aiosqlite:///path.db")` for async engines.
  - Use `AsyncSession` from `sqlalchemy.ext.asyncio` for queries.
  - Schema creation requires `run_sync`: `await conn.run_sync(SQLModel.metadata.create_all)`.
  - Always call `await engine.dispose()` when done; without this, the process will hang.
- Async generators (`AsyncIterator`) are preferred for streaming results.
- Tests use pytest-asyncio with `asyncio_mode = "auto"` (no need for `@pytest.mark.asyncio`).
- Services managing resources (database connections, clients) should implement async context managers (`__aenter__`/`__aexit__`) to ensure cleanup on exit or exception.

## Database & SQLModel
- Keep SQLModel table classes (`table=True`) separate from Pydantic domain models in `models/tables.py`.
- Domain models are frozen/immutable; table models need mutability for ORM operations.
- Avoid field name `metadata` in table models (reserved by SQLAlchemy); use `extra` instead.
- Use SQLAlchemy's `JSON` type (`sa_type=JSON`) for dict fields to enable native serialization.
- Convert between domain and table models using `.model_dump()` / `.model_validate()`.
- SQLite does not preserve timezone info; restore UTC when reading datetime fields.

## Testing Strategy
- Follow the pyramid: unit > integration > e2e.
- Unit tests (`tests/unit/...`) use DI with in-memory or fake dependencies and run quickly—never mark them `slow` or `external`.
- Integration tests (`tests/integration/...`) exercise component interactions or real external systems; mark with `@pytest.mark.slow` and/or `@pytest.mark.external` as needed.
- End-to-end tests (`tests/e2e/...`) cover core workflows spanning commands/services/adapters.
- Reuse fixtures that spin up in-memory databases, fake LiteLLM clients, or temp directories to keep tests deterministic.
- Use class-based test organization; group related tests into classes (e.g., `TestFileWalkerPatternMatching`, `TestFileWalkerErrorHandling`).
