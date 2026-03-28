---
tags:
  - '#exec'
  - '#infra-config'
date: '2026-03-28'
related:
  - '[[2026-03-28-infra-config-plan]]'
  - '[[2026-03-28-infra-config-adr]]'
  - '[[2026-03-28-infra-config-research]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `infra-config` summary

Layer 3 infrastructure config cleanup: settings decoupling, Docker/Compose
fixes, and hygiene. All 3 phases executed successfully with 4 commits.

- Modified: `domain_config.py`, `api/ws_dispatch.py`, `api/routes/cancel.py`,
  `api/routes/messages.py`, `api/routes/permissions.py`, `api/routes/threads.py`,
  `control/dispatch.py`, `worker/graph_lifecycle.py`, `worker/executor.py`
- Modified: `docker-compose.integration.yml`, `.dockerignore`, `docker/README.md`
- Modified: `.env.example`, `Justfile`, `README.md`
- Deleted: `docker-compose.postgres.yml`

## Description

**Phase 1 — Settings decoupling:** Switched 8 production files from
`settings` to `domain_config` for domain-only field access. Added
`env_file=".env"` to `DomainConfig.model_config` for runtime equivalence.
Settings import footprint reduced from 37 → 29 production files (22%).

**Phase 2 — Docker/Compose fixes:** Fixed stale VidaiMock tapes volume
mount (`core/` → `team/`). Deleted orphan `docker-compose.postgres.yml`.
Updated `.dockerignore` with 6 new exclusions. Fixed `docker/README.md`.

**Phase 3 — Hygiene:** Added missing `VAULTSPEC_ACP_INTERACTIVE_AUTH_TIMEOUT_SECONDS`
to `.env.example`. Fixed misleading `preps` Justfile comments.

**Code review fix:** `worker/executor.py` was identified as dual-sourcing
`graph_recursion_limit` from `settings` while other files had switched to
`domain_config`. Fixed in a follow-up commit.

## Tests

- `pytest -m core`: 520 passed (baseline: >= 520)
- `pytest -m middleware`: 574 passed (baseline: >= 574)
- `pytest`: 1,094 passed (baseline: >= 1,094)
- `ruff check .`: clean
- `ty check`: clean
- Pre-commit hooks: all passed on all 4 commits
