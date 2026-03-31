# service/

Docker Compose files, Dockerfiles, and environment configuration for
running the Vaultspec A2A orchestrator as containerised services.

## Compose files

| File | Type | Description |
|---|---|---|
| `docker-compose.dev.yml` | Standalone | Frontend-ready dev environment: gateway + worker + Vite HMR |
| `docker-compose.prod.yml` | Standalone | Single-node SQLite deployment: gateway + worker + Jaeger |
| `docker-compose.prod.postgres.yml` | Overlay | Adds Postgres to the prod stack (replaces SQLite) |

## Usage

All commands run from the **repository root** (not `service/`).

### Development (gateway + worker + Vite)

```sh
docker compose -f service/docker-compose.dev.yml up --build
```

- Gateway: <http://localhost:8000>
- Frontend: <http://localhost:5173> (HMR, proxied to the gateway)

### Production with SQLite

```sh
docker compose -f service/docker-compose.prod.yml up --build
```

- Gateway: <http://localhost:8000>
- Jaeger UI: <http://localhost:16686>

### Production with Postgres (recommended)

```sh
docker compose \
  -f service/docker-compose.prod.yml \
  -f service/docker-compose.prod.postgres.yml \
  up --build
```

The Postgres overlay file **must** be combined with the base prod file.
It overrides database environment variables and adds the Postgres service.

## Environment

Copy `service/.env.example` to `.env` in the repo root and fill in the
required values. The Justfile `dotenv-load` reads `.env` from the repo
root automatically.
