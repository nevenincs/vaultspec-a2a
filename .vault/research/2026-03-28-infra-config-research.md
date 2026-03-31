---
tags:
  - '#research'
  - '#infra-config'
date: '2026-03-28'
related:
  - '[[2026-03-28-post-layer2d-boundary-audit]]'
  - '[[2026-03-28-layer2d-rolling-audit]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `infra-config` research: layer 3 — infrastructure config

Research into three tracks for Layer 3: settings god-object reduction,
Docker/Compose topology cleanup, and Justfile audit. Conducted via three
parallel research agents analyzing the full codebase.

## Track A: Settings Import Footprint

### Current State

`Settings` composes `DomainConfig` (18 fields) + `InfraConfig` (75+ fields)
via multiple inheritance. The global `settings` singleton is imported from
52 sites across 37 production files + 7 test files.

### Classification of Import Sites

| Classification | Prod Files | Details |
|---|---|---|
| **domain-only** | 7 | Use exclusively DomainConfig fields |
| **infra-required** | 29 | Use at least one InfraConfig field |
| **mixed** | 1 | `worker/executor.py` (both domain + infra) |
| **Total prod** | **37** | |

### Domain-Only Files (switch candidates)

These 7 files access exclusively DomainConfig fields and could import
`domain_config` instead of `settings`:

| File | Field Used |
|------|------------|
| `api/ws_dispatch.py` | `graph_recursion_limit` |
| `api/routes/cancel.py` | `graph_recursion_limit` |
| `api/routes/messages.py` | `graph_recursion_limit` |
| `api/routes/permissions.py` | `graph_recursion_limit` |
| `api/routes/threads.py` | `graph_recursion_limit` |
| `worker/graph_lifecycle.py` | `max_cached_graphs` |
| `control/dispatch.py` | `graph_recursion_limit` |

All 7 use exactly one field each. The 5 API route files + `control/dispatch.py`
all access the same `graph_recursion_limit` field.

### Mixed File

`worker/executor.py` uses `graph_recursion_limit` (domain) and
`max_concurrent_threads` (infra). Cannot switch without relocating
`max_concurrent_threads` to `DomainConfig` or splitting the import.

### Key Infra-Heavy Consumers

- `api/app.py` — 17 fields (startup wiring, CORS, UI path, DB validation)
- `worker/app.py` — 11 fields (startup wiring, DB validation, URLs)
- `providers/factory.py` — 10 fields (all API keys + project_root + ACP backend)
- `control/doctor.py` — 9 fields (diagnostic introspection)
- `control/db.py` — 6 fields (database lifecycle)
- `cli/_util.py` — uses `settings.model_fields` (full Settings introspection)

### Finding: Reduction Target is Modest

Switching the 7 domain-only files reduces the `settings` footprint from
37 → 30 prod files (19% reduction). The remaining 30 files legitimately
need infrastructure fields (API keys, URLs, ports, DB config, timeouts).

The `InfraConfig` class itself is already well-factored — it is the sole
infrastructure config class, not a god-object by complexity but by import
breadth. The real win is decoupling Layer 2 entry points (API routes)
from infrastructure config they don't need.

## Track B: Docker/Compose Topology

### Current Topology (6 compose files + 3 Dockerfiles)

| File | Purpose | Services |
|------|---------|----------|
| `docker-compose.dev.yml` | Dev stack (SQLite) | gateway, worker, frontend |
| `docker-compose.prod.yml` | Prod base (SQLite + Jaeger) | gateway, worker, jaeger |
| `docker-compose.prod.postgres.yml` | Postgres overlay for prod | postgres (+ gw/worker overrides) |
| `docker-compose.postgres.yml` | **ORPHAN** legacy Postgres overlay | postgres (+ gw/worker overrides) |
| `docker-compose.prod.providers.yml` | Provider auth overlay | worker env overrides |
| `docker-compose.integration.yml` | Mock/test stack | vidaimock, mock-seeder, jaeger (+ gw/worker OTEL) |

| Dockerfile | Purpose |
|---|---|
| `docker/prod.Dockerfile` | Multi-stage: frontend-build → python-base → gateway / worker |
| `docker/dev.Dockerfile` | Dev images: python-base, node-base, mock-seeder |
| `docker/vidaimock.Dockerfile` | VidaiMock tape-replay server |

### Critical: Stale Volume Mount

`docker-compose.integration.yml` mounts
`./src/vaultspec_a2a/core/presets/mock/tapes:/app/tapes` — this path does
not exist post-Layer-1 decomposition. The correct path is
`./src/vaultspec_a2a/team/presets/mock/tapes`. Docker silently creates an
empty directory, so VidaiMock starts with no tapes.

### High: Orphan Compose File

`docker-compose.postgres.yml` is a legacy duplicate of
`docker-compose.prod.postgres.yml` with these differences:

- Uses `${POSTGRES_PASSWORD:?}` env var (prod variant hardcodes `vaultspec:vaultspec`)
- Missing `VAULTSPEC_CHECKPOINT_DATABASE_URL` (bug)
- Different volume name (`pg-data` vs `postgres-data`)
- Clears `db-data` volumes on gateway/worker (`volumes: []`)
- Not referenced by Justfile
- Not referenced by any active documentation

Recommendation: delete `docker-compose.postgres.yml`. If the
`${POSTGRES_PASSWORD:?}` pattern is wanted for real production, update
`docker-compose.prod.postgres.yml` to use env vars instead of hardcoded
credentials.

