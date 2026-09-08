# ===========================================================================
#  vaultspec-a2a development harness
#
#  Every entry point is a FLAT HYPHENATED recipe named `<verb>-<thing>` -
#  `just check-type`, `just test-unit`, `just stack-dev-up`. There is no
#  `target` argument anywhere, and no `mod` submodule tree: the thing a recipe
#  acts on is part of its name, so `just --list` is the complete surface and
#  tab completion reaches every one of them. Run `just` for the annotated
#  recipe list, grouped by CONSEQUENCE.
#
#  THIS REPLACED THREE COEXISTING CONVENTIONS. The root file carried
#  `<verb> <target>`; `dev/just/*.just` carried an eleven-module tree reached
#  as `just dev <module> <recipe>` (`dev::code::check`, `dev::test::unit`);
#  and inside that tree the stack module inverted the grammar again, putting
#  the verb LAST (`dev::stack::dev-up`). `dev::code::*` and `dev::test::*` were
#  outright duplicates of the root verbs, so two spellings of one gate could
#  drift apart. One grammar now covers the lot.
#
#  Every gate, audit, and measurement below is one `python -m dev <verb>
#  <target>` call whose behaviour is declared in `dev/toolchain.py`; nothing
#  about WHAT a target runs lives in a justfile. The process-lifecycle and
#  container recipes are the deliberate exception - they are thin passthroughs
#  to the product CLI and to `docker compose`, and are named as such.
#
#  The GROUPS split by CONSEQUENCE, not by tool. The taxonomy is a closed set
#  of ten, identical in every repository:
#
#    setup    Provisioning and dependency resolution. MUTATES the environment.
#    dev      Day-to-day operations on this checkout that are not gates.
#    check    GATES.    Read-only, and a finding fails the build.
#    fix      MUTATES.  Everything automatically repairable, in one pass.
#    audit    ADVISORY, and exits 0 even with findings, because each yields a
#             lead to confirm. `audit-deps` is the ONE exception: a published
#             advisory against a pinned version is a verdict, so it gates.
#    build    Produces artifacts from a plain checkout.
#    release  Actions that need a published tag.
#    docs     Regenerates committed documentation assets.
#    test     GATES.
#    meta     The recipe list and the composed pipeline.
#
#  The `health-*` recipes MEASURE and always exit 0; they are filed under
#  `audit` because measurement without a verdict is what that group is.
#
#  THRESHOLDS ARE PUBLISHED INDUSTRY DEFAULTS, not this tree's current worst
#  offender. `just check-all` therefore chains only the dimensions that hold
#  that line today; `just check-strict` runs every dimension including the
#  unfinished burndowns and is expected to be red. `just health-report` ranks
#  the distance between the two.
# ===========================================================================

# Requires just >= 1.38 (`set working-directory`, native modules, `[doc]`/`[group]`).
#
# just defaults to `sh -cu` on every platform, which on Windows means a Git Bash
# `sh.exe` that is only on PATH for some Git for Windows install options. This
# names the one interpreter every Windows machine is guaranteed to have.
#
# `cmd` is chosen for EXIT-CODE FIDELITY, not familiarity. It forwards a native
# command's status verbatim; `pwsh -Command` and `powershell -Command` collapse
# every non-zero status onto 1, which would flatten the whole of
# `dev/exit_codes.py` - INIT_STALE 3, INIT_LOCKED 6, TOOL_BROKEN 7,
# NOTHING_SELECTED 8 - onto FAILED, and destroy the advisory-versus-gating
# split the recipe groups are built on. cmd's weaknesses - `%VAR%` expansion
# and no single-quote literal - cost nothing here, because every recipe body
# below is a single command with no shell syntax and no recipe body contains
# either character.
set windows-shell := ["cmd.exe", "/c"]
set quiet := true
set dotenv-load := true

# The development toolchain's single entry point.
dev := "uv run --no-sync --frozen --no-default-groups --group tooling python -m dev"

# The product CLI, for the passthrough recipes in the `dev` group.
product := "uv run --no-sync --frozen --no-default-groups vaultspec-a2a"

# The process registry that owns every long-lived development service.
procs := "uv run --no-sync --frozen --no-default-groups vaultspec-a2a procs"

