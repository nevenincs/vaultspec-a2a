---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-09-20'
body_schema: 'body-v2'
body_hash: 'sha256:6e1752e5c1b4c7028e030c64e90e523d442c69492dc2c339576810cc59554898'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---

# `resource-aware-test-execution` ledger

## Changes

- `S01` `T` `pyproject.toml`
- `S02` `T` `src/vaultspec_a2a/testing/resources.py`
- `S03` `T` `src/vaultspec_a2a/testing/leases.py`
- `S04` `T` `src/vaultspec_a2a/testing/progress.py`
- `S05` `T` `src/vaultspec_a2a/testing/endpoints.py`
- `S06` `T` `src/vaultspec_a2a/testing/plugin.py`
- `S07` `T` `src/vaultspec_a2a/conftest.py`
- `S08` `T` `src/vaultspec_a2a/service_tests/test_pw7_acceptance.py`
- `S09` `T` `src/vaultspec_a2a/testing/tests/`
- `S10` `T` `pyproject.toml`
- `S11` `T` `src/vaultspec_a2a/control/config.py`
- `S12` `T` `src/vaultspec_a2a/testing/ports.py`
- `S13` `T` `src/vaultspec_a2a`
- `S14` `T` `src/vaultspec_a2a/tests/gateway_boot.py`
- `S15` `T` `src/vaultspec_a2a/testing/sessions.py`
- `S16` `T` `src/vaultspec_a2a/testing/tests/`
- `S17` `T` `pyproject.toml`
- `S18` `T` `src/vaultspec_a2a/tests/gateway_boot.py`
- `S19` `T` `src/vaultspec_a2a/testing/`
- `S20` `T` `src/vaultspec_a2a/testing/tests/`
- `S21` `T` `dev/toolchain.py`
- `S22` `M` `src/vaultspec_a2a/control/action_lease.py`
- `S22` `M` `src/vaultspec_a2a/control/permission_service.py`
- `S22` `M` `src/vaultspec_a2a/control/tests/test_dispatch_receipts.py`
- `S22` `M` `.vault/audit/2026-08-02-resource-aware-test-execution-audit.md`
- `S22` `verify:` `ruff, ty, basedpyright` -> `pass`
- `S22` `by:` `vaultspec-high-executor`
- `S23` `M` `.vault/plan/2026-08-02-resource-aware-test-execution-plan.md`
- `S23` `M` `.vault/audit/2026-08-02-resource-aware-test-execution-audit.md`
- `S23` `M` `src/vaultspec_a2a/control/worker_management.py`
- `S23` `M` `src/vaultspec_a2a/control/tests/test_worker_health_probe.py`
- `S23` `verify:` `uv run pytest -q src/vaultspec_a2a/control/tests/test_worker_health_probe.py src/vaultspec_a2a/control/tests/test_desktop_worker_readiness.py` -> `pass`
- `S23` `by:` `root`
- `S23` `verify:` `desktop race process proof x5` -> `pass`
- `S23` `verify:` `ruff + ty + basedpyright focused checks` -> `pass`
- `S24` `M` `.vault/plan/2026-08-02-resource-aware-test-execution-plan.md`
- `S24` `M` `.vault/audit/2026-08-02-resource-aware-test-execution-audit.md`
- `S24` `M` `src/vaultspec_a2a/testing/resources.py`
- `S24` `M` `src/vaultspec_a2a/api/tests/test_provider_catalog_route.py`
- `S24` `verify:` `unit/service collection split and focused execution` -> `pass`
- `S24` `by:` `root`
- `S24` `verify:` `ruff + ty + basedpyright focused checks` -> `pass`
- `S25` `M` `.vault/plan/2026-08-02-resource-aware-test-execution-plan.md`
- `S25` `M` `.vault/audit/2026-08-02-resource-aware-test-execution-audit.md`
- `S25` `M` `src/vaultspec_a2a/providers/tests/conftest.py`
- `S25` `M` `src/vaultspec_a2a/providers/tests/test_resource_lifetimes.py`
- `S25` `verify:` `170 ACP fixture consumers and isolation proof` -> `pass`
- `S25` `by:` `root`
- `S25` `verify:` `ruff + ty + basedpyright focused checks` -> `pass`
- `S26` `M` `.vault/plan/2026-08-02-resource-aware-test-execution-plan.md`
- `S26` `M` `.vault/audit/2026-08-02-resource-aware-test-execution-audit.md`
- `S26` `A` `src/vaultspec_a2a/providers/cli_resolution.py`
- `S26` `M` `src/vaultspec_a2a/providers/factory.py`
- `S26` `M` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S26` `M` `src/vaultspec_a2a/providers/tests`
- `S26` `verify:` `110 deterministic + 12 installed provider proofs` -> `pass`
- `S26` `by:` `root`
- `S26` `verify:` `ruff + ty + basedpyright focused checks` -> `pass`
- `S27` `M` `.vault/plan/2026-08-02-resource-aware-test-execution-plan.md`
- `S27` `M` `.vault/audit/2026-08-02-resource-aware-test-execution-audit.md`
- `S27` `M` `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `S27` `verify:` `five asyncio-debug transport-owner repeats` -> `pass`
- `S27` `by:` `root`
- `S27` `verify:` `75 endpoint tests with unraisable warnings as errors` -> `pass`
- `S27` `verify:` `ruff + ty + basedpyright focused checks` -> `pass`
