---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:b148494f8c923da6098a3fb9459fe77c618a78e89b257c7314ed733c314faeb2'
step_id: 'S76'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Declare durable run revision and writer generation plus action-specific receipt identity without storing credentials or duplicating transcript authority

## Scope

- `src/vaultspec_a2a/database/models.py`

## Changes

- `M` `src/vaultspec_a2a/database/models.py`
- `A` `src/vaultspec_a2a/database/tests/test_run_write_authority_model.py`
- `M` `.vault/research/2026-09-05-embedded-runtime-remediation-research.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `verify:` `uv run --no-sync pytest src/vaultspec_a2a/database/tests/test_run_write_authority_model.py src/vaultspec_a2a/database/tests/test_schema_parity.py src/vaultspec_a2a/database/tests/test_database.py -q` -> `pass` (131 passed in 6.38s)
- `verify:` `uv run --no-sync ruff check src/vaultspec_a2a/database/models.py src/vaultspec_a2a/database/tests/test_run_write_authority_model.py` -> `pass`
- `verify:` `uv run --no-sync ty check src/vaultspec_a2a/database/models.py src/vaultspec_a2a/database/tests/test_run_write_authority_model.py` -> `pass`
- `verify:` `uv run --no-sync vaultspec-core vault check all --feature embedded-runtime-remediation` -> `pass` (19 checks)
