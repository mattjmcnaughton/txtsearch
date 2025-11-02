# Agent Guidelines

This document guides AI agents and contributors.

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

## Testing Strategy
- Follow the pyramid: unit > integration > e2e.
- Unit tests (`tests/unit/...`) use DI with in-memory or fake dependencies and run quickly—never mark them `slow` or `external`.
- Integration tests (`tests/integration/...`) exercise component interactions or real external systems; mark with `@pytest.mark.slow` and/or `@pytest.mark.external` as needed.
- End-to-end tests (`tests/e2e/...`) cover core workflows spanning commands/services/adapters.
- Reuse fixtures that spin up in-memory databases, fake LiteLLM clients, or temp directories to keep tests deterministic.
