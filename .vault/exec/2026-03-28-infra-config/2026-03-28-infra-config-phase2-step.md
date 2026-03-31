---
tags:
  - '#exec'
  - '#infra-config'
date: '2026-03-28'
related:
  - '[[2026-03-28-infra-config-plan]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `infra-config` phase-2 docker-compose-fixes

Fixed Docker topology bugs left by Layer 1 decomposition.

- Modified: `docker-compose.integration.yml` — tapes volume mount path
- Deleted: `docker-compose.postgres.yml` — orphan with bug
- Modified: `.dockerignore` — added 6 exclusions
- Modified: `docker/README.md` — fixed orphan reference + markdownlint

## Description

The VidaiMock tapes volume mount in `docker-compose.integration.yml`
pointed to `core/presets/mock/tapes` — a path that ceased to exist
when Layer 1 moved presets to `team/presets/mock/tapes`. Docker
silently created an empty directory, making VidaiMock start with no
tapes.

The orphan `docker-compose.postgres.yml` was a legacy duplicate of
`docker-compose.prod.postgres.yml` with a missing
`VAULTSPEC_CHECKPOINT_DATABASE_URL` bug and no Justfile or CI references.

`.dockerignore` was updated to exclude `.vault/`, `.vaultspec/`,
`Justfile`, `docker-compose*.yml`, `CLAUDE.md`, and
`.pre-commit-config.yaml` — reducing build context size without
affecting image contents.

## Tests

- Pre-commit hooks: all passed (including markdownlint)
- Compose file validation: 5 compose files remain, orphan confirmed gone
