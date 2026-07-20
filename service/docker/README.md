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
just dev build docker-prod
```

### `vidaimock.Dockerfile`

The integration profile uses this image for deterministic model responses. It
is not part of the development or production profiles.

### `dev.Dockerfile`

This file retains a standalone `python-base` development image definition. The
current Compose and Just recipes do not select it; `just dev build docker`
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
just dev stack help
just dev stack dev-config
just dev stack integration-config
just dev stack prod-config
just dev stack database-config
```

The gateway and worker share one `VAULTSPEC_INTERNAL_TOKEN` in production
profiles. The PostgreSQL overlay additionally requires `POSTGRES_PASSWORD`.
Mutable runtime state belongs to the configured volumes or application runtime
directories, not the image layers.

See the [service overview](../README.md) for startup commands and the
[operator reference](../../docs/operations.rst) for the Compose ownership
boundary.
