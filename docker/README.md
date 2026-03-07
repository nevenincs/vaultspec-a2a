# Docker Overview

This directory contains all Docker build definitions for the project. Compose files reference these Dockerfiles directly for clarity and consistency.

## Files

- `dev.Dockerfile`  
  Development-only images and targets. Used by `docker-compose.dev.yml`.

- `prod.Dockerfile`  
  Production build targets for API and Worker services. Used by `docker-compose.prod.yml`.

- `vidaimock.Dockerfile`  
  Dedicated image for the `vidaimock` service (mock model API).

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

**Used by:** `docker-compose.dev.yml`  
**Typical usage:** local development with HMR, mocks, tracing.

---

### `docker/prod.Dockerfile`

**Targets:**
- `api`  
  Builds the production API (gateway). Includes the compiled frontend assets.

- `worker`  
  Builds the production worker (agent executor). No frontend assets included.

**Used by:** `docker-compose.prod.yml`  
**Typical usage:** production-like deployment.

---

### `docker/vidaimock.Dockerfile`

**Purpose:**
- Runs `vidaimock` with recorded tapes for deterministic mocking.

**Used by:** `docker-compose.dev.yml` (dev)

---

## Compose Mapping

- `docker-compose.dev.yml`  
  - `frontend` → `docker/dev.Dockerfile` `node-base`  
  - `mock-seeder` → `docker/dev.Dockerfile` `mock-seeder`  
  - `vidaimock` → `docker/vidaimock.Dockerfile`

- `docker-compose.prod.yml`  
  - `api` → `docker/prod.Dockerfile` `api`  
  - `worker` → `docker/prod.Dockerfile` `worker`

---

## Notes

- All Docker definitions live under `docker/` for consistency.
- Dev and prod concerns are split cleanly by target and compose file.
- If you add a new service, prefer adding a new target to the appropriate Dockerfile and referencing it explicitly in compose.