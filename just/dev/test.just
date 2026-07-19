set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Show test-selection recipes.
help:
    @just --list dev::test

# Run the repository's current default non-service test selection.
unit *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest {{ ARGS }}

# Run deterministic service tests against real local services.
service *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest --override-ini "addopts=--durations=10 --showlocals -ra --capture=sys" -m service {{ ARGS }}

# Run the current project-wide default selection.
all *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest {{ ARGS }}

# Run the current default selection with terminal coverage.
coverage *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest --cov=src/vaultspec_a2a --cov-report=term-missing {{ ARGS }}

# Collect the current default selection without executing tests.
collect *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest --collect-only {{ ARGS }}
