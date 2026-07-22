---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S81'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Authenticate the Compose worker healthcheck without changing its independently managed worker topology

## Scope

- `service/docker-compose.prod.yml`

## Description

- Replaced the unauthenticated `urllib.request.urlopen` probe in the prod worker healthcheck with a `urllib.request.Request` call that reads `VAULTSPEC_INTERNAL_TOKEN` from the container environment and adds it as `Authorization: Bearer <tok>`.
- Topology unchanged: the worker remains an independently managed service; no restart policy, port mapping, or network configuration altered.
- YAML validated via PyYAML.

## Outcome

`service/docker-compose.prod.yml` worker healthcheck now presents the IPC bearer on `GET /health`, matching the credential gate introduced by commit 2760d11c. Docker will mark the worker healthy only when the gateway-worker IPC credential pair is intact.

## Notes

The prod compose already required `VAULTSPEC_INTERNAL_TOKEN` via `${VAULTSPEC_INTERNAL_TOKEN:?...}` so the healthcheck can unconditionally read it with `os.environ['VAULTSPEC_INTERNAL_TOKEN']` — no optional path needed.
