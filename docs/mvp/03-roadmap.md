# txtsearch MVP Roadmap

## Semantic Slice First
- Define shared Pydantic models for documents, chunks, and search results.
- Implement semantic indexing service with Sqlite metadata and Chroma embeddings.
- Wire CLI `index` and `search` commands to run semantic strategy end-to-end with text/JSON outputs.

## Expand Strategies
- Add lexical and literal indexing/search paths leveraging existing service contracts.
- Introduce agentic search orchestration via LiteLLM and pydantic-ai.
- Enhance CLI UX for strategy selection, ingest-on-miss, context controls, and errors.

## Persistence & Ops Hardening
- Finalize on-disk storage layout, temp-swap reindexing, and in-memory modes.
- Add dependency checks, capability detection, and structlog instrumentation.
- Build test doubles and unit coverage for services and storage utilities.

## Interfaces Beyond CLI
- Ship FastAPI adapter mirroring CLI semantics with shared models and wiring.
- Ship FastMCP server reusing the same service layer and schemas.
- Handle process lifecycle concerns and provide usage examples for both adapters.

## Polish & Packaging
- Finish version reporting, wiring factories, and CLI documentation.
- Run integration/E2E validation across strategies and interfaces; lock JSON schema decisions.
- Prepare uvx distribution details and supporting docs for MVP release.
- Set-up semantic release.