# The vaultspec-core and vaultspec-rag CLIs this checkout runs on ITSELF.
core := "uv run --no-sync --frozen --no-default-groups --group tooling vaultspec-core"
rag := "uv run --no-sync --frozen --no-default-groups --extra rag vaultspec-rag"
safe_enroll := "uv run --no-sync --frozen --no-default-groups --group tooling python dev/vault/enroll.py"

# The bounded Docker Compose projects. Each is pinned to its own project name
# so one stack can never tear another's containers down.
compose_dev := "docker compose --project-name vaultspec-a2a-dev -f service/docker-compose.dev.yml"
compose_integration := "docker compose --project-name vaultspec-a2a-integration -f service/docker-compose.integration.yml"
compose_database := "docker compose --project-name vaultspec-a2a-database -f service/docker-compose.prod.yml -f service/docker-compose.prod.postgres.yml"
compose_prod := "docker compose --project-name vaultspec-a2a-prod -f service/docker-compose.prod.yml"
compose_infrastructure := "docker compose --project-name vaultspec-a2a-infrastructure -f service/docker-compose.integration.yml"

# List every recipe, grouped by consequence.
[group('meta')]
default:
    @just --list

# ===========================================================================
#  setup
#
#  The dependency recipes deliberately do NOT go through `uv run --no-sync`:
#  changing the environment is their whole purpose. The dispatcher itself must
#  still run from an environment that exists, which is why it goes through the
#  already-resolved tooling profile.
# ===========================================================================

# `init` is the one command a fresh worktree needs, and the command git
# tooling and the worktree provisioner call after creating one. It cannot
# route through `{{dev}}`, which presumes the environment `init` is
# responsible for creating; it runs on an ephemeral interpreter instead, and
# `dev/init/` is stdlib-only for exactly that reason.
#
# Idempotent: a second run costs a stamp comparison and touches nothing.
# `just init-check` verifies without mutating, exiting 3 when the worktree is
# not initialized, which is what a hook or a provisioner calls. Set
# VAULTSPEC_INIT_JSON=1 for an NDJSON event stream, VAULTSPEC_INIT_FORCE=1 to
# ignore the stamp. Every run writes `.venv/init-report.json`.
#
# The phases run in dependency order and stop at the first failure: unlike the
# `-all` aggregates, which chain independent inspectors and run every one,
# these build one artifact, and `init-tools` runs executables out of the
# environment `init-python` creates. The report still lists every phase, with
# the ones that were not attempted naming the failure that stopped them.

# Initialize a fresh clone or worktree: dependencies, ACP runtime, enrollment, hooks.
[group('setup')]
init:
    uv run --no-project --python 3.13 -- python -m dev.init all

# Resolve the locked tooling and server dependency profiles into .venv.
[group('setup')]
init-python:
    uv run --no-project --python 3.13 -- python -m dev.init python

# Restore the project-pinned Claude ACP runtime from the npm lock.
[group('setup')]
init-node:
    uv run --no-project --python 3.13 -- python -m dev.init node

# Enroll the Vaultspec workspace and install the prek hook.
[group('setup')]
init-tools:
    uv run --no-project --python 3.13 -- python -m dev.init tools

# Report whether this worktree is initialized. Mutates nothing; exits 3 if not.
[group('setup')]
init-check:
    uv run --no-project --python 3.13 -- python -m dev.init check

# Resolve the base runtime profile from the project lock.
[group('setup')]
deps-base:
    {{dev}} deps base

# Resolve the server runtime profile from the project lock.
[group('setup')]
deps-server:
    {{dev}} deps server

# Resolve the RAG runtime profile without provisioning models.
[group('setup')]
deps-rag:
    {{dev}} deps rag

# Resolve the repository tooling profile from the project lock.
[group('setup')]
deps-tooling:
    {{dev}} deps tooling

# Restore the project-pinned ACP runtime from the npm lock.
[group('setup')]
deps-node:
    {{dev}} deps node

# Resolve every runtime extra plus the composed all dependency group.
[group('setup')]
deps-all:
    {{dev}} deps all

# Verify project metadata and the lock agree without changing either.
[group('setup')]
deps-check:
    {{dev}} deps check

# Regenerate the lockfile.
[group('setup')]
deps-lock:
    {{dev}} deps lock

