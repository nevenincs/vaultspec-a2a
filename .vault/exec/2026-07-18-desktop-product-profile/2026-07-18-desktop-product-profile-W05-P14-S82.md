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

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S82 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Authenticate the development Compose worker healthcheck without adopting it into desktop lifecycle and ## Scope

- `service/docker-compose.dev.yml` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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
