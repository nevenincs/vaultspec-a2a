---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
body_hash: 'sha256:702530e8d218dbc8ec8785f60d0fbc047f666be9fe1e7101469facc81015c9cb'
step_id: 'S83'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Authenticate the integration Compose worker healthcheck while retaining VidaiMock and Jaeger certification

## Scope

- `service/docker-compose.integration.yml`

## Description

- Replaced the unauthenticated `urllib.request.urlopen` probe in the integration worker healthcheck with an authenticated `urllib.request.Request` call using `os.environ['VAULTSPEC_INTERNAL_TOKEN']` (hardcoded as `'vaultspec-integration-token'` in the stack).
- VidaiMock and Jaeger service definitions, their healthchecks, and all port mappings retained unchanged.
- YAML validated via PyYAML.

## Outcome

`service/docker-compose.integration.yml` worker healthcheck presents the IPC bearer. Docker's `condition: service_healthy` dependency chain (gateway waits for worker, worker waits for jaeger + vidaimock) now works end-to-end with the gated `/health` endpoint.

## Notes

Integration token is hardcoded to a deterministic test value (`vaultspec-integration-token`); the unconditional `os.environ['VAULTSPEC_INTERNAL_TOKEN']` lookup is correct here since the environment declaration guarantees the variable is present.