# Regenerate the lockfile at the newest allowed versions.
[group('setup')]
deps-upgrade:
    {{dev}} deps upgrade

# Every probe below is one call into `dev/doctor`, which implements each check
# ONCE in stdlib-only Python. These recipes previously carried paired
# `[windows]`/`[unix]` bodies - including two separate semver comparators, one
# in PowerShell's `[Version]` type and one in `awk` - so which answer you got
# depended on which platform you were standing on.

# Diagnose required tools and report optional Docker support.
[group('setup')]
doctor-check:
    uv run --no-sync --frozen --no-default-groups --group tooling python -m dev.doctor check

# Verify Just, uv, Node.js, and npm and report their resolved versions.
[group('setup')]
doctor-required:
    uv run --no-sync --frozen --no-default-groups --group tooling python -m dev.doctor required

# Report Docker support without failing non-container workflows.
[group('setup')]
doctor-docker-optional:
    uv run --no-sync --frozen --no-default-groups --group tooling python -m dev.doctor docker-optional

# Require Docker and Compose for the container recipes.
[group('setup')]
doctor-docker:
    uv run --no-sync --frozen --no-default-groups --group tooling python -m dev.doctor docker

# Resolve the locked development environment used by the git hooks.
[group('setup')]
hooks-bootstrap:
    uv venv .venv --allow-existing
    uv sync --locked --no-default-groups --extra server --group all

# Install the repository-managed, path-agnostic prek hook.
[group('setup')]
hooks-install: hooks-bootstrap
    uv run --no-sync --frozen --no-default-groups --group dev python -m dev.repo.hooks install

# Remove the repository-managed prek hook.
[group('setup')]
hooks-remove:
    uv run --no-sync --frozen --no-default-groups --group dev python -m dev.repo.hooks remove

# Run the locked read-only hook pipeline outside a commit attempt.
[group('setup')]
hooks-run *ARGS:
    uv run --no-sync --frozen --no-default-groups --group dev prek run {{ ARGS }}

# Apply code repairs explicitly, then rerun the read-only hook pipeline.
[group('setup')]
hooks-repair *ARGS:
    {{dev}} fix python
    just hooks-run {{ ARGS }}

# ===========================================================================
#  check - GATES. Read-only, and a finding fails the build.
# ===========================================================================

# Ruff lint and format verification.
[group('check')]
check-python:
    {{dev}} lint python

# Ty type checking.
[group('check')]
check-type:
    {{dev}} lint type

# Ty type checking against every target platform.
[group('check')]
check-type-platforms:
    {{dev}} lint type-platforms

# Basedpyright strict-mode type checking.
[group('check')]
check-type-strict:
    {{dev}} lint type-strict

# Gate cognitive complexity over production code.
[group('check')]
check-complexity:
    {{dev}} lint complexity

# Gate cyclomatic complexity.
[group('check')]
check-cyclomatic:
    {{dev}} lint cyclomatic

# Gate function and class shape.
[group('check')]
check-shape:
    {{dev}} lint shape

# Gate the declared design limits.
[group('check')]
check-limits:
    {{dev}} lint limits

# Gate nesting depth.
[group('check')]
check-nesting:
    {{dev}} lint nesting

# Gate module length.
[group('check')]
check-size:
    {{dev}} lint size

# Gate the import discipline.
[group('check')]
check-imports:
    {{dev}} lint imports

# Gate the storage anchors.
[group('check')]
check-anchors:
    {{dev}} lint anchors

# Gate the declared dependency surface.
[group('check')]
check-dependencies:
    {{dev}} lint dependencies

# Check TOML formatting.
[group('check')]
check-toml:
    {{dev}} lint toml

# Check the GitHub Actions workflows.
[group('check')]
check-workflow:
    {{dev}} lint workflow

# Check the shell scripts a workflow step calls out to.
[group('check')]
check-shell:
    {{dev}} lint shell

# AGGREGATES RUN EVERY STEP and exit with the first non-zero status; they do
# not stop at the first failure. An aggregate is asked for a complete picture,
# and fail-fast costs a CI round-trip per defect. That is why these dispatch
# into `dev/` rather than listing their members as just dependencies: a
# dependency chain cannot express run-all-then-report. The membership lives in
# `dev/toolchain.py` as references to the same targets the individual recipes
# run, so an aggregate and its gates cannot disagree.

