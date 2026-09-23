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

Run every command from the repository root. Use `just doctor-check` to check Docker,
then validate a Docker Compose (Compose) configuration before starting it.

## Development stack

```console
just stack-dev-config
just stack-dev-up
just stack-dev-status
just stack-dev-down
```

The gateway is published at <http://localhost:18000>. The worker remains on the
Compose network and is not published to the host.

Every engine-facing `/v1` request requires the gateway bearer. In the supplied
Compose profiles, accepted workspaces are canonical descendants of
`/app/data/workspaces`; foreign, ancestor, and symlink-escaping roots are
refused before project configuration is read. Provider and tool processes run
as a separate `agentuser` identity. They can read and write admitted projects,
but cannot read the service-owned SQLite database or token handoff. Gateway and
worker discovery state also use separate volumes. The worker safely upgrades
existing files in shipped named volumes for shared GID 1002 access. Operators
adding bind mounts must place them beneath the configured workspace root, set
`VAULTSPEC_A2A_MANAGED_WORKSPACE_PERMISSIONS=false`, and prepare their contents for
group 1002 access; startup validates the root rather than recursively changing
host files. This remains a trusted single-control-plane profile, not a
tenant-isolation boundary.

Set `VAULTSPEC_A2A_GATEWAY_TOKEN` in the repository-root `.env` to pin the
gateway bearer. If it is unset, the gateway generates one and writes it to the
owner-restricted `service.token` handoff beside `service.json` in the
gateway-only `VAULTSPEC_A2A_HOME` volume. Send it as
`Authorization: Bearer <token>`; the separate `VAULTSPEC_A2A_INTERNAL_TOKEN` is
only for gateway-to-worker traffic and is removed from provider environments.

## Integration stack

```console
just stack-integration-config
just stack-integration-up
just stack-integration-status
just stack-integration-down
```

The stack publishes the gateway at <http://localhost:18000>, VidaiMock at
<http://localhost:8100>, and the Jaeger user interface (UI) at
<http://localhost:16686>.

## Production-image stack

Set a non-empty `VAULTSPEC_A2A_INTERNAL_TOKEN` in the repository-root `.env`, then
run the SQLite-backed production images:

```console
just stack-prod-config
just stack-prod-up
just stack-prod-status
just stack-prod-down
```

For PostgreSQL, also set `POSTGRES_PASSWORD`. The `database-*` recipes validate
the combined production configuration but start and manage only PostgreSQL:

```console
just stack-database-config
just stack-database-up
just stack-database-status
just stack-database-down
```

To run the complete PostgreSQL-backed application stack, combine the base file
and overlay in one isolated Compose project:

```console
docker compose --project-name vaultspec-a2a-prod-postgres -f service/docker-compose.prod.yml -f service/docker-compose.prod.postgres.yml config
docker compose --project-name vaultspec-a2a-prod-postgres -f service/docker-compose.prod.yml -f service/docker-compose.prod.postgres.yml up -d --build --wait
docker compose --project-name vaultspec-a2a-prod-postgres -f service/docker-compose.prod.yml -f service/docker-compose.prod.postgres.yml down --remove-orphans
```

See [`.env.example`](../.env.example) for supported settings and the
[operator reference](../docs/operations.rst) for lifecycle ownership.
