---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:cf1520f8b45a1dbd4c6738af2688b6a1f9068a2819f0f9e6f272de965fceb657'
step_id: 'S47'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Conform readiness/drain/shutdown routes and ownership capability handling to the intended consumer generation with fail-closed incompatible attachment

## Scope

- `src/vaultspec_a2a/api/routes/admin.py`

## Changes

- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `M` `.vault/research/2026-09-05-embedded-runtime-remediation-research.md`
- `M` `src/vaultspec_a2a/api/app.py`
- `M` `src/vaultspec_a2a/api/routes/admin.py`
- `M` `src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py`
- `M` `src/vaultspec_a2a/api/tests/test_gateway_drain.py`
- `verify:` `uv run --locked ruff check src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/routes/admin.py src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py src/vaultspec_a2a/api/tests/test_gateway_drain.py` -> `pass`
- `verify:` `uv run --locked ty check src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/routes/admin.py src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py` -> `pass`
- `verify:` `uv run --locked python -m pytest src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py src/vaultspec_a2a/api/tests/test_gateway_drain.py -q` -> `pass` (15 passed in 35.79s)

## Notes

Formal review `b80e843b` failed the first implementation. The correction validates callable owner shape before admission changes, proves absent and malformed owners keep admission OPEN, and drives the named production Uvicorn binding over real HTTP. S47 owns `_bind_server_shutdown_owner` and its `main` call in `api/app.py`; S49 separately owns the total deadline, stream drain and forced-escalation evolution around that seam. S48 discovery remains unchanged. S47 stays open for rereview.