# Run every gating dimension that holds the line today.
[group('check')]
check-all:
    {{dev}} lint all

# Run every dimension including the unfinished burndowns; expected red.
[group('check')]
check-strict:
    {{dev}} lint strict

# ===========================================================================
#  fix - MUTATES. Everything automatically repairable, in one pass.
# ===========================================================================

# Apply configured lint fixes and formatting.
[group('fix')]
fix-python:
    {{dev}} fix python

# Sort and repair imports.
[group('fix')]
fix-imports:
    {{dev}} fix imports

# Format TOML.
[group('fix')]
fix-toml:
    {{dev}} fix toml

# Repair this repository's own .vault/ corpus.
[group('fix')]
fix-vault:
    {{dev}} fix vault

# Apply every automatic fix, in one pass.
[group('fix')]
fix-all:
    {{dev}} fix all

# ===========================================================================
#  audit - ADVISORY, except `audit-deps`, which gates.
# ===========================================================================

# Gate on published advisories against the locked versions.
[group('audit')]
audit-deps:
    {{dev}} audit deps

# Scan for insecure patterns; advisory, exits 0.
[group('audit')]
audit-security:
    {{dev}} audit security

# Report unreachable code; advisory, exits 0.
[group('audit')]
audit-dead-code:
    {{dev}} audit dead-code

# Report copy-paste clones; advisory, exits 0.
[group('audit')]
audit-duplication:
    {{dev}} audit duplication

# Report missing and malformed docstrings; advisory, exits 0.
[group('audit')]
audit-docstrings:
    {{dev}} audit docstrings

# Report test-tree complexity; advisory, exits 0.
[group('audit')]
audit-complexity:
    {{dev}} audit complexity

# Report every dimension; one red dimension does not hide the rest.
[group('audit')]
audit-all:
    {{dev}} audit all

# MEASUREMENT ONLY - always exits 0.

# Rank the worst offenders across every code-health dimension.
[group('audit')]
health-report:
    {{dev}} health report

# The same report, machine-readable.
[group('audit')]
health-json:
    {{dev}} health json

# Full per-dimension distributions behind each threshold.
[group('audit')]
health-census:
    {{dev}} health census

# ===========================================================================
#  test - GATES.
# ===========================================================================

# Run the unit gate, explicitly excluding service tests.
[group('test')]
test-unit:
    {{dev}} test unit

# Run the unit gate in parallel.
[group('test')]
test-parallel:
    {{dev}} test parallel

# Run deterministic service tests against real local services.
[group('test')]
test-service:
    {{dev}} test service

# Run the unit gate with terminal coverage.
[group('test')]
test-coverage:
    {{dev}} test coverage

# Run the harness's own test suite.
[group('test')]
test-harness:
    {{dev}} test harness

# Run every collected test, removing the project default marker exclusion.
[group('test')]
test-all:
    {{dev}} test all

# Report the lanes, models, and controls this host's provider CLIs serve.
# `--exports claude=haiku --option effort=low` renders the VAULTSPEC_LIVE_*
# block the live tier opts in with; the ids are catalog-derived, so read them
# from here rather than committing a block that goes stale.
[group('test')]
test-lanes *ARGS:
    uv run --no-sync --frozen python -m dev.providers {{ ARGS }}

# The durable-replay proof lives in the service tier, which the default gate
# excludes, so a default run never executed it and a bare service run could
# report green while it skipped. This tier declares the dashboard engine: it
# either EXECUTES the proof or fails naming the missing binary and how to
# supply it. A pass here is evidence; there is no skip-shaped green.
#
# Prove durable replay and lost-ack recovery across repositories (never skips).
[group('test')]
test-cross-repo *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- -m "" --require-prerequisite=dashboard-engine src/vaultspec_a2a/service_tests/test_engine_broker_lost_ack_live.py {{ ARGS }}

