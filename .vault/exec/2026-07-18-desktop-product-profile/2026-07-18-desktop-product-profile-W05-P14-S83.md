---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S83'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S83 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Authenticate the integration Compose worker healthcheck while retaining VidaiMock and Jaeger certification and ## Scope

- `service/docker-compose.integration.yml` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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
