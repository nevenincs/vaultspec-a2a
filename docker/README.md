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

---

## Notes

- All Docker definitions live under `docker/` for consistency.
- `docker-compose.dev.yml` is the default frontend-ready stack.
- `docker-compose.integration.yml` is the richer overlay for mocks and tracing.
- `docker-compose.prod.yml` no longer reads developer `.env` files implicitly.
- If you add a new service, prefer adding a new target to the appropriate Dockerfile and referencing it explicitly in compose.
