---
tags:
- '#adr'
- '#containerization-strategy'
date: 2026-02-28
modified: '2026-07-15'
related:
- '[[2026-02-26-tech-stack-deployment-adr]]'
- '[[2026-02-26-observability-telemetry-integration-adr]]'
- '[[2026-02-28-dependency-hygiene-cli-entry-point-adr]]'
- '[[2026-03-31-docs-vault-migration-research]]'
---

# `containerization-strategy` adr: `adr-15` | (**status:** `proposed`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-15`
- Original title: `Containerization Strategy`
- Legacy status at migration time: `Proposed`

## Original ADR

## ADR-017: Containerization Strategy

**Date:** 2026-02-28
**Status:** Proposed

## 1. Context & Problem Statement

The project has no Docker infrastructure. This blocks:

- **Cross-platform verification**: Development is Windows-primary but
  deployment targets Linux. No way to verify the backend works on Linux
  without manual setup.
- **Contributor onboarding**: New developers must install Python 3.13,
  uv, Node.js, and configure environment variables manually.
- **Production deployment**: No containerized deployment path exists for
  cloud platforms (Fly.io, Railway, Render).
- **Observability verification**: OTel is now mandatory (ADR-015) but
  there's no local collector to receive traces — they vanish into
  `localhost:4317` connection errors.

### 1.1 Architecture Constraints

| Constraint               | Implication                                                    |
| ------------------------ | -------------------------------------------------------------- |
| SQLite with WAL mode     | Single-container only — WAL breaks across container boundaries |
| React `adapter-static`   | Frontend builds to pure HTML/JS/CSS — no Node runtime needed   |
| OTel mandatory (ADR-015) | Collector sidecar needed for trace consumption                 |
| Windows-primary dev      | Docker Desktop required, not native Linux containers           |
| 17 runtime Python deps   | All on PyPI, no git deps (ADR-015)                             |

### 1.2 Reference Patterns

| Project       | Architecture                            | Containers |
| ------------- | --------------------------------------- | ---------- |
| Open WebUI    | Single container (Python + built React) | 1          |
| Dify          | Multi-container (11 services)           | 11         |
| LangGraph CLI | Programmatic compose (3-4 services)     | 3-4        |
| a2a-samples   | Minimal per-agent Dockerfile            | 1          |

Open WebUI is the closest match to our stack (FastAPI + React,
single container).

## 2. Decision

### 2.1 Single-Container Production Architecture

The production image bundles both the Python backend and the pre-built
React static assets in a single container. FastAPI serves the API at
`/api` and the SPA at `/` — no separate Node runtime or reverse proxy
needed.

**Rationale:**

- SQLite WAL mode requires single-process database access
- `adapter-static` output is pure HTML/JS/CSS — no Node server needed
- Simplest deployment model for personal/team use
- Matches Open WebUI's proven architecture

### 2.2 Multi-Stage Dockerfile

Two build stages:

1. **Node stage**: `node:22-alpine` — builds React frontend
2. **Python stage**: `python:3.13-slim-bookworm` — installs deps, copies
   built frontend, serves everything

**Base image: `python:3.13-slim-bookworm`** (not Alpine):

- Alpine uses musl libc — breaks compiled packages (grpcio for OTel,
  SQLAlchemy C extensions)
- `slim-bookworm` ≈ 130MB, avoids Alpine pitfalls
- Many Python wheels lack Alpine builds → slow compilation from source

### 2.3 Docker Compose for Development

Three services:

1. **backend**: Python app with hot-reload
2. **frontend**: Vite dev server with HMR
3. **jaeger**: All-in-one OTel collector + trace UI

Jaeger is included by default because OTel is mandatory (ADR-015). No
separate overlay — traces should always have a consumer in development.

### 2.4 Dev Container for VS Code / Codespaces

A `.devcontainer/devcontainer.json` using devcontainer features for
Python (uv) and Node, with `postCreateCommand` running `just setup`.

## 3. Implementation

### 3.1 Dockerfile

```dockerfile
# ============================================================
# Stage 1: Build React frontend
# ============================================================
FROM node:22-alpine AS frontend-build
WORKDIR /app/src/ui
COPY src/ui/package*.json ./
RUN npm ci
COPY src/ui/ .
RUN npm run build

# ============================================================
# Stage 2: Python runtime
# ============================================================
FROM python:3.13-slim-bookworm AS runtime

# uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Phase 1: install deps only (cached layer)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev --locked

# Phase 2: install project + copy source
COPY lib/ ./lib/
COPY --from=frontend-build /app/src/ui/build ./src/vaultspec_a2a/api/static/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-editable

# Non-root user
RUN groupadd -g 1001 app && useradd -u 1001 -g app -m appuser
USER appuser

EXPOSE 8000

CMD ["uv", "run", "vaultspec"]
```text

