set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Show code validation and repair recipes.
help:
    @just --list dev::code

# Run every read-only code-quality check.
check: lint format-check type dependencies workflows

# Check Python lint rules without changing files.
lint:
    uv run --no-sync --frozen --no-default-groups --group tooling ruff check .

# Check Python formatting without changing files.
format-check:
    uv run --no-sync --frozen --no-default-groups --group tooling ruff format --check .

# Run the project type checker without changing files.
type:
    uv run --no-sync --frozen --no-default-groups --group tooling ty check

# Check declared dependencies against imports and explicit runtime loaders.
dependencies:
    uv run --no-sync --frozen --no-default-groups --group tooling deptry .

# Validate GitHub Actions workflows with the project-pinned authority.
workflows:
    uv run --no-sync --frozen --no-default-groups --group tooling actionlint

# Apply configured lint fixes and formatting explicitly.
repair:
    uv run --no-sync --frozen --no-default-groups --group tooling ruff check --fix .
    uv run --no-sync --frozen --no-default-groups --group tooling ruff format .
