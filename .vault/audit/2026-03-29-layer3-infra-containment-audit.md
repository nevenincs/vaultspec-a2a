---
date: 2026-03-29
tags:
  - "#audit"
  - "#infra-config"
related:
  - "[[2026-03-28-infra-config-phase1-review]]"
  - "[[2026-03-28-infra-config-rolling-audit]]"
---

# layer-3 infrastructure containment audit

Comprehensive audit of Docker, compose, config, and build-context
containment for the vaultspec-a2a project.

---

## check 3.1 — dockerfile scope

**Severity: MEDIUM**

### prod.Dockerfile

Uses targeted multi-stage COPY — no `COPY . /app`. The critical line is:

```dockerfile
COPY src/vaultspec_a2a/ ./src/vaultspec_a2a/
```

This copies the *entire* Python package tree, which **includes `tests/`
subdirectories embedded inside every sub-package** (~95 test files across
`api/tests/`, `context/tests/`, `control/tests/`, `graph/tests/`,
`thread/tests/`, `providers/tests/`, `streaming/tests/`, `telemetry/tests/`,
`tests/` (top-level), `tests/evals/`, `tests/preps/`, etc.).

**Violations:**

- **Test code in production images** — both gateway and worker stages inherit
  from `python-base`, which copies the full `src/vaultspec_a2a/` tree including
  all `tests/` directories. This adds dead weight and increases attack surface.
- **Gateway contains worker code** — the `python-base` stage copies all of
  `src/vaultspec_a2a/` including `worker/`, `graph/`, `providers/`,
  `streaming/` which are worker-only modules. The gateway stage inherits this
  unchanged.
- **Worker contains gateway code** — similarly, worker inherits `api/`,
  `control/`, `cli/` which are gateway-only modules.

The multi-stage build cleanly separates *runtime assets* (frontend build,
node_modules, Gemini CLI) but does **not** separate Python code by service
boundary.

### dev.Dockerfile

Same `COPY src/vaultspec_a2a/` pattern. Acceptable for dev images but
reinforces the structural debt.

**Recommendation:** Either add `.dockerignore` rules for `**/tests/` or
restructure to `COPY src/vaultspec_a2a/api/ ...` etc. per stage target. The
latter is higher effort but achieves true service isolation.

---

## check 3.2 — dockerfile and compose file placement

**Severity: LOW**

- Dockerfiles live in `docker/` — acceptable and better than repo root.
- **5 compose files at repo root** — `docker-compose.dev.yml`,
  `docker-compose.prod.yml`, `docker-compose.prod.postgres.yml`,
  `docker-compose.prod.providers.yml`, `docker-compose.integration.yml`.

This is a minor structural issue. The compose files clutter the repo root and
make it harder to scan the project. A `docker/` or `deploy/` directory
containing both Dockerfiles and compose files would be cleaner.

Not a blocking violation — compose files at root is a common convention and
Docker Compose resolves build contexts relative to the compose file location.

---

## check 3.3 — business logic in compose

**Severity: CLEAN**

No compose file contains complex entrypoint scripts or business logic. All
`command:` directives are straightforward:

- `docker-compose.dev.yml`: frontend uses `npm run dev -- --host 0.0.0.0`
- `docker-compose.integration.yml`: vidaimock uses a simple CLI invocation
  with flags; mock-seeder uses `uv run python docker/run.py`
- All other services rely on Dockerfile `CMD` directives

Healthchecks use inline Python one-liners (`urllib.request.urlopen(...)`)
which is slightly unusual but not business logic — they are pure
infrastructure probes.

---

## check 3.4 — hardcoded config in dockerfiles

**Severity: LOW**

prod.Dockerfile gateway stage:
```dockerfile
ENV VAULTSPEC_WORKER_URL=http://worker:8001 \
    VAULTSPEC_UI_BUILD_DIR=/app/src/ui/dist \
    VAULTSPEC_PROJECT_ROOT=/app \
    VAULTSPEC_AUTO_SPAWN_WORKER=false
```

prod.Dockerfile worker stage:
```dockerfile
ENV VAULTSPEC_GATEWAY_URL=http://gateway:8000 \
    VAULTSPEC_PROJECT_ROOT=/app
```

