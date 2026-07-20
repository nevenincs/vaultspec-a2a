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

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S81 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Authenticate the Compose worker healthcheck without changing its independently managed worker topology and ## Scope

- `service/docker-compose.prod.yml` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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
