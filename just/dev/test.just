set working-directory := "../.."
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Show test-selection recipes.
help:
    @just --list dev::test

# Run the unit gate, explicitly excluding service tests.
unit *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest -m "not service" {{ ARGS }}

# Run deterministic service tests against real local services.
service *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest --override-ini "addopts=--durations=10 --showlocals -ra --capture=sys" -m service {{ ARGS }}

# Run every collected test, removing the project default marker exclusion.
all *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest --override-ini "addopts=--durations=10 --showlocals -ra --capture=sys" {{ ARGS }}

# Run the unit gate with terminal coverage.
coverage *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest -m "not service" --cov=src/vaultspec_a2a --cov-report=term-missing {{ ARGS }}

# Collect the unit gate without executing tests.
collect-unit *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest --collect-only -m "not service" {{ ARGS }}

# Collect the service gate without executing tests.
collect-service *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest --override-ini "addopts=--durations=10 --showlocals -ra --capture=sys" --collect-only -m service {{ ARGS }}

# Collect every test without the project default marker exclusion.
collect-all *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest --override-ini "addopts=--durations=10 --showlocals -ra --capture=sys" --collect-only {{ ARGS }}
