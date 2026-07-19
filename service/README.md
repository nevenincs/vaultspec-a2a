# Service containers

This directory contains the headless gateway, worker, telemetry, mock-provider,
and database container definitions. It does not contain or start a user
interface.

## Docker Compose profiles

| File | Role |
| --- | --- |
| `docker-compose.dev.yml` | Gateway and worker with shared SQLite storage |
| `docker-compose.integration.yml` | Gateway, worker, VidaiMock, and Jaeger certification stack |
| `docker-compose.prod.yml` | Gateway, worker, and Jaeger with shared SQLite storage |
| `docker-compose.prod.postgres.yml` | Overlay that adds PostgreSQL and switches both application services to it |

Run every command from the repository root. Use `just doctor` to check Docker,
then validate a Docker Compose (Compose) configuration before starting it.

## Development stack

```console
just dev stack dev-config
just dev stack dev-up
just dev stack dev-status
just dev stack dev-down
```

The gateway is published at <http://localhost:18000>. The worker remains on the
Compose network and is not published to the host.

## Integration stack

```console
just dev stack integration-config
just dev stack integration-up
just dev stack integration-status
just dev stack integration-down
```

The stack publishes the gateway at <http://localhost:18000>, VidaiMock at
<http://localhost:8100>, and the Jaeger user interface (UI) at
<http://localhost:16686>.

## Production-image stack

Set a non-empty `VAULTSPEC_INTERNAL_TOKEN` in the repository-root `.env`, then
run the SQLite-backed production images:

```console
just dev stack prod-config
just dev stack prod-up
just dev stack prod-status
just dev stack prod-down
```

For PostgreSQL, also set `POSTGRES_PASSWORD`. The `database-*` recipes validate
the combined production configuration but start and manage only PostgreSQL:

```console
just dev stack database-config
just dev stack database-up
just dev stack database-status
just dev stack database-down
```

To run the complete PostgreSQL-backed application stack, combine the base file
and overlay in one isolated Compose project:

```console
docker compose --project-name vaultspec-a2a-prod-postgres -f service/docker-compose.prod.yml -f service/docker-compose.prod.postgres.yml config
docker compose --project-name vaultspec-a2a-prod-postgres -f service/docker-compose.prod.yml -f service/docker-compose.prod.postgres.yml up -d --build --wait
docker compose --project-name vaultspec-a2a-prod-postgres -f service/docker-compose.prod.yml -f service/docker-compose.prod.postgres.yml down --remove-orphans
```

See [`service/.env.example`](.env.example) for supported settings and the
[operator reference](../docs/operations.rst) for lifecycle ownership.
