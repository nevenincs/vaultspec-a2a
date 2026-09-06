---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:5545ea8e47ba1bbd7ce3f4e46ace85bca14857e6ebe0198159a1664ab36f198c'
step_id: 'S49'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Use cooperative server shutdown with admission closed first and one total deadline covering active work, streams and bounded forced escalation

## Scope

- `src/vaultspec_a2a/api/app.py`

## Changes

- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-robustness-audit.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `M` `.vault/research/2026-09-05-embedded-runtime-remediation-research.md`
- `M` `src/vaultspec_a2a/api/app.py`
- `M` `src/vaultspec_a2a/control/config.py`
- `M` `src/vaultspec_a2a/control/tests/test_unready_worker_reap.py`
- `M` `src/vaultspec_a2a/control/worker_management.py`
- `A` `src/vaultspec_a2a/lifecycle/shutdown.py`
- `A` `src/vaultspec_a2a/lifecycle/tests/test_shutdown.py`
- `M` `src/vaultspec_a2a/utils/process.py`
- `M` `src/vaultspec_a2a/worker/app.py`
- `M` `src/vaultspec_a2a/worker/ipc.py`
- `M` `src/vaultspec_a2a/worker/tests/test_app.py`
- `M` `src/vaultspec_a2a/worker/tests/test_ipc.py`
- `verify:` `uv run --locked ruff check <S49 paths>` -> `pass`
- `verify:` `uv run --locked ty check <S49 production paths>` -> `pass`
- `verify:` `uv run --locked python -m pytest <focused shutdown modules> -q` -> `pass` (48 passed in 41.39s after exact-identity refinement)
- `verify:` `uv run --locked python -m pytest src/vaultspec_a2a/worker/tests/test_app.py src/vaultspec_a2a/worker/tests/test_ipc.py -q` -> `pass` (35 passed in 12.76s)
- `verify:` `uv run --locked python -m pytest src/vaultspec_a2a/control/tests/test_unready_worker_reap.py src/vaultspec_a2a/control/tests/test_spawn_containment_ownership.py -q` -> `pass` (16 passed in 18.75s)
- `verify:` `uv run --locked python -m pytest <complete S49 focused modules> -q` -> `pass` (67 passed in 56.64s)
- `verify:` `uv run --locked python -m pytest <late-child and process-containment modules> -q` -> `pass` (15 passed in 27.60s)
- `verify:` `uv run --locked python -m pytest test_catalog_restart_redispatch.py::test_current_schema_restart_reaches_a_fresh_production_worker -vv -s --timeout=90 --timeout-method=thread` -> `fail`

## Notes

S47's prerequisite cooperative server owner is isolated in implementation `24dab547` and formal-FAIL correction `b83ad5ba`. S48 discovery ownership is unchanged, and S50 retains full frozen-worker lifecycle proof. The bridge's undelivered event remains only in memory, so durable terminal delivery stays HIGH/open under W02.P03.S14.

The instrumented production restart check crossed real catalog discovery but timed out with three current-schema runs still reconciling and the demand run still running. It never initiated shutdown. The separate HIGH recovery hang has the currently open correction owner `2026-08-05-served-capability-contract-plan W04.P08.S56`; this plan's open W02.P03.S11 owns verification and atomic-election integration. Exact last state and zero-process-residue evidence are retained in the audits and research.

Formal review `dcac3b27` failed S49 on a late child created inside the cooperative request after the original identity snapshot. The correction makes containment mandatory for every gateway spawn, seats restored uncontained roots before cooperation, skips cooperation when seating cannot be established, and runs forced cleanup plus handle release in a cancellation-safe `finally`. Real initially uncontained/then-seated and precontained late-child variants both exit root and child within the original four-second deadline without a host-wide scan or reused-pid risk. S49 stays open for rereview.
