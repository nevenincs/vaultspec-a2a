set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Show hook validation and maintenance recipes.
help:
    @just --list dev::hooks

# Resolve the locked development environment used by hooks.
bootstrap:
    uv venv .venv --allow-existing
    uv sync --locked --no-default-groups --group dev

# Install the repository-managed, path-agnostic prek hook.
install: bootstrap
    uv run --no-default-groups --group dev python -m vaultspec_a2a.control.hooks install

# Remove the repository-managed prek hook.
remove:
    uv run --no-default-groups --group dev python -m vaultspec_a2a.control.hooks remove

# Run the current hook pipeline outside a commit attempt.
run *ARGS:
    uv run --no-sync --frozen --no-default-groups --group dev prek run {{ ARGS }}

# Apply code repairs explicitly, then rerun the current hook pipeline.
repair *ARGS:
    just dev code repair
    just dev hooks run {{ ARGS }}
