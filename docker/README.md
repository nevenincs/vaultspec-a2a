# Docker Overview

This directory contains all Docker build definitions for the project. Compose
files reference these Dockerfiles directly for clarity and consistency.

## Files

- `dev.Dockerfile`
  Development-only images and targets. Used by `docker-compose.dev.yml` and the
  integration overlay.

- `prod.Dockerfile`
  Production build targets for gateway and worker services. Used by
  `docker-compose.prod.yml`.

- `vidaimock.Dockerfile`  
  Dedicated image for the `vidaimock` service (mock model gateway).

- `run.py`  
  Entrypoint logic for the `mock-seeder` target.

---

## Targets and When to Use Them

### `docker/dev.Dockerfile`

**Targets:**

- `python-base`  
  Base Python image for dev. Used by dev backends and tooling.

- `node-base`  
  Base Node image for the Vite dev server (HMR). Used by the **frontend** service.

- `mock-seeder`  
  Runs a loop to populate the mock database for demo/test flows. Used by the **mock-seeder** service.

**Used by:** `docker-compose.dev.yml`, `docker-compose.integration.yml`
**Typical usage:** local development with HMR, plus optional integration mocks.

---

### `docker/prod.Dockerfile`

**Targets:**

- `gateway`  
  Builds the production gateway. Includes the compiled frontend assets.

- `worker`  
  Builds the production worker (agent executor). No frontend assets included.

**Used by:** `docker-compose.prod.yml`  
**Typical usage:** production-like deployment.

---

### `docker/vidaimock.Dockerfile`

**Purpose:**

- Runs `vidaimock` with recorded tapes for deterministic mocking.

**Used by:** `docker-compose.integration.yml`

---

## Compose Mapping

- `docker-compose.dev.yml`
  Frontend-ready stack:
  - `gateway` → `docker/prod.Dockerfile` `gateway`
  - `worker` → `docker/prod.Dockerfile` `worker`
  - `frontend` → `docker/dev.Dockerfile` `node-base`

- `docker-compose.integration.yml`
  Optional overlay:
  - `vidaimock` → `docker/vidaimock.Dockerfile`
  - `mock-seeder` → `docker/dev.Dockerfile` `mock-seeder`
  - `jaeger` → upstream image

- `docker-compose.prod.yml`  
  - `gateway` → `docker/prod.Dockerfile` `gateway`
  - `worker` → `docker/prod.Dockerfile` `worker`
  - base SQLite transitional stack

- `docker-compose.prod.postgres.yml`
  Postgres production-like overlay:
  - adds `postgres:16-alpine`
  - switches gateway/worker to `VAULTSPEC_DATABASE_BACKEND=postgres`
  - switches the LangGraph checkpoint backend to Postgres
  - sets `VAULTSPEC_POSTGRES_REQUIRED=true`

- `docker-compose.prod.providers.yml`
  Optional provider-auth overlay:
  - passes through `CLAUDE_CODE_OAUTH_TOKEN`
  - passes through `GEMINI_API_KEY`
  - passes through `GOOGLE_API_KEY`
  - intended for explicit provider verification, not implicit local `.env` use

---

## Notes

- All Docker definitions live under `docker/` for consistency.
- `docker-compose.dev.yml` is the default frontend-ready stack.
- `docker-compose.integration.yml` is the richer overlay for mocks and tracing.
- The production-authoritative Docker path is:
  `docker compose -f docker-compose.prod.yml -f docker-compose.prod.postgres.yml up --build`
- Required production env:
  - `VAULTSPEC_INTERNAL_TOKEN` for gateway <-> worker internal auth
  - `POSTGRES_PASSWORD` when using `docker-compose.prod.postgres.yml`
- `just verify-prodlike-docker` is the current staged verification target for the
  Postgres production-like stack.
- The repo-owned Docker verifier scripts explicitly disable Docker Compose's
  default project `.env` loading (`COMPOSE_DISABLE_ENV_FILE=1`) so production
  verification uses only explicit inputs.
- Mutable verifier bundles, CLI-managed service state/logs, and
  gateway-managed worker stderr logs now emit under `.vault/runtime/`;
  `.vaultspec` is treated as protected and is not a supported mutable runtime
  sink. Historical bundles captured before this policy shift remain under
  `.vaultspec/runtime/`.
- Provider/runtime note:
  - the worker image now includes the Node.js runtime and
    `@zed-industries/claude-agent-acp` package needed for the Node-backed Claude
    ACP adapter path
  - the worker image now also includes the official pinned Gemini CLI package
    and runs it via the package `dist/index.js` entrypoint under Node
  - the supported explicit Docker auth path is:
    - Claude: `CLAUDE_CODE_OAUTH_TOKEN`
    - Gemini:
      `GEMINI_API_KEY` or `GOOGLE_API_KEY`, or a mounted local Gemini CLI
      state root via `GEMINI_HOST_CLI_HOME` -> `GEMINI_CLI_HOME`
  - repo-owned provider verification entry point:
    - `just verify-claude-docker`
    - `just verify-gemini-docker`
    - compatibility alias:
      `just verify-prodlike-docker-provider <claude|gemini>`
    - underlying CLI:
      `uv run vaultspec test prodlike-provider <claude|gemini>`
  - production-like Docker verification is therefore certifying for the
    backend stack itself and the Gemini runtime install path, but full
    Claude/Gemini provider certification still depends on supplying real
    provider credentials at verification time
  - current live status on March 11, 2026:
    - Claude Docker certification reaches ACP `session/prompt` and is blocked
      by provider quota/account state
    - Gemini Docker certification now reaches mounted OAuth visibility,
      token refresh, and ACP `initialize`, but still fails ACP `session/new`
      with `Authentication required`
- If you add a new service, prefer adding a new target to the appropriate Dockerfile and referencing it explicitly in compose.