These are **Docker-internal service discovery defaults** (container hostnames,
internal paths). They are appropriate as ENV defaults — compose `environment:`
blocks can override them. No API keys, secrets, or external URLs are
hardcoded.

Ports 8000/8001 appear as hardcoded `EXPOSE` and in `CMD` `--port` flags.
These are internal container ports and correctly fixed. Host-side mapping is
parameterized in compose via `${VAULTSPEC_PORT:-8000}`.

**Minor nit:** The `EXPOSE 8000` on dev.Dockerfile line 23 is only relevant
to the `python-base` stage, not the `node-base` or `mock-seeder` stages.
Harmless but imprecise.

---

## check 3.5 — .env.example completeness

**Severity: LOW**

Cross-referencing `.env.example` against `InfraConfig` and `DomainConfig`
fields:

### Present in .env.example but NOT in InfraConfig/DomainConfig

- `FIGMA_ACCESS_TOKEN` — documented in .env.example but no corresponding
  field in either config class. Not consumed by any Python code in
  `src/vaultspec_a2a/`. This is a zombie env var.
- `CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY` / `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`
  — documented in .env.example as ACP subprocess env injection. Not modeled in
  config classes (correctly — they are passthrough subprocess env, not app
  config). Documented accurately.
- `VITE_API_URL` / `VITE_API_BASE_URL` — frontend-only vars. Correct to
  document but not model in Python config.

### In InfraConfig but missing from .env.example

- `GOOGLE_CLOUD_PROJECT_ID` — accepted as an alias via `AliasChoices` but not
  documented.
- `VAULTSPEC_MCP_API_BASE_URL` — accepted as an alias for `gateway_url` but
  not documented.

These are minor (aliases, not primary names), but completeness would help.

### Default value alignment

All checked defaults match between .env.example and config classes.
`max_concurrent_threads` lives in `DomainConfig` (correct layer placement)
and is documented in .env.example under `VAULTSPEC_MAX_CONCURRENT_THREADS=5`.

---

## check 3.6 — build context bloat

**Severity: MEDIUM**

`.dockerignore` excludes:
`.venv/`, `.git/`, `node_modules/`, `knowledge/repositories/*/`,
`__pycache__/`, `*.pyc`, `*.db*`, `.env`, `.vault/`, `.vaultspec/`,
`CLAUDE.md`, `Justfile`, `docker-compose*.yml`, `.pre-commit-config.yaml`,
`data/`, `logs/`, `temp/`, `docs/`, `.claude/`, `.mcp.json`, `*.log`,
`*.tmp`, `*.bak`

**Not excluded but should be:**

- `tests/` at repo root (currently empty, but should be excluded defensively)
- `**/tests/` inside `src/vaultspec_a2a/` — **~95 test files** are copied
  into every Docker image. This is the biggest bloat/security issue.
- `knowledge/` top-level (only `knowledge/repositories/*/` is excluded, but
  other `knowledge/` content would leak through)
- `*.md` files (README, CHANGELOG, etc.) — minor but unnecessary in build
  context
- `alembic/versions/` — migration scripts are needed for the app but worth
  noting as context
- `docker/README.md` — minor

**Good exclusions:** `.vault/`, `.vaultspec/`, `docs/`, `data/`, `logs/`,
`.git/`, `node_modules/` are all correctly excluded.

---

## check 3.7 — service topology clarity

**Severity: MEDIUM**

Current layout for a new developer:

```
repo-root/
  docker-compose.dev.yml            # dev stack
  docker-compose.integration.yml    # integration test stack
  docker-compose.prod.yml           # prod SQLite stack
  docker-compose.prod.postgres.yml  # prod Postgres overlay
  docker-compose.prod.providers.yml # provider API key passthrough
  docker/
    dev.Dockerfile
    prod.Dockerfile
    vidaimock.Dockerfile
    run.py
    README.md
```

**Issues:**

- 5 compose files at root with different naming conventions (`dev`, `prod`,
  `prod.postgres`, `prod.providers`, `integration`) make it unclear which
  files are standalone vs overlays. A developer must read each to understand
  the layering.
- No `services/` or `deploy/` directory to signal "this is deployment config."
- The compose overlay pattern (`-f base -f overlay`) is powerful but not
  self-documenting. The Justfile presumably wraps these, but the raw file
  layout does not communicate the topology.
