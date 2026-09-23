# Docker build definitions

Vaultspec agent-to-agent (A2A) is headless. These Dockerfiles build backend
services and provider runtimes; no target builds or embeds a frontend. Docker
Compose is shortened to Compose below.

## Files and targets

### `prod.Dockerfile`

All profiles that build application services use this file. Its runnable
targets are:

- `gateway`: the FastAPI control surface on port 18000.
- `worker`: the graph executor on port 18001. It includes the pinned Node.js
  provider runtimes used by the Claude Agent Client Protocol (ACP) and Gemini
  command-line interface (CLI) paths.

Build both targets without starting Compose:

```console
just build-docker-prod
```

### `vidaimock.Dockerfile`

The integration profile uses this image for deterministic model responses. It
is not part of the development or production profiles.

### `dev.Dockerfile`

This file retains a standalone `python-base` development image definition. The
current Compose and Just recipes do not select it; `just build-docker`
builds the gateway and worker declared by `docker-compose.dev.yml`, which both
use `prod.Dockerfile`.

## Compose mapping

| Compose file | Images and services |
| --- | --- |
| `docker-compose.dev.yml` | `prod.Dockerfile` gateway and worker targets |
| `docker-compose.integration.yml` | Production gateway and worker targets, `vidaimock.Dockerfile`, and the upstream Jaeger image |
| `docker-compose.prod.yml` | Production gateway and worker targets plus the upstream Jaeger image |
| `docker-compose.prod.postgres.yml` | Upstream PostgreSQL 16 overlay; no additional project image |

Use the repository-owned stack recipes rather than inventing service lifecycle
commands:

```console
just --list
just stack-dev-config
just stack-integration-config
just stack-prod-config
just stack-database-config
```

The gateway and worker share one `VAULTSPEC_A2A_INTERNAL_TOKEN` in production
profiles. The PostgreSQL overlay additionally requires `POSTGRES_PASSWORD`.
Mutable runtime state belongs to the configured volumes or application runtime
directories, not the image layers.

The engine-facing gateway bearer is separate from
`VAULTSPEC_A2A_INTERNAL_TOKEN`. The shipped profiles admit only canonical
descendants of `/app/data/workspaces`. Provider, MCP, and terminal descendants
are launched as UID/GID 1002 with no supplementary groups, capabilities, or
privilege-regain path; the service retains UID/GID 1001 for SQLite and runtime
state. The gateway token handoff and worker discovery state live in distinct,
service-only volumes. Existing files in shipped named-volume workspaces are
upgraded at worker startup for shared GID 1002 access without following
symlinks; hard-linked, special, or foreign-owned files fail startup. Custom
bind mounts must sit beneath the configured workspace root, set
`VAULTSPEC_A2A_MANAGED_WORKSPACE_PERMISSIONS=false`, and be prepared by the operator
for group 1002 access. Their contents are not recursively rewritten. Set
`VAULTSPEC_A2A_GATEWAY_TOKEN` to pin the bearer or read the
generated `service.token` from the gateway volume. This is a trusted control
plane and makes no multi-tenant isolation claim.

See the [service overview](../README.md) for startup commands and the
[operator reference](../../docs/operations.rst) for the Compose ownership
boundary.