# These need the Codex and Claude CLIs on PATH and no credential whatsoever, so
# a certification job can provision them. Selected by explicit node id and run
# strict on purpose: a renamed or deleted gate is a usage error, and a gate that
# skips while its CLI is installed fails the run. Credential-gated provider
# lanes are deliberately NOT here - they need owner-supplied secrets.
#
# Run the provider gates whose prerequisite is an installable CLI (never skips).
[group('test')]
test-provider-gates *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- -m "" --require-prerequisite=codex-cli --require-prerequisite=claude-cli --require-prerequisite=mcp-streamable-http src/vaultspec_a2a/providers/tests/test_codex_chat_model.py::test_classify_provider_command_resolves_codex src/vaultspec_a2a/providers/tests/test_codex_chat_model.py::test_codex_readiness_ready_when_installed src/vaultspec_a2a/providers/tests/test_codex_config_home.py::TestCodexEntrypointAcceptsEmittedMcpConfig::test_codex_mcp_list_accepts_the_built_config_home src/vaultspec_a2a/providers/tests/test_acp_project_mcp.py::TestAcpEntrypointAcceptsProjectedMcpConfig::test_claude_mcp_list_accepts_the_projected_config {{ ARGS }}

# Prove gateway and worker telemetry start in a base-only installation.
#
# Runs in an isolated environment holding ONLY the default dependencies, so the
# optional OTLP exporter is genuinely absent rather than merely unimported - the
# condition that once aborted startup and that the main suite, which has the
# exporter installed, cannot reproduce. Installed editable on purpose: the wheel
# excludes `**/tests`, so the probe has no installed-module form to invoke.
[group('test')]
test-clean-base:
    uv run --isolated --no-project --with-editable . python -m vaultspec_a2a.telemetry.tests.probe_clean_base

# Collect the unit gate without executing tests.
[group('test')]
test-collect-unit *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- --collect-only -m "not service" {{ ARGS }}

# Collect the service gate without executing tests.
[group('test')]
test-collect-service *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- --collect-only -m service {{ ARGS }}

# Collect every test without the project default marker exclusion.
[group('test')]
test-collect-all *ARGS:
    uv run --no-sync --frozen --no-default-groups --group tooling python -m vaultspec_a2a.testing.runner -- -m "" --collect-only {{ ARGS }}

# ===========================================================================
#  build
# ===========================================================================

# Build the Python source distribution and wheel.
[group('build')]
build-package:
    {{dev}} build package

# Build the local development container images.
[group('build')]
build-docker:
    {{dev}} build docker

# Build the production gateway and worker container images.
[group('build')]
build-docker-prod:
    {{dev}} build docker-prod

# Remove generated package, documentation, and Python cache artifacts.
[group('build')]
build-clean:
    {{dev}} build clean

# Build every artifact producible without Docker.
[group('build')]
build-all:
    {{dev}} build all

# ===========================================================================
#  docs
#
#  The registry verb behind this is still `build`, because the documentation
#  IS an artifact and `build-all` composes it. The recipe is named and grouped
#  for the reader instead: every repository in the fleet spells its
#  documentation entry point `docs-*`, and a contributor looking for "how do I
#  build the docs" reads the group list, not the toolchain table.
# ===========================================================================

# Run documentation tests and build strict Sphinx HTML.
[group('docs')]
docs-build:
    {{dev}} build docs

# ===========================================================================
#  dev - passthroughs to the product CLI, the process registry, the bounded
#  Compose stacks, and this checkout's own vaultspec and RAG state.
# ===========================================================================

# Pass arguments directly to the product CLI.
[group('dev')]
product-cli *ARGS:
    {{product}} {{ ARGS }}

# Report gateway health through the product CLI.
[group('dev')]
product-doctor *ARGS:
    {{product}} doctor {{ ARGS }}

# List product team presets.
[group('dev')]
product-presets *ARGS:
    {{product}} presets {{ ARGS }}

# Start, inspect, or cancel runs through the product CLI.
[group('dev')]
product-run *ARGS:
    {{product}} run {{ ARGS }}

# Provision or verify an agent workspace through the product CLI.
[group('dev')]
product-workspace *ARGS:
    {{product}} workspace {{ ARGS }}

# List every registered process and its liveness verdict.
[group('dev')]
service-list:
    {{procs}} list

# Reserve and print the next free configured role port.
[group('dev')]
service-allocate ROLE:
    {{procs}} allocate {{ ROLE }}

# Start one configured process role under the production registry.
[group('dev')]
service-up ROLE NAME *ARGS:
    {{procs}} up {{ ROLE }} {{ NAME }} {{ ARGS }}

