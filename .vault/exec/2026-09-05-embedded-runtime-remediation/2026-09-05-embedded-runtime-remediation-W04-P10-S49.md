---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:83cbc63587fd09679baf9ca3ea005a5546d12e42a7944a97485cb8b682a91aa0'
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
- `A` `.vault/audit/2026-09-06-embedded-runtime-remediation-w04-p10-s49-cooperative-shutdown-review-audit.md`
- `A` `.vault/audit/2026-09-06-embedded-runtime-remediation-w04-p10-s49-containment-rereview-audit.md`
- `A` `.vault/audit/2026-09-06-embedded-runtime-remediation-w04-p10-s49-assignment-failure-rereview-audit.md`
- `M` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W04-P10-S49.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `M` `.vault/plan/2026-09-05-embedded-runtime-remediation-plan.md`
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

## Assignment-before-authority correction

Formal rereview `91c882fe` failed the prior correction because Windows Job assignment could raise before containment recorded authority. `_reap_unready_worker` then treated the empty containment as success and left the exact retained root live. Cleanup now uses containment only when assignment succeeded; otherwise it retains the live `Popen` root and descendants as creation-time-guarded psutil identities, terminates only that scoped tree, waits the original handle, releases containment and re-raises the original assignment error. Comments now describe mandatory all-profile containment and the narrow restored/unassigned fallback.

The real Windows discriminator starts a root plus two 300-second descendants, closes Job assignment, and drives the production pre-admission readiness seam. It propagated `ProcessContainmentError` in 0.59 seconds and left no root or descendant. An initial invalid proof retained the uv venv redirector and exceeded 60 seconds; the owned test tree was interrupted and reaped with zero survivors, and the fixture was corrected to launch the base interpreter. That invalid run is classified MEDIUM/resolved measurement-integrity and supports no runtime claim.

- `verify:` `.venv/Scripts/python.exe -m pytest src/vaultspec_a2a/control/tests/test_unready_worker_reap.py::test_failed_containment_assignment_reaps_exact_tree_and_propagates -q -s` -> `pass` (1 passed in 1.05s; call 0.59s)
- `verify:` `.venv/Scripts/python.exe -m pytest src/vaultspec_a2a/control/tests/test_unready_worker_reap.py src/vaultspec_a2a/utils/tests/test_process_containment.py -q` -> `pass` (24 passed in 12.09s)
- `verify:` `.venv/Scripts/python.exe -m pytest <complete S49 focused modules> -q` -> `pass` (68 passed in 50.17s)
- `verify:` `.venv/Scripts/python.exe -m ruff check <correction paths>` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m ty check <correction production paths>` -> `pass`
- `verify:` implementation/review chain `8f79c919` -> `dcac3b27` FAIL -> `84ba2a2b` -> `91c882fe` FAIL -> `d8453cf0` -> `4b2e0a61` PASS
- `verify:` final formal rereview -> `pass` (assignment discriminator call 0.36 seconds; 24-test gate passed with zero survivors)
- `verify:` trace-only provider-owner reopen `141147db` -> `pass` (no S49 runtime or remediation-plan mutation; W04.P11.S60 remains open)
- `verify:` remediation, desktop-product-profile and codebase-health Core checks -> `pass` (zero diagnostics)

Formal rereview `4b2e0a61` accepts the assignment-before-authority correction and the complete S49 chain. Core closes S49, ER15 and ER16 after preserving both formal failures, the 7.1849-second bridge-close / 3.6920-second loop stall, parked SSE evidence, late-child race, 5.0086-second assignment-failure leak, invalid 60-second uv-redirector harness hang, exact-handle/PID-reuse safety and the final 68-pass gate. S48 and S50 remain separate. Volatile terminal recovery remains HIGH/open under W02.P03.S14; the 90-second recovery polling hang remains HIGH/open under served-capability W04.P08.S56 with W02.P03.S11 integration ownership; provider containment W04.P11.S60 remains reopened by trace-only `141147db`.
