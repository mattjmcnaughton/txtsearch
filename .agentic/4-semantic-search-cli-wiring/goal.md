# Goal: Wire CLI index/search Semantic Flow

## Business Value

This ticket delivers **end-to-end user experience** for the core txtsearch product. Without this wiring, users cannot actually use the semantic search capabilities that have been built in previous tickets.

### User Stories

1. **As a developer**, I want to run `uvx txtsearch index ./my-codebase` so that my files are indexed with semantic embeddings for intelligent code search.

2. **As a developer**, I want to run `uvx txtsearch search --strategy semantic "how does authentication work"` so that I can find relevant files using natural language queries.

3. **As a developer**, I want to see both human-readable and JSON output formats so that I can integrate results into my workflow or scripts.

### Success Criteria

- [ ] `uvx txtsearch index <directory>` invokes the IndexingService and indexes all files
- [ ] `uvx txtsearch search --strategy semantic <query>` invokes SemanticSearchService and returns ranked results
- [ ] Human-readable output is clear and actionable
- [ ] JSON output (`--json` flag) provides structured data for programmatic use
- [ ] Error handling provides guidance when:
  - Directory doesn't exist
  - Index hasn't been created yet
  - Embeddings are missing
- [ ] Logging follows structlog conventions

### Dependencies

This ticket builds on:
- Issue #1: Shared search models (complete)
- Issue #2: Semantic indexing service (complete)
- Issue #3: Semantic search service (complete)

### Out of Scope

- Other search strategies (lexical, literal) - future tickets
- REST API / MCP interfaces - future tickets
- Persisted index layout finalization - future ticket
