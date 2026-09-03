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

# The durable-replay proof lives in the service tier, which the default gate
# excludes, so a default run never executed it and a bare service run could
# report green while it skipped. This tier declares the dashboard engine: it
# either EXECUTES the proof or fails naming the missing binary and how to supply
# it. A pass here is evidence; there is no skip-shaped green.
#
# Prove durable replay and lost-ack recovery across repositories (never skips).
cross-repo *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest --override-ini "addopts=--durations=10 --showlocals -ra --capture=sys" --require-prerequisite=dashboard-engine src/vaultspec_a2a/service_tests/test_engine_broker_lost_ack_live.py {{ ARGS }}

# These need the Codex and Claude CLIs on PATH and no credential whatsoever, so
# a certification job can provision them. Selected by explicit node id and run
# strict on purpose: a renamed or deleted gate is a usage error, and a gate that
# skips while its CLI is installed fails the run. Credential-gated provider
# lanes are deliberately NOT here - they need owner-supplied secrets.
#
# Run the provider gates whose prerequisite is an installable CLI (never skips).
provider-gates *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest --override-ini "addopts=--durations=10 --showlocals -ra --capture=sys" --require-prerequisite=codex-cli --require-prerequisite=claude-cli --require-prerequisite=mcp-streamable-http src/vaultspec_a2a/providers/tests/test_codex_chat_model.py::test_classify_provider_command_resolves_codex src/vaultspec_a2a/providers/tests/test_codex_chat_model.py::test_codex_readiness_ready_when_installed src/vaultspec_a2a/providers/tests/test_codex_config_home.py::TestCodexEntrypointAcceptsEmittedMcpConfig::test_codex_mcp_list_accepts_the_built_config_home src/vaultspec_a2a/providers/tests/test_acp_project_mcp.py::TestAcpEntrypointAcceptsProjectedMcpConfig::test_claude_mcp_list_accepts_the_projected_config {{ ARGS }}

# Run every collected test, removing the project default marker exclusion.
all *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling pytest --override-ini "addopts=--durations=10 --showlocals -ra --capture=sys" {{ ARGS }}

# Prove gateway and worker telemetry start in a base-only installation.
#
# Runs in an isolated environment holding ONLY the default dependencies, so the
# optional OTLP exporter is genuinely absent rather than merely unimported - the
# condition that once aborted startup and that the main suite, which has the
# exporter installed, cannot reproduce. Installed editable on purpose: the wheel
# excludes `**/tests`, so the probe has no installed-module form to invoke.
clean-base:
    uv run --isolated --no-project --with-editable . python -m vaultspec_a2a.telemetry.tests.probe_clean_base

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
