---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S82'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Authenticate the development Compose worker healthcheck without adopting it into desktop lifecycle

## Scope

- `service/docker-compose.dev.yml`

## Description

- Replaced the unauthenticated `urllib.request.urlopen` probe in the dev worker healthcheck with a `urllib.request.Request` call that reads `VAULTSPEC_INTERNAL_TOKEN` via `os.environ.get` (optional in dev) and adds the Bearer header only when the token is present.
- Dev worker lifecycle remains separate from desktop; no new env vars injected, no topology changes.
- YAML validated via PyYAML.

## Outcome

`service/docker-compose.dev.yml` worker healthcheck is now auth-aware: it presents the IPC bearer when `VAULTSPEC_INTERNAL_TOKEN` is set, and falls back to an unauthenticated probe otherwise. In default dev mode (no token, DEVELOPMENT environment) the worker permits the unauthenticated probe; when a developer runs dev with a token the credential is forwarded correctly.

## Notes

Dev compose does not set `VAULTSPEC_INTERNAL_TOKEN` by default; the `os.environ.get` path keeps the zero-config dev workflow intact.
