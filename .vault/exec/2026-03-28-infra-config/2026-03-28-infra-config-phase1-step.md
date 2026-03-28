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

# `infra-config` phase-1 settings-decoupling

Switched 8 production files from `settings` (75+ infra fields) to
`domain_config` (18 domain fields) for domain-only field access.

- Modified: `domain_config.py` — added `env_file=".env"` to `model_config`
- Modified: `api/ws_dispatch.py` — `domain_config.graph_recursion_limit`
- Modified: `api/routes/cancel.py` — same
- Modified: `api/routes/messages.py` — same
- Modified: `api/routes/permissions.py` — same (inline import)
- Modified: `api/routes/threads.py` — same
- Modified: `control/dispatch.py` — same
- Modified: `worker/graph_lifecycle.py` — `domain_config.max_cached_graphs`
- Modified: `worker/executor.py` — `domain_config.graph_recursion_limit`
  (review finding: was dual-source, fixed post-review)

## Description

Mechanical import swap: `from ..control.config import settings` →
`from ..domain_config import domain_config`. Each file touched only the
import line and field access sites. `DomainConfig.model_config` was
updated first (step 1a) to add `.env` file loading, ensuring runtime
equivalence with `Settings` for shared fields.

Code review identified `worker/executor.py` as a missed dual-source
for `graph_recursion_limit` — fixed in a follow-up commit.

## Tests

- `pytest -m core`: 520 passed
- `pytest -m middleware`: 574 passed
- `pytest`: 1,094 passed
- `ruff check .`: clean
- `ty check`: clean
- Pre-commit hooks: all passed
