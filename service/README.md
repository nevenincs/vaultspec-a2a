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
<http://127.0.0.1:16686>. Jaeger's UI and OTLP gRPC collector are bound to
127.0.0.1; host certification exports to `http://127.0.0.1:4317`.
`JAEGER_UI_PORT` and `JAEGER_OTLP_PORT` change those host ports without changing
the bind address. Container exporters still use `http://jaeger:4317`; OTLP HTTP
and health remain inside the Compose network. These restrictions also apply to
the infrastructure recipes, which use this same profile. Use Docker Engine
28.0.0 or newer and an authenticated TLS proxy with access controls and resource
limits for remote telemetry access.

## Production-image stack

Set a non-empty `VAULTSPEC_A2A_INTERNAL_TOKEN` in the repository-root `.env`, then
run the SQLite-backed production images:

```console
just stack-prod-config
just stack-prod-up
just stack-prod-status
just stack-prod-down
```

The Jaeger UI is available only on the host at <http://127.0.0.1:16686>
(`JAEGER_UI_PORT` changes the port). OTLP ingestion on ports 4317/4318 and the
health endpoint on port 13133 remain inside the Compose network; production
does not use `JAEGER_OTLP_PORT`. Gateway and worker export to `http://jaeger:4317`.
For remote telemetry access, use an authenticated TLS proxy with access controls
and resource limits instead of publishing Jaeger directly. Use Docker Engine
28.0.0 or newer: older engines can expose loopback-published ports to peers on
the same network segment.

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

### Released container images

Changes go through the PR merge gate. Post-merge Full Validation also builds
the committed production worker and runs its MCP identity-isolation proof.
Maintainers start a release through the existing cut workflow:

```console
gh workflow run release-please.yml --ref main
```

The release lane builds Linux AMD64 gateway and worker images from the same
release tag. It proves the worker before pushing to
`ghcr.io/nevenincs/vaultspec-a2a-gateway` and
`ghcr.io/nevenincs/vaultspec-a2a-worker`, then attaches an attested
`container-release.json` containing the source commit and immutable image
digests. The release remains a draft until both container publication and the
existing archive cohort succeed. Registry build tags are candidates; use the
digests in a published release receipt for deployment.

GitHub Actions needs package-write and attestation permissions. Existing GHCR
packages must grant this repository access. Publishing does not restart any
service. No production destination is currently configured; deployment host
enrollment and promotion setup remain required.
