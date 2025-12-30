# Goal: Lexical Search with DuckDB

## Business Value

**Enable users to search indexed codebases using keyword/term matching (lexical search) as an alternative to semantic search, ensuring they get fast, deterministic, BM25-ranked results when exact terminology matters more than conceptual similarity.**

## User Workflow (E2E Validation)

A user who has indexed their codebase can run:
```bash
txtsearch search --strategy lexical "authentication password"
```

And receive ranked search results showing documents that contain those specific terms, with:
- BM25 relevance scores (normalized to 0-1 range)
- Snippet previews showing matching context
- Fast query performance via DuckDB FTS indexes
- Clear error messages if the lexical index doesn't exist yet

## Feature Capabilities

The feature enables users to toggle between:
- **Semantic search** (`--strategy semantic`): Find conceptually similar content, even with different terminology
- **Lexical search** (`--strategy lexical`): Find exact term matches with traditional keyword search ranking

This completes the dual-strategy search capability, giving users the right tool for different search scenarios: semantic for exploratory/conceptual searches, lexical for finding specific function names, error messages, or technical terms.

## Core Requirements

1. Users can index codebases with DuckDB FTS tables populated alongside semantic embeddings
2. Users can search using `--strategy lexical` via the CLI
3. Results are ranked using BM25 scoring and normalized to 0-1 range
4. The search service mirrors the semantic search API (same `SearchHit` structure)
5. Missing DuckDB indexes produce actionable error messages guiding users to re-index
6. Performance is fast (< 1s for typical queries over moderate codebases)