- Service names in compose files are `gateway`, `worker`, `frontend`,
  `vidaimock`, `mock-seeder`, `jaeger`, `postgres` — clear individually but
  the full topology requires reading multiple files.

**Recommendation:** A `deploy/` or `docker/` directory containing all compose
files with a short `README.md` explaining the overlay pattern would
significantly improve discoverability.

---

## check 3.8 — configuration scatter

**Severity: MEDIUM**

Config values are defined in **four layers** with potential for drift:

| Value | .env.example | Compose env: | Dockerfile ENV | config.py default |
|---|---|---|---|---|
| `VAULTSPEC_WORKER_URL` | `(commented)` | `http://worker:8001` (dev) | `http://worker:8001` (gateway) | `""` (auto-derived) |
| `VAULTSPEC_GATEWAY_URL` | `(commented)` | `http://gateway:8000` (dev worker) | `http://gateway:8000` (worker) | `""` (auto-derived) |
| `VAULTSPEC_AUTO_SPAWN_WORKER` | `true` | `false` (all compose) | `false` (gateway) | `True` |
| `VAULTSPEC_DATABASE_URL` | `sqlite+aiosqlite:///vaultspec.db` | `sqlite+aiosqlite:////app/data/vaultspec.db` | *(not set)* | `sqlite+aiosqlite:///vaultspec.db` |
| `VAULTSPEC_DATABASE_BACKEND` | `sqlite` | `sqlite` (dev/prod) / `postgres` (overlay) | *(not set)* | `"sqlite"` |
| `VAULTSPEC_PROJECT_ROOT` | `(commented)` | *(not set)* | `/app` | computed from `__file__` |
| `VAULTSPEC_ENVIRONMENT` | `development` | `production` (prod compose) | *(not set)* | `development` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | `http://jaeger:4317` (prod/integration) | *(not set)* | *(not modeled)* |

**Observations:**

- `VAULTSPEC_WORKER_URL` and `VAULTSPEC_GATEWAY_URL` are set in **both**
  Dockerfile ENV and compose `environment:` blocks. The compose values
  override the Dockerfile defaults, making the Dockerfile values dead code in
  any compose deployment. This is the standard Docker pattern but creates two
  places to maintain the same value.
- `VAULTSPEC_AUTO_SPAWN_WORKER` defaults to `true` in config.py and
  .env.example but is overridden to `false` in every compose file AND the
  Dockerfile. The 3-layer override chain works but is fragile.
- `VAULTSPEC_DATABASE_URL` uses different path formats: relative
  (`///vaultspec.db`) in config.py/.env.example vs absolute
  (`////app/data/vaultspec.db`) in compose. Correct for their contexts but
  requires understanding the 3-slash vs 4-slash SQLite URL convention.
- `OTEL_EXPORTER_OTLP_ENDPOINT` is documented in .env.example but not
  modeled in `InfraConfig` — it is consumed directly by the OpenTelemetry SDK
  via environment. This is correct (SDK convention) but means it falls outside
  the config validation boundary.

---

## summary table

| Check | Finding | Severity |
|---|---|---|
| 3.1 Dockerfile scope | Test code + cross-service Python in all images | **MEDIUM** |
| 3.2 File placement | 5 compose files at root; Dockerfiles in docker/ | LOW |
| 3.3 Business logic in compose | Clean — no complex entrypoints | **CLEAN** |
| 3.4 Hardcoded config | Docker-internal defaults only; appropriate | LOW |
| 3.5 .env.example completeness | Zombie `FIGMA_ACCESS_TOKEN`; 2 undocumented aliases | LOW |
| 3.6 Build context bloat | `**/tests/` not excluded; ~95 test files in images | **MEDIUM** |
| 3.7 Service topology clarity | Overlay pattern not self-documenting | MEDIUM |
| 3.8 Configuration scatter | 4-layer override chain for key values; functional but fragile | MEDIUM |

## top-priority fixes

- **Add `**/tests/` to .dockerignore** — immediate win, zero risk, removes
  test code from all production images.
- **Remove `FIGMA_ACCESS_TOKEN` from .env.example** — dead var, confusing.
- **Document the compose overlay pattern** in docker/README.md or a root-level
  comment block.
