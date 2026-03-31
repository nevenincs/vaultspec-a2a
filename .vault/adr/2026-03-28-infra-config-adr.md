---
tags:
  - '#adr'
  - '#infra-config'
date: '2026-03-28'
related:
  - '[[2026-03-28-infra-config-research]]'
  - '[[2026-03-28-post-layer2d-boundary-audit]]'
  - '[[2026-03-28-layer2d-rolling-audit]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `infra-config` adr: layer 3 infrastructure config cleanup | (**status:** `accepted`)

## Problem Statement

After completing Layers 1–2d (PRs #2–#15), the codebase has clean
domain/infrastructure boundaries at the code level, but Layer 3 —
infrastructure config — has accumulated three categories of debt:

- **Settings coupling:** 7 production files import the full `settings`
  singleton (75+ infrastructure fields) when they only access DomainConfig
  fields. This creates unnecessary coupling between API route modules and
  infrastructure config.

- **Docker topology bugs:** A stale volume mount in
  `docker-compose.integration.yml` points to a path removed during Layer 1
  decomposition, silently breaking VidaiMock tape loading. An orphan compose
  file (`docker-compose.postgres.yml`) duplicates functionality with a bug.

- **Build context bloat and hygiene:** `.dockerignore` is missing `.vault/`
  and `.vaultspec/` exclusions. `.env.example` is missing one InfraConfig
  field. Justfile has a misleading backward-compat comment.

## Considerations

- The settings footprint analysis shows 37 production files importing
  `settings`. Only 7 are domain-only — the remaining 30 legitimately need
  infrastructure fields (API keys, URLs, ports, DB config).

- The `DomainConfig` singleton (`domain_config`) already exists as a
  separate module-level object in `domain_config.py`. No new abstraction
  is required — just import redirection.

- `InfraConfig` is already a single well-factored class. Further
  decomposition (e.g., extracting `McpConfig`, `WorkerConfig`) would
  increase complexity without proportionate benefit at this stage.

- Docker compose consolidation beyond deleting the orphan is out of scope.
  The 5 remaining compose files serve distinct purposes (dev, prod,
  postgres overlay, provider overlay, integration).

- Justfile structural changes (service topology extraction, stop/kill
  deduplication) are deferred to the service layer work.

## Constraints

- No backwards-compat shims. Old import paths break loudly.
- No file may exceed 1,000 lines.
- Test suite must remain green (>= 520 core, >= 574 middleware, >= 1,094 total).
- No mocks, stubs, fakes, patches, skips.
- Merge commits only.
- Must not touch Layer 1 packages, Layer 2 entry points beyond the 7
  domain-only files, or Layer 2d modules.

## Implementation

### Phase 1: Settings decoupling (Track A)

**Step 1a:** Add `env_file=".env"` and `env_file_encoding="utf-8"` to
`DomainConfig.model_config` in `domain_config.py`. Without this,
`DomainConfig` reads only from process environment variables while
`Settings` also reads from `.env` files. Adding `.env` loading ensures
runtime equivalence — both singletons resolve the same value for shared
fields like `graph_recursion_limit`.

**Step 1b:** Switch 7 files from `from ..control.config import settings`
to `from ..domain_config import domain_config`:

- `api/ws_dispatch.py` — replace `settings.graph_recursion_limit` with
  `domain_config.graph_recursion_limit`
- `api/routes/cancel.py` — same field
- `api/routes/messages.py` — same field
- `api/routes/permissions.py` — same field (note: inline import inside
  function body, not module-level)
- `api/routes/threads.py` — same field
- `control/dispatch.py` — same field
- `worker/graph_lifecycle.py` — replace `settings.max_cached_graphs` with
  `domain_config.max_cached_graphs`
- `worker/executor.py` — replace `settings.graph_recursion_limit` with
  `domain_config.graph_recursion_limit` (mixed file: retains `settings`
  for `max_concurrent_threads`)

This is a mechanical import swap — no logic changes, no new abstractions.
Each file touches the import line and one or more field access sites.

### Phase 2: Docker/Compose fixes (Track B)

- Fix `docker-compose.integration.yml` vidaimock volume mount:
  `core/presets/mock/tapes` → `team/presets/mock/tapes`

- Delete `docker-compose.postgres.yml` (orphan with missing
  `CHECKPOINT_DATABASE_URL` bug, not referenced by Justfile or active docs)

- Update `.dockerignore` to add: `.vault/`, `.vaultspec/`, `Justfile`,
  `docker-compose*.yml`, specific root-level markdown files
  (`CLAUDE.md`, `CONTRIBUTING.md`, `CHANGELOG.md`), `.pre-commit-config.yaml`.
  Do NOT use bare `*.md` glob — it would exclude `src/vaultspec_a2a/README.md`
  and `docker/README.md` from the build context due to non-anchored matching.

- Update `docker/README.md` to remove references to the deleted orphan
  compose file

### Phase 3: Hygiene (Track C)

- Add `VAULTSPEC_ACP_INTERACTIVE_AUTH_TIMEOUT_SECONDS` to `.env.example`
  (present in `InfraConfig` but missing from `.env.example`)

- Fix misleading `preps` comment in Justfile: remove the "backward compat"
  label and the incorrect redirect to `just dev test mock` (they are
  different commands — `preps` runs integration scenarios, `dev test mock`
  runs pytest)

## Rationale

- **Minimal blast radius:** All changes are mechanical or config-only. No
  business logic changes. No new abstractions.

- **Measurable outcome:** Settings footprint drops from 37 → 30 production
  files (19% reduction). The 5 API route modules become fully decoupled
  from infrastructure config.

- **Bug fix:** The stale tapes mount is a silent failure that makes
  VidaiMock integration testing non-functional in Docker.

- **No further InfraConfig decomposition:** Research confirmed the
  remaining 30-file footprint is legitimate. Creating sub-configs
  (McpConfig, WorkerConfig, etc.) would add indirection without reducing
  the coupling that matters.

## Consequences

- **Import paths change for 8 files.** Any code that previously relied on
  `settings.graph_recursion_limit` being the canonical access pattern in
  API routes now uses `domain_config.graph_recursion_limit`. The value is
  identical at runtime (both read from the same env vars and `.env` file).

- **`docker-compose.postgres.yml` is deleted.** Anyone who had custom
  scripts referencing this file must switch to
  `docker-compose.prod.postgres.yml`. The Justfile already uses the prod
  variant exclusively.

- **`.dockerignore` additions** reduce build context size. No functional
  impact on images (excluded paths were never COPY'd into images).

- **Dual-source risk:** After Phase 1, `graph_recursion_limit` is served
  by `domain_config` in 7 files and by `settings` in the remaining files
  (notably `worker/executor.py`). Step 1a (adding `.env` loading to
  `DomainConfig`) mitigates the divergence risk. Both singletons read the
  same env vars from the same sources.

- **Deferred items** (service topology extraction, `max_concurrent_threads`
  relocation, Justfile structural cleanup, `docker-compose.prod.postgres.yml`
  hardcoded credentials) remain tracked for the service layer PR.
