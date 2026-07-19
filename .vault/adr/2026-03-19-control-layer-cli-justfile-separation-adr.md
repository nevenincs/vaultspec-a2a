---
tags:
  - "#adr"
  - "#control-layer-cli-justfile-separation"
date: '2026-03-19'
related:
  - "[[2026-03-04-worker-process-architecture-adr]]"
  - "[[2026-03-31-docs-vault-migration-research]]"
superseded_by: '2026-07-19-repository-tooling-hardening-adr'
modified: '2026-07-19'
---
# `control-layer-cli-justfile-separation` adr: `adr-038` | (**status:** `superseded`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-038`
- Original title: `Control Layer — CLI/Justfile Separation`
- Legacy status at migration time: `Accepted`

## Original ADR

## ADR-038: Control Layer — CLI/Justfile Separation

**Date:** 2026-03-19
**Status:** Accepted
**Supersedes:** ADR-034 (CLI Domain Restructure)

## 1. Context

The CLI usability audit (2026-03-19) found that an operator spent 11 of 18
minutes fighting service startup. The root cause: the Python CLI mixes
production commands (team operations) with dev tooling (service lifecycle,
testing, database management). This is the same mistake vaultspec-core made
and fixed — the fix is the same.

ADR-034 proposed restructuring the CLI into 6 domain groups but kept all
commands in the Python CLI. This ADR supersedes it with a clean separation:

- **Python CLI** (`vaultspec`): Production-only. Operates teams and agents
  against a running backend. Fail-fast if backend is down.
- **Justfile** (`just`): Development toolchain. Two namespaces: `dev`
  (services, code quality, testing, building, dependencies) and `prod`
  (passthrough to the Python CLI).

## 2. Decision

### 2.1 Python CLI Surface

```text
vaultspec [--verbose] [--debug] [--version] [--show-config] <command>

  team
    start         --preset NAME --message TEXT [--name NICK] [--autonomous|--supervised]
    message       THREAD_ID --content TEXT [--agent AGENT_ID]
    respond       THREAD_ID --request-id ID --option OPTION_ID
    resume        THREAD_ID [--message TEXT]
    cancel        THREAD_ID
    delete        THREAD_ID
    archive       THREAD_ID
    status        THREAD_ID [--json]
    watch         THREAD_ID
    list          [STATUS_FILTER] [--json]
    presets       [--json]

  agent
    list          [--json]
    show          NAME [--json]
```

Root options follow vaultspec-core:

| Option | Short | Meaning |
|--------|-------|---------|
| `--verbose` | `-v` | INFO logging |
| `--debug` | `-d` | DEBUG logging |
| `--version` | `-V` | Print version, exit |
| `--show-config` | | Print resolved settings, exit |

Every command fails fast if the gateway is unreachable, printing:

```text
Error: Gateway not running at http://127.0.0.1:8000

  just dev service start gateway    Start the gateway
  just dev service start            Start all services
```

### 2.2 Commands Removed from Python CLI

| File | Commands | Reason |
|------|----------|--------|
| `_service.py` | start, stop, kill, status | Dev tooling → Justfile `dev service` |
| `_test.py` | unit, smoke, benchmark, prodlike-* | Dev tooling → Justfile `dev test` |
| `_verify.py` | (imported by _test) | Dev tooling → Justfile `dev test verify` |
| `_run.py` | mock, probe | Dev tooling → Justfile `dev test` |
| `_database.py` | update, clear, snapshot, restore | Dev tooling → Justfile `dev service db` |
| `_mcp.py` | status, tools, discovery | Out of scope — MCP is a separate executable |

### 2.3 Justfile Surface

```text
just dev service <action> [target]
just dev code <action> [target]
just dev test <target> [*args]
just dev build <target>
just dev deps <action>
just prod <command> [*args]
```

#### `dev service` — Service lifecycle

```text
just dev service start [target=all]
just dev service stop [target=all]
just dev service kill [target=all]
just dev service restart [target=all]
just dev service rebuild [target=all]
just dev service health [target=all]
just dev service logs TARGET
just dev service probe PROVIDER | --list
```

Service targets:

