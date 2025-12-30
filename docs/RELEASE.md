# Release Process

This project uses [semantic-release](https://semantic-release.gitbook.io/) to automate version management and package releases.

## Initial Setup

### GitHub Actions Workflow

Create `.github/workflows/release.yml` with the following content:

```yaml
name: Release

on:
  push:
    branches:
      - main

permissions:
  contents: write
  issues: write
  pull-requests: write

jobs:
  release:
    name: Release
    runs-on: ubuntu-latest
    if: "!contains(github.event.head_commit.message, 'skip ci')"

    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
          persist-credentials: false

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 'lts/*'

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'

      - name: Install uv
        run: pip install uv

      - name: Install dependencies
        run: uv sync --group dev

      - name: Run linting
        run: uv run ruff check .

      - name: Check formatting
        run: uv run ruff format --check .

      - name: Type check
        run: uv run ty check

      - name: Run tests
        run: uv run pytest

      - name: Install semantic-release
        run: |
          npm install -g semantic-release@23 \
            @semantic-release/changelog@6 \
            @semantic-release/git@10 \
            @semantic-release/exec@6 \
            @semantic-release/github@10 \
            @semantic-release/commit-analyzer@11 \
            @semantic-release/release-notes-generator@12

      - name: Release
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: npx semantic-release
```

**Note**: This workflow file must be created manually or committed by a user with workflow permissions. The GitHub App used by automated tools does not have permission to create/modify workflow files.

## How It Works

The release process is fully automated through GitHub Actions:

1. **Commit Analysis**: When commits are pushed to `main`, semantic-release analyzes commit messages following the [Conventional Commits](https://www.conventionalcommits.org/) specification.

2. **Version Calculation**: Based on the commits since the last release:
   - `fix:` commits trigger a patch release (0.0.x)
   - `feat:` commits trigger a minor release (0.x.0)
   - `BREAKING CHANGE:` in commit body triggers a major release (x.0.0)

3. **Automated Updates**: semantic-release automatically:
   - Updates the version in `pyproject.toml`
   - Generates/updates `CHANGELOG.md`
   - Creates a git tag
   - Creates a GitHub release with release notes
   - Commits the changes back to `main`

## Commit Message Format

Follow the Conventional Commits format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types
- `feat`: New feature (triggers minor version bump)
- `fix`: Bug fix (triggers patch version bump)
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `test`: Test additions or changes
- `chore`: Build process or tooling changes
- `ci`: CI/CD changes

### Examples

```bash
# Patch release (0.1.0 -> 0.1.1)
git commit -m "fix: resolve indexing issue with empty files"

# Minor release (0.1.0 -> 0.2.0)
git commit -m "feat: add semantic search capability"

# Major release (0.1.0 -> 1.0.0)
git commit -m "feat: redesign search API

BREAKING CHANGE: search() now returns SearchResult objects instead of raw dicts"
```

## Publishing to PyPI (Manual Steps Required)

**IMPORTANT**: The GitHub Actions workflow does NOT automatically publish to PyPI. This requires manual intervention.

### Initial PyPI Setup

1. **Create PyPI Account**: If you haven't already, create accounts on:
   - [PyPI](https://pypi.org/) (production)
   - [TestPyPI](https://test.pypi.org/) (testing)

2. **Generate API Token**:
   - Go to PyPI Account Settings → API tokens
   - Create a token with scope limited to the `txtsearch` project
   - Save the token securely (it will only be shown once)

3. **Add Token to GitHub Secrets**:
   - Go to GitHub repository Settings → Secrets and variables → Actions
   - Create a new secret named `PYPI_API_TOKEN`
   - Paste your PyPI API token as the value

### Publishing a Release to PyPI

After semantic-release creates a GitHub release:

1. **Build the Package**:
   ```bash
   # Clone the repository at the release tag
   git checkout v<version>

   # Install build tools
   pip install build twine

   # Build the distribution
   python -m build
   ```

2. **Test the Build** (optional but recommended):
   ```bash
   # Upload to TestPyPI first
   python -m twine upload --repository testpypi dist/*

   # Test installation from TestPyPI
   pip install --index-url https://test.pypi.org/simple/ txtsearch
   ```

3. **Upload to PyPI**:
   ```bash
   python -m twine upload dist/*
   ```

   When prompted, use:
   - Username: `__token__`
   - Password: Your PyPI API token (starting with `pypi-`)

### Future Automation (Optional)

To fully automate PyPI publishing:

1. Add the `PYPI_API_TOKEN` secret to GitHub (see above)

2. Modify `.github/workflows/release.yml` to add a PyPI publish step after the semantic-release step:

```yaml
- name: Build package
  run: |
    pip install build
    python -m build

- name: Publish to PyPI
  if: steps.semantic.outputs.new_release_published == 'true'
  env:
    TWINE_USERNAME: __token__
    TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
  run: |
    pip install twine
    python -m twine upload dist/*
```

## Testing the Release Process

To test the release configuration without creating an actual release:

```bash
# Install semantic-release locally
npm install -g semantic-release @semantic-release/changelog @semantic-release/git @semantic-release/exec

# Run in dry-run mode
npx semantic-release --dry-run
```

This will show what version would be released and what changes would be made, without actually performing the release.

## Troubleshooting

### No Release Created

If no release is created when you expect one:

1. Check that commits follow the Conventional Commits format
2. Verify commits include types that trigger releases (`feat`, `fix`, or `BREAKING CHANGE`)
3. Check the GitHub Actions logs for errors

### Version Not Updated in pyproject.toml

The `.releaserc.json` configuration uses `sed` to update the version. Ensure:

1. The `pyproject.toml` file has a line matching `version = "X.Y.Z"`
2. The semantic-release workflow has write permissions to the repository

### Release Created But PyPI Upload Failed

Since PyPI publishing is manual by default:

1. Follow the "Publishing to PyPI" steps above
2. Or implement automated publishing by adding the PyPI token and modifying the workflow

## Additional Resources

- [Semantic Release Documentation](https://semantic-release.gitbook.io/)
- [Conventional Commits Specification](https://www.conventionalcommits.org/)
- [Python Packaging Guide](https://packaging.python.org/)
