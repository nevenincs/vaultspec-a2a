---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:e6073f6a2f3d094b9d24ee9aa29ddc3c7f2901b054d4acde25eeb41793ef4cd3'
step_id: 'S47'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Conform readiness/drain/shutdown routes and ownership capability handling to the intended consumer generation with fail-closed incompatible attachment

## Scope

- `src/vaultspec_a2a/api/routes/admin.py`

## Changes

- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-robustness-audit.md`
- `A` `.vault/audit/2026-09-06-embedded-runtime-remediation-w04-p10-s47-cooperative-server-owner-review-audit.md`
- `A` `.vault/audit/2026-09-06-embedded-runtime-remediation-w04-p10-s47-cooperative-server-owner-rereview-audit.md`
- `M` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W04-P10-S47.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `M` `.vault/plan/2026-09-05-embedded-runtime-remediation-plan.md`
- `M` `.vault/research/2026-09-05-embedded-runtime-remediation-research.md`
- `M` `src/vaultspec_a2a/api/app.py`
- `M` `src/vaultspec_a2a/api/routes/admin.py`
- `M` `src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py`
- `M` `src/vaultspec_a2a/api/tests/test_gateway_drain.py`
- `verify:` `uv run --locked ruff check src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/routes/admin.py src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py src/vaultspec_a2a/api/tests/test_gateway_drain.py` -> `pass`
- `verify:` `uv run --locked ty check src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/routes/admin.py src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py` -> `pass`
- `verify:` `uv run --locked python -m pytest src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py src/vaultspec_a2a/api/tests/test_gateway_drain.py -q` -> `pass` (15 passed in 35.79s)
- `verify:` implementation/review chain `24dab547465e2bb846dfba0f8b9d87e95c41b7e8` -> `b80e843ba63ae48f45c322957b23f98e70e2aa94` FAIL -> `b83ad5ba87c00d9aeb82af39cd677f5f2acd2030` -> `2279eb52d529ee338661006779a0143095003ce7` PASS
- `verify:` real Uvicorn HTTP shutdown -> `pass` (authenticated 202 observed before serving-task exit; `should_exit` observed; bounded completion in 0.61 seconds during rereview)
- `verify:` incompatible owner handling -> `pass` (absent and malformed owners return 503; admission remains OPEN)
- `verify:` archived exact-correction focused gate -> `pass` (15 passed in 12.84 seconds)
- `verify:` `git diff --check` and remediation Core checks -> `pass` (19 checks; zero diagnostics)
- `verify:` no-legacy/no-deprecated boundary -> `pass` (no process-signal route, compatibility translation, deprecated API or discovery mutation)

## Notes

Formal review `b80e843b` failed the first implementation; correction `b83ad5ba` resolved all five findings and formal rereview `2279eb52` passed. S47 owns `_bind_server_shutdown_owner` and its `main` call in `api/app.py`. S49 separately owns the total deadline, stream drain, owned-child cleanup and forced escalation around that seam; ER15 remains open only for that S49 closure. S48 discovery remains unchanged.