### Medium: `.dockerignore` Gaps

Missing entries that inflate build context:

| Missing | Impact |
|---|---|
| `.vault/` | ADR/plan/research markdown sent to daemon every build |
| `.vaultspec/` | Agent rules and templates |
| `tests/` | N/A — tests are inside `src/`, already copied |
| `*.md` (root-level) | Small but unnecessary |
| `Justfile` | Unnecessary in image |
| `docker-compose*.yml` | Unnecessary in image |

Note: `src/vaultspec_a2a/tests/` is COPY'd by the broad
`COPY src/vaultspec_a2a/ ./src/vaultspec_a2a/` in both Dockerfiles. Test
code lands in the production image but doesn't execute. Excluding tests
from the Dockerfile COPY would require restructuring the COPY commands.

### Low: Inconsistencies

- Dev compose gateway healthcheck: `/internal/health` vs prod: `/api/health`
- Integration compose Jaeger: no `restart: unless-stopped` (prod has it)
- `docker/README.md` references the orphan `docker-compose.postgres.yml`

## Track C: Justfile Audit

### Recipe Inventory: 83 total (15 public, 68 private)

| Section | Count | Notes |
|---|---|---|
| Top-level | 4 | `default`, `dev`, `prod`, `ci` |
| dev hooks | 6 | Commit pipeline (bootstrap, install, remove, run, fix) |
| dev service | 39 | 6-action × 6-target matrix + dispatcher + db + probe |
| dev code | 8 | lint/type/ui check + fix |
| dev test | 9 | unit/live/smoke/tracing/mock/verify/ci/all/cov |
| dev build | 5 | package/docker/docker-prod/clean |
| dev deps | 7 | install/sync/upgrade/lock + helpers |
| prod | 2 | team/agent passthrough |
| aliases | 3 | preps/preps-list/mcp |

### Module Existence: All Present

All 6 referenced Python modules exist and are importable:
`control.hooks`, `control.doctor`, `control.db`, `control.verify`,
`tests.preps`, `providers.probes`.

### No Dead Recipes Found

Every recipe dispatches to an existing module or valid command.

### Business Logic in Recipes

The `_dev-service-dispatch` recipe (lines 70–105) contains PowerShell
logic that encodes service topology knowledge:
- Hardcoded `$prodTargets = @("gateway", "worker", "ui", "postgres")`
- Hardcoded `$devTargets = @("jaeger", "vidaimock")`
- Group alias resolution and sequential iteration

This creates a maintenance burden: adding a new service requires editing
the dispatcher AND adding 7 leaf recipes (start/stop/kill/restart/rebuild/
health/logs).

### PowerShell / Bash Mixing

15+ recipes use `#!/usr/bin/env pwsh` shebangs. The split is intentional:
PowerShell for Windows process management (`Get-Process`, `Stop-Process`,
`Remove-Item`), bash for everything else. This creates a Linux/macOS
portability gap — the Justfile cannot run on non-Windows without PowerShell
Core installed.

### `stop` vs `kill` Redundancy

For foreground services (gateway, worker, ui), `stop` and `kill` recipes
are functionally identical — both use `Stop-Process -Force`. The
distinction is semantic-only.

### `preps` / `preps-list` Aliases

Labeled "backward compat" with a comment suggesting `just dev test mock`,
but `_dev-test-mock` runs `pytest -m requires_vidaimock` which is
**different** from `preps` (integration scenario runners). The aliases are
independently necessary. The comment is misleading.

### Service Lifecycle Bloat

The 6-action × 6-target matrix generates 36 leaf recipes, of which:
- 3 are no-op echo stubs (`logs-gateway/worker/ui`)
- 6 are identical pairs (`stop` ≡ `kill` for gateway/worker/ui)
- 6 are thin wrappers (`restart` = `stop + start`)

This accounts for 15 recipes that add minimal functional value.

### Finding: No Immediate Justfile Changes Required

The Justfile is large (515 lines, 83 recipes) but internally consistent
and all references are valid. The bloat is structural (combinatorial
explosion of targets × actions) but not harmful. The service topology
embedding is the only genuine concern, and addressing it would require
a Python-driven service manager (aligning with the planned service layer).

## Synthesis: Recommended Scope for Layer 3 PR

### Must-Do (bugs and broken paths)

- Fix stale tapes volume mount in `docker-compose.integration.yml`
- Delete orphan `docker-compose.postgres.yml`
- Update `.dockerignore` to exclude `.vault/`, `.vaultspec/`

### High-Value (measurable coupling reduction)

- Switch 7 domain-only files from `settings` → `domain_config` import
- This decouples 5 API route modules + `control/dispatch.py` +
  `worker/graph_lifecycle.py` from infrastructure config entirely

### Medium-Value (consistency and hygiene)

- Fix misleading `preps` backward-compat comment in Justfile
- Update `docker/README.md` to remove orphan compose file reference
- Align `.env.example` field `VAULTSPEC_ACP_INTERACTIVE_AUTH_TIMEOUT_SECONDS`
  (present in `InfraConfig` but absent from `.env.example`)

### Out of Scope (deferred to service layer)

- `_dev-service-dispatch` topology extraction to Python
- `max_concurrent_threads` relocation to DomainConfig
- `InfraConfig` further decomposition (the 30-file footprint is legitimate)
- PowerShell/bash unification (platform-specific by design)
- Test code in Docker images (requires COPY restructuring)
