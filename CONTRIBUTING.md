# Contributing to txtsearch

## Development Setup

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [just](https://github.com/casey/just) command runner

### Installation
```bash
just install          # Install all dependencies
```

## Development Workflow

### Code Quality
Run the full CI pipeline before committing:
```bash
just ci               # Run all linting, formatting, typechecking, and tests
```

Individual commands:
```bash
just lint             # Lint with ruff
just lint-fix         # Auto-fix linting issues
just format           # Format code with ruff
just format-check     # Check formatting without fixing
just typecheck        # Run type checking with ty
just test             # Run tests with pytest
```

### Commit Message Format

This project uses [Conventional Commits](https://www.conventionalcommits.org/) for automated releases:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

#### Version Impact
- `fix:` → PATCH version (0.0.X)
- `feat:` → MINOR version (0.X.0)
- `BREAKING CHANGE:` or `!` → MAJOR version (X.0.0)

#### Other Types
`docs:`, `style:`, `refactor:`, `test:`, `chore:`, `ci:` → No version bump

#### Examples
- `feat: add semantic search functionality`
- `fix: handle empty directories correctly`
- `feat!: change CLI command structure` (breaking change)
- `docs: update installation instructions`
- `test: add integration tests for MCP server`

## Release Process

Releases are fully automated:
1. Merge changes to `main` branch
2. CI pipeline runs automatically
3. If CI passes, semantic-release analyzes commits
4. Version is bumped automatically in `pyproject.toml`
5. Changelog is generated
6. Git tag and GitHub release are created

## Code Style

- Use absolute imports in Python
- Follow Ruff configuration (120 char line length, Python 3.11 target)
- No emojis in code, comments, or CLI output
- Use `structlog` for logging with snake_case event names
- Follow existing patterns and conventions
