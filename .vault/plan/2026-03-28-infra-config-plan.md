---
tags:
  - '#plan'
  - '#infra-config'
date: '2026-03-28'
related:
  - '[[2026-03-28-infra-config-adr]]'
  - '[[2026-03-28-infra-config-research]]'
  - '[[2026-03-28-post-layer2d-boundary-audit]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `infra-config` plan

Layer 3 infrastructure config cleanup: settings decoupling, Docker/Compose
fixes, and hygiene. Derived from accepted ADR.

## Proposed Changes

Reduce unnecessary coupling between Layer 2 entry points and
infrastructure config. Fix Docker topology bugs left by Layer 1
decomposition. Improve build context hygiene and documentation alignment.

## Tasks

- **Phase 1 — Settings decoupling**
  1. Add `.env` file loading to `DomainConfig.model_config` in
     `domain_config.py` — add `env_file=".env"` and
     `env_file_encoding="utf-8"` to ensure runtime equivalence with
     `Settings`
  1. Switch `api/ws_dispatch.py` from `settings` → `domain_config` import,
     replace `settings.graph_recursion_limit` access
  1. Switch `api/routes/cancel.py` — same pattern
  1. Switch `api/routes/messages.py` — same pattern
  1. Switch `api/routes/permissions.py` — inline import inside function
     body, same field
  1. Switch `api/routes/threads.py` — same pattern
  1. Switch `control/dispatch.py` — same pattern
  1. Switch `worker/graph_lifecycle.py` — replace
     `settings.max_cached_graphs` with `domain_config.max_cached_graphs`
  1. Run `pytest -m core` and `pytest -m middleware` to verify green suite
  1. Run lint (`ruff check .`) and type check (`ty check`) to verify clean
  1. Commit Phase 1

- **Phase 2 — Docker/Compose fixes**
  1. Fix `docker-compose.integration.yml` vidaimock volume mount path:
     `core/presets/mock/tapes` → `team/presets/mock/tapes`
  1. Delete orphan `docker-compose.postgres.yml`
  1. Update `.dockerignore` — add `.vault/`, `.vaultspec/`, `Justfile`,
     `docker-compose*.yml`, `CLAUDE.md`, `.pre-commit-config.yaml`
  1. Update `docker/README.md` — remove references to the deleted orphan
     compose file
  1. Commit Phase 2

- **Phase 3 — Hygiene**
  1. Add `VAULTSPEC_ACP_INTERACTIVE_AUTH_TIMEOUT_SECONDS` to `.env.example`
     in the ACP provider section
  1. Fix `preps` and `preps-list` comments in Justfile — remove misleading
     "backward compat" label and incorrect redirect to `dev test mock`
  1. Run full test suite (`pytest`) to confirm green
  1. Commit Phase 3

## Parallelization

Phases 1, 2, and 3 are independent — they touch disjoint file sets
(Python source, Docker/ignore config, and env/Justfile respectively).
They could execute in parallel but sequential execution with a commit
per phase is preferred for clean git history and easier rollback.

Within Phase 1, steps 1.2–1.8 (the 7 import swaps) are independent of
each other and could be parallelized via subagents. **Constraint:** step
1.1 (`DomainConfig` env_file fix) MUST complete before any import swap
starts — otherwise `.env`-only values would silently diverge between
`domain_config` and `settings`.

## Verification

- **Test baseline:** `pytest -m core` >= 520, `pytest -m middleware` >= 574,
  `pytest` >= 1,094
- **Import footprint:** `grep -rn 'from.*control\.config import settings'`
  in the 7 switched files must return zero matches after Phase 1
- **Boundary check:** Layer 1 modules must not import from Layer 2+ (run
  the boundary violation grep from `README.md`)
- **Docker:** `docker-compose.postgres.yml` must not exist after Phase 2.
  The tapes path in `docker-compose.integration.yml` must point to
  `team/presets/mock/tapes`
- **Lint/type:** `ruff check .` and `ty check` must pass
- **.env.example:** `VAULTSPEC_ACP_INTERACTIVE_AUTH_TIMEOUT_SECONDS` must
  be present
- **`.dockerignore` safety:** No bare `*.md` glob — only specific
  root-level filenames. Verify `src/vaultspec_a2a/README.md` is NOT
  excluded by running a build context check
- **DomainConfig env_file:** Confirm `domain_config.py` has
  `env_file=".env"` in `model_config` after Phase 1 step 1.1
