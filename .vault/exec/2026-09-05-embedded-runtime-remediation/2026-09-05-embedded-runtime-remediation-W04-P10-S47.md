---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:85ebb6087df5d6e30044f693150b6cde3e9c076f872d0291c569dc2675d38273'
step_id: 'S47'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---

# Conform readiness/drain/shutdown routes and ownership capability handling to the intended consumer generation with fail-closed incompatible attachment

## Scope

- `src/vaultspec_a2a/api/routes/admin.py`

## Changes

- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `M` `.vault/research/2026-09-05-embedded-runtime-remediation-research.md`
- `M` `src/vaultspec_a2a/api/app.py`
- `M` `src/vaultspec_a2a/api/routes/admin.py`
- `M` `src/vaultspec_a2a/api/tests/test_gateway_drain.py`
- `verify:` `uv run --locked ruff check src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/routes/admin.py src/vaultspec_a2a/api/tests/test_gateway_drain.py` -> `pass`
- `verify:` `uv run --locked ty check src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/routes/admin.py` -> `pass`
- `verify:` `uv run --locked python -m pytest src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py src/vaultspec_a2a/api/tests/test_gateway_drain.py -q` -> `pass`
