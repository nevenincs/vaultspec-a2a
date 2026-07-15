---
tags:
  - '#research'
  - '#service-layer'
date: '2026-03-30'
modified: '2026-07-15'
related:
  - '[[2026-03-28-infra-config-research]]'
  - '[[2026-03-28-infra-config-rolling-audit]]'
---

# `service-layer` research: containerization structure and live-test removal

Two-track research: (A) service layer containerization — consolidating
all Docker/compose/service topology under `service/`, and (B) live-test
infrastructure removal — identifying all files, config, CI, and Justfile
entries that constitute live testing and must be deleted.

## Track A: Service Layer Structure

### Current state — scattered topology

All Docker and compose files are fragmented across repo root and `docker/`:

**Repo root (5 compose files):**
- `docker-compose.dev.yml` — gateway + worker + frontend (SQLite)
- `docker-compose.prod.yml` — gateway + worker + Jaeger (SQLite)
- `docker-compose.prod.postgres.yml` — Postgres overlay
- `docker-compose.prod.providers.yml` — provider auth overlay
- `docker-compose.integration.yml` — VidaiMock + mock-seeder + Jaeger

**`docker/` directory (3 Dockerfiles + tooling):**
- `prod.Dockerfile` — multi-stage: frontend-build → python-base → gateway / worker
- `dev.Dockerfile` — dev images: python-base, node-base, mock-seeder
- `vidaimock.Dockerfile` — VidaiMock mock LLM provider
- `run.py` — mock-seeder entrypoint
- `README.md` — Docker docs

**Root config:**
- `.env.example` — all env vars
- `.dockerignore` — build context exclusions
- `Justfile` — service lifecycle recipes

No `service/` directory exists.

### Target state — `service/` owns all topology

```
service/
├── docker-compose.dev.yml
├── docker-compose.prod.yml
├── docker-compose.prod.postgres.yml
├── docker-compose.prod.providers.yml
├── docker-compose.integration.yml
├── .env.example
├── docker/
│   ├── prod.Dockerfile
│   ├── dev.Dockerfile
│   ├── vidaimock.Dockerfile
│   ├── run.py
│   └── README.md
```

Stays at repo root: `.dockerignore` (Docker requires it at build
context root), `Justfile`, `pyproject.toml`, `alembic.ini`,
`package*.json`.

### Path dependency analysis

All Dockerfiles COPY from repo-root paths (`src/vaultspec_a2a/`,
`pyproject.toml`, `uv.lock`, `alembic.ini`, `package*.json`, `src/ui/`).
After moving compose files to `service/`, `build.context` must point
back to repo root (`..`), not `.`.

**Compose `build` fields — before/after:**
- Before: `context: .`, `dockerfile: docker/prod.Dockerfile`
- After: `context: ..`, `dockerfile: service/docker/prod.Dockerfile`

**Compose bind-mount paths — before/after:**
- `./src/vaultspec_a2a/team/presets/mock/tapes` → `../src/vaultspec_a2a/team/presets/mock/tapes`
- `.:/app` (mock-seeder) → `..:/app`

**`dev.Dockerfile` CMD:** `uv run python docker/run.py` → needs COPY
update or path adjustment since the working dir is `/app` and the file
moves to `service/docker/run.py`.

**Justfile recipes:** 12 recipes reference compose files by path — all
need `service/` prefix.

**CI workflows:** `prodlike-docker.yml` references compose files — needs
path updates (but this workflow is being deleted as live-test infra).

## Track B: Live-Test Infrastructure Removal

### Files to delete (complete manifest)

**Live test files (10):**
- `src/vaultspec_a2a/tests/conftest.py`
- `src/vaultspec_a2a/tests/test_smoke.py`
- `src/vaultspec_a2a/tests/test_crash_recovery.py`
- `src/vaultspec_a2a/tests/test_permission_durability_live.py`
- `src/vaultspec_a2a/tests/test_ipc_heartbeat_live.py`
- `src/vaultspec_a2a/tests/test_mcp_e2e_live.py`
- `src/vaultspec_a2a/tests/test_reconciliation_live.py`
- `src/vaultspec_a2a/tests/test_replay_reconnect_live.py`
- `src/vaultspec_a2a/tests/test_snapshot_degradation_live.py`
- `src/vaultspec_a2a/tests/test_repo_hygiene.py`

**Preps directory (7 files):** entire `src/vaultspec_a2a/tests/preps/`

**Evals directory (16 files):** entire `src/vaultspec_a2a/tests/evals/`

**Provider probes (12 files):** entire `src/vaultspec_a2a/providers/probes/`

**CLI package (6 files):** entire `src/vaultspec_a2a/cli/`

**Control modules (2):** `control/verify.py`, `control/doctor.py`

**CI workflows (2):** `eval.yml`, `prodlike-docker.yml`

### Sub-package conftest files to clean (not delete)

These conftest files contain live-infra marker handling mixed with
legitimate unit-test fixtures. They need surgical edits:

- `telemetry/tests/conftest.py` — remove Jaeger fixtures and
  `pytest_runtest_setup` re-export
- `providers/tests/conftest.py` — remove `requires_acp` fail-fast hook
- `graph/tests/conftest.py` — remove `requires_vidaimock`/`requires_jaeger`
  marker handling
- `database/tests/conftest.py` — remove `requires_postgres` fail-fast hook

### pyproject.toml changes

- Remove `vaultspec` from `[project.scripts]` (keep `vaultspec-mcp`)
- Remove `[project.optional-dependencies].eval` section
- Remove 5 live markers from `[tool.pytest.ini_options].markers`
- Simplify `addopts` — drop the `-m "not live and not ..."` exclusion
- Remove live-test-only dev deps: `psutil`, `tenacity`,
  `testcontainers[generic]`, `websockets`

### Justfile recipes to remove (26)

All recipes referencing: live tests, smoke, tracing, mock, verify,
preps, probes, doctor, prod-team, prod-agent, and all jaeger/vidaimock
service lifecycle recipes.

### Cross-references — safe to delete

Zero production imports from any deletion target. All are invoked only
as `python -m` from Justfile/CI or via the `vaultspec` console script.

## Synthesis: Execution Phases

- **Phase 1:** Delete all live-test infrastructure (files, config, CI,
  Justfile recipes, pyproject.toml entries). Clean sub-package conftest
  files. Commit.
- **Phase 2:** Create `service/` directory. Move compose files and
  `docker/` directory. Move `.env.example`. Update all path references
  (compose build contexts, bind mounts, Justfile recipes). Commit.
- **Phase 3:** Verify — run full test suite, lint, type check. Update
  `README.md` architecture doc. Commit.