| Target | Services |
|--------|----------|
| `all` | Everything in dependency order (prod + dev) |
| `prod` | gateway + worker + ui + postgres |
| `dev` | jaeger + vidaimock |
| `gateway` | Gateway API server (:8000) |
| `worker` | Worker executor (:8001) |
| `ui` | Vite frontend (:5173) |
| `postgres` | PostgreSQL (:5432) |
| `jaeger` | Jaeger tracing (:4317, :16686) |
| `vidaimock` | Mock LLM provider (:8100) |

Multi-target: `just dev service start gateway worker`

Database operations (owned by gateway):

```text
just dev service db migrate [--fix]
just dev service db snapshot [list]
just dev service db restore --name FILE
just dev service db clear --yes
```

#### `dev code` — Code quality

```text
just dev code check [target=all]     # read-only
just dev code fix [target=all]       # auto-repair
```

Targets: `lint`, `type`, `ui`, `all`

#### `dev test` — Testing

```text
just dev test unit [*ARGS]
just dev test live [*ARGS]
just dev test smoke [*ARGS]
just dev test tracing [*ARGS]
just dev test mock [NAME | --list]
just dev test verify docker | provider NAME | endpoints | core
just dev test ci                      # unit + tracing (CI gate)
just dev test all                     # everything
```text

#### `dev build` — Build artifacts

```text
just dev build package                # Python sdist + wheel
just dev build docker                 # Local dev Docker image
just dev build docker-prod            # Production multi-stage image
just dev build clean                  # Remove dist/, egg-info, __pycache__
```

#### `dev deps` — Dependency management

```text
just dev deps install                 # Full bootstrap (uv sync + npm install)
just dev deps sync                    # Sync to lockfile
just dev deps upgrade                 # Upgrade all
just dev deps lock                    # Regenerate lockfile
```

#### `prod` — Production CLI passthrough

```text
just prod team [*ARGS]                → uv run vaultspec team ...
just prod agent [*ARGS]               → uv run vaultspec agent ...
```

### 2.4 The `control` Module

Python implementations for Justfile-invoked commands live in
`src/vaultspec_a2a/control/`, invoked via `python -m`:

```text
src/vaultspec_a2a/control/
├── __init__.py
├── doctor.py          # Port scanning, config validation, service health
├── db.py              # Database clear, snapshot, restore
└── verify.py          # Prod-like Docker verification
```

This module is NOT registered as a CLI command group. The Justfile calls it:

```text
just dev service health  →  uv run python -m vaultspec_a2a.control.doctor
just dev service db ...  →  uv run python -m vaultspec_a2a.control.db ...
just dev test verify ... →  uv run python -m vaultspec_a2a.control.verify ...
```

### 2.5 No Background Process Management

The `_service.py` approach (background spawning, PID registry, zombie
detection) is deleted entirely. `just dev service start gateway` runs
uvicorn in the foreground with `--reload`. This resolves 5 audit findings
by design:

| Finding | Resolution |
|---------|-----------|
| F-02 (env not propagated) | Foreground process inherits shell env |
| F-03 (success for dead process) | You see the crash immediately |
| F-04 (PID tracking blind) | No PID tracking needed |
| F-05 (no port conflict detection) | `bind()` fails visibly |
| F-07 (no stderr visible) | stderr in your terminal |

## 3. Consequences

### 3.1 Positive

- Python CLI is lean (2 command groups, 13 commands)
- Every CLI command has a clear prerequisite: backend must be running
- Service lifecycle bugs eliminated by design (foreground processes)
- Justfile mirrors vaultspec-core pattern (validated in production)
- `just dev` and `just prod` are discoverable top-level namespaces

### 3.2 Negative

- Breaking change: all existing `vaultspec service/test/run/database`
  invocations must move to Justfile equivalents
- Justfile recipes are more complex (nested dispatch via case/esac)
- Contributors must install `just` for dev workflows

### 3.3 Risks

- Deep nesting (`just dev service db migrate --fix`) is 5 tokens.
  Mitigated by: Justfile `--list` shows all recipes, and the hierarchy
  is logical enough to guess.

## 4. Compliance Matrix

| ADR | Relationship | Status |
|-----|-------------|--------|
| ADR-016 (Task Runner) | Extends — adds dev/prod namespaces to Justfile | Compliant |
| ADR-031 (Worker Process) | Unchanged — gateway/worker separation preserved | Compliant |
| ADR-034 (CLI Restructure) | **Superseded** — this ADR replaces it | Superseded |