# Print the endpoint for one live registered process.
[group('dev')]
service-attach NAME:
    {{procs}} attach {{ NAME }}

# Tree-kill one registered process through the production registry.
[group('dev')]
service-kill NAME:
    {{procs}} kill {{ NAME }}

# Run the registered role's configured build command.
[group('dev')]
service-rebuild NAME:
    {{procs}} rebuild {{ NAME }}

# Kill, rebuild, and restart one registered process on its recorded port.
[group('dev')]
service-rerun NAME:
    {{procs}} rerun {{ NAME }}

# Restart one dead registered process on its recorded port.
[group('dev')]
service-resume NAME:
    {{procs}} resume {{ NAME }}

# Kill and clear every stale or dead registry record.
[group('dev')]
service-reap:
    {{procs}} reap

# Start a named development gateway through the production registry.
[group('dev')]
service-gateway-up NAME="dev" *ARGS:
    {{procs}} up gateway-dev {{ NAME }} {{ ARGS }}

# Start a named development worker through the production registry.
[group('dev')]
service-worker-up NAME="dev" *ARGS:
    {{procs}} up worker-dev {{ NAME }} {{ ARGS }}

# Start a named development engine with explicit serve, build, and data seats.
[group('dev')]
service-engine-up NAME REPO BUILD_REPO WORKSPACE *ARGS:
    {{procs}} up engine-dev {{ NAME }} --repo {{ REPO }} --build-repo {{ BUILD_REPO }} --workspace {{ WORKSPACE }} {{ ARGS }}

# Validate the development stack configuration.
[group('dev')]
stack-dev-config: doctor-docker
    {{compose_dev}} config

# Start the development stack.
[group('dev')]
stack-dev-up: doctor-docker
    {{compose_dev}} up -d --build --wait

# Stop and remove the development stack.
[group('dev')]
stack-dev-down: doctor-docker
    {{compose_dev}} down --remove-orphans

# Show development stack status.
[group('dev')]
stack-dev-status: doctor-docker
    {{compose_dev}} ps

# Validate the deterministic integration stack configuration.
[group('dev')]
stack-integration-config: doctor-docker
    {{compose_integration}} config

# Start the deterministic integration stack.
[group('dev')]
stack-integration-up: doctor-docker
    {{compose_integration}} up -d --build --wait

# Stop and remove the deterministic integration stack.
[group('dev')]
stack-integration-down: doctor-docker
    {{compose_integration}} down --remove-orphans

# Show deterministic integration stack status.
[group('dev')]
stack-integration-status: doctor-docker
    {{compose_integration}} ps

# Validate the PostgreSQL-backed stack configuration.
[group('dev')]
stack-database-config: doctor-docker
    {{compose_database}} config

# Start only the PostgreSQL service in its isolated Compose project.
[group('dev')]
stack-database-up: doctor-docker
    {{compose_database}} up -d --wait postgres

# Stop and remove the isolated PostgreSQL Compose project.
[group('dev')]
stack-database-down: doctor-docker
    {{compose_database}} down --remove-orphans

# Show PostgreSQL stack status.
[group('dev')]
stack-database-status: doctor-docker
    {{compose_database}} ps

# Validate the production stack configuration.
[group('dev')]
stack-prod-config: doctor-docker
    {{compose_prod}} config

# Start the production stack.
[group('dev')]
stack-prod-up: doctor-docker
    {{compose_prod}} up -d --build --wait

# Stop and remove the production stack.
[group('dev')]
stack-prod-down: doctor-docker
    {{compose_prod}} down --remove-orphans

# Show production stack status.
[group('dev')]
stack-prod-status: doctor-docker
    {{compose_prod}} ps

# Validate the integration file used by the isolated infrastructure project.
[group('dev')]
stack-infrastructure-config: doctor-docker
    {{compose_infrastructure}} config

# Start only Jaeger in its isolated infrastructure Compose project.
[group('dev')]
stack-infrastructure-up: doctor-docker
    {{compose_infrastructure}} up -d --wait jaeger

# Stop and remove the isolated infrastructure Compose project.
[group('dev')]
stack-infrastructure-down: doctor-docker
    {{compose_infrastructure}} down --remove-orphans

# Show infrastructure stack status.
[group('dev')]
stack-infrastructure-status: doctor-docker
    {{compose_infrastructure}} ps