**Key patterns:**

- **Two-phase uv sync**: deps cached separately from app code — code
  changes don't invalidate the dep layer
- **`UV_COMPILE_BYTECODE=1`**: faster startup in production
- **`UV_LINK_MODE=copy`**: required when cache mount crosses filesystems
- **`UV_PYTHON_DOWNLOADS=never`**: use the image's Python, don't download
- **Non-root user**: security best practice

### 3.2 docker-compose.dev.yml

```yaml
services:
  backend:
    build: .
    ports:
      - '8000:8000'
    volumes:
      - db-data:/app/data
    environment:
      - VAULTSPEC_DATABASE_URL=sqlite+aiosqlite:////app/data/vaultspec.db
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
      - OTEL_EXPORTER_OTLP_INSECURE=true
    depends_on:
      - jaeger

  frontend:
    image: node:22-alpine
    working_dir: /app/src/ui
    command: npm run dev -- --host 0.0.0.0
    ports:
      - '5173:5173'
    volumes:
      - ./src/ui:/app/src/ui

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - '4317:4317' # OTLP gRPC receiver
      - '4318:4318' # OTLP HTTP receiver
      - '16686:16686' # Jaeger UI — http://localhost:16686
    environment:
      - COLLECTOR_OTLP_ENABLED=true

volumes:
  db-data:
```text

**Usage:**

- `docker compose up` — starts all three services
- `http://localhost:8000` — backend API
- `http://localhost:5173` — frontend dev server (HMR)
- `http://localhost:16686` — Jaeger trace UI

### 3.3 .devcontainer/devcontainer.json

```json
{
  "name": "vaultspec-a2a",
  "image": "mcr.microsoft.com/devcontainers/base:debian-12",
  "features": {
    "ghcr.io/devcontainers/features/python:1": { "version": "3.13" },
    "ghcr.io/devcontainers/features/node:1": { "version": "22" },
    "ghcr.io/jsburckhardt/devcontainer-features/uv:1": {}
  },
  "postCreateCommand": "just setup",
  "forwardPorts": [8000, 5173, 16686],
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "charliermarsh.ruff",
        "React.React-vscode",
        "tamasfe.even-better-toml"
      ]
    }
  }
}
```text

### 3.4 .dockerignore

```text
# VCS
.git/
.gitignore

# Python
.venv/
__pycache__/
*.pyc
*.egg-info/
dist/
build/

# Node
node_modules/
src/ui/.React-kit/

# Project
knowledge/
legacy-docs/
tests/
*.db
*.db-wal
*.db-shm
.env
.claude/
```text

### 3.5 SQLite Persistence

The database file lives at `/app/data/vaultspec.db` inside the container,
backed by a named Docker volume (`db-data`). The WAL and SHM files are
co-located automatically.

**Critical constraint**: Only one container may access the SQLite file at
a time. The single-container architecture satisfies this. If future
scaling requires multiple backend instances, SQLite must be replaced with
PostgreSQL (or Turso/libSQL for distributed SQLite).

## 4. Consequences

### 4.1 Positive

- **Cross-platform verification**: `docker compose up` works identically
  on Windows, macOS, and Linux.
- **Instant observability**: Jaeger is always running — OTel traces are
  visible immediately at `http://localhost:16686`.
- **One-command onboarding**: `docker compose up` or VS Code "Reopen in
  Container" — no manual tool installation.
- **Production-ready image**: Multi-stage build produces a slim,
  non-root, compiled-bytecode image.
- **Layer caching**: Two-phase uv sync means code changes don't trigger
  full dep reinstall.

### 4.2 Negative

- **Docker Desktop required**: Windows developers need Docker Desktop
  installed — adds a ~2GB install requirement.
- **Not suitable for multi-instance scaling**: SQLite WAL limits the
  architecture to single-container. Horizontal scaling requires a
  database migration.
- **Build time**: Multi-stage build takes ~2-3 minutes on first run
  (Node + Python deps). Subsequent builds are fast via layer cache.

### 4.3 Neutral

- Docker is for deployment and cross-platform dev. Local native dev
  (PWSH + `just dev`) remains the primary workflow — Docker is an
  alternative, not a replacement.

## 5. Compliance Matrix

| ADR                     | Relationship                                                     | Status    |
| ----------------------- | ---------------------------------------------------------------- | --------- |
| ADR-007 (Tech Stack)    | Implements — FastAPI serves SPA + API in single container        | Compliant |
| ADR-010 (Observability) | Enforces — Jaeger sidecar consumes mandatory OTel traces         | Compliant |
| ADR-015 (Dep Hygiene)   | Depends — clean dep surface enables cross-platform Docker builds | Compliant |
| ADR-016 (Task Runner)   | Integrates — `just docker-build`, `just docker-dev` recipes      | Compliant |