# Resolve locked tooling and enroll the workspace through Vaultspec Core.
[group('dev')]
vault-setup:
    uv sync --locked --no-default-groups --group tooling
    {{safe_enroll}}

# Enroll the workspace after the tooling profile has already been synchronized.
[group('dev')]
vault-install:
    {{safe_enroll}}

# Preview Core-owned enrollment and Git-ignore reconciliation.
[group('dev')]
vault-install-dry-run:
    {{core}} install all --mode dev --dry-run

# Reconcile canonical rules, projections, MCP configuration, and Git-ignore policy.
[group('dev')]
vault-sync:
    {{core}} sync all

# Preview Core-owned reconciliation without changing the workspace.
[group('dev')]
vault-sync-dry-run:
    {{core}} sync all --dry-run

# Deliberately refresh Core inside its declared compatibility range.
[group('dev')]
vault-upgrade:
    uv lock --upgrade-package vaultspec-core
    uv sync --locked --no-default-groups --group tooling
    {{core}} --version
    {{safe_enroll}}
    uv lock --check

# Diagnose framework, provider, projection, configuration, and Git-ignore state.
[group('dev')]
vault-doctor:
    {{core}} spec doctor

# Report the locked Core version and workspace diagnosis.
[group('dev')]
vault-status:
    {{core}} --version
    {{core}} spec doctor

# Repair this repository's own .vault/ corpus outside commit validation.
[group('dev')]
vault-repair:
    {{core}} vault check all --fix

# Remove Vaultspec template annotations outside commit validation.
[group('dev')]
vault-sanitize:
    {{core}} vault sanitize annotations

# Fail when the ACP launch spec does not serve the tools the harness declares.
[private]
[group('dev')]
_rag-check-tool-contract:
    uv run --no-sync --frozen --no-default-groups --extra rag python -m dev.rag tool-contract

# Resolve locked RAG dependencies and enroll the workspace without provisioning.
[group('dev')]
rag-setup: _rag-check-tool-contract
    uv sync --locked --no-default-groups --extra rag
    {{rag}} install --mode dependency --no-mcp --no-provision --no-torch-config --yes

# Enroll RAG after its profile is synchronized; download no models or Qdrant.
[group('dev')]
rag-install: _rag-check-tool-contract
    {{rag}} install --mode dependency --no-mcp --no-provision --no-torch-config --yes

# Preview non-provisioning workspace enrollment.
[group('dev')]
rag-install-dry-run:
    {{rag}} install --mode dependency --no-mcp --no-provision --no-torch-config --yes --dry-run

# Deliberately refresh RAG inside its declared compatibility range.
[group('dev')]
rag-upgrade: _rag-check-tool-contract
    uv lock --upgrade-package vaultspec-rag
    uv sync --locked --no-default-groups --extra rag
    {{rag}} install --mode dependency --upgrade --no-mcp --no-provision --no-torch-config --yes
    {{rag}} --version
    {{rag}} status
    uv lock --check

# Build or update both document and source indexes.
[group('dev')]
rag-index:
    {{rag}} index --type all

# Preview source discovery without loading models or writing an index.
[group('dev')]
rag-index-dry-run:
    {{rag}} index --type all --dry-run

# Report project index counts and storage state.
[group('dev')]
rag-status:
    {{rag}} status

# Report installed dependency and live-service readiness independently.
[group('dev')]
rag-service-doctor:
    {{rag}} server doctor

# Start the managed-Qdrant search service explicitly.
[group('dev')]
rag-service-start:
    {{rag}} server start

# Start the local-store search service explicitly.
[group('dev')]
rag-service-start-local:
    {{rag}} server start --local-only

# Stop the owned search service explicitly.
[group('dev')]
rag-service-stop:
    {{rag}} server stop

# Report background search service state.
[group('dev')]
rag-service-status:
    {{rag}} server status

# Show recent background service activity.
[group('dev')]
rag-service-logs:
    {{rag}} server logs

# Explicitly download model files before first service use.
[group('dev')]
rag-warmup:
    {{rag}} server warmup

# ===========================================================================
#  meta
# ===========================================================================

# Run the current read-only local validation baseline.
[group('meta')]
ci:
    uv run --isolated --no-project python -m dev ci all
