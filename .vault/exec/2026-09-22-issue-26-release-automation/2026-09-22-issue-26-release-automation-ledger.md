---
tags:
  - '#exec'
  - '#issue-26-release-automation'
date: '2026-09-22'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:a3fba579cbdb8981ac2e08866a33e9aad041ae79a7f6cad50f510d113dd8b79c'
related:
  - "[[2026-09-22-issue-26-release-automation-plan]]"
---

# `issue-26-release-automation` ledger

## Changes

- `S01` `M` `.github/workflows/release-please.yml`
- `S01` `M` `.github/workflows/release.yml`
- `S01` `A` `.vault/audit/2026-09-22-issue-26-release-automation-audit.md`
- `S01` `A` `.vault/index/issue-26-release-automation.index.md`
- `S01` `M` `.vault/plan/2026-09-22-issue-26-release-automation-plan.md`
- `S01` `A` `.vault/reference/2026-09-22-issue-26-release-automation-core-pattern-reference.md`
- `S01` `M` `CHANGELOG.md`
- `S01` `M` `Justfile`
- `S01` `A` `dev/tests/test_release_please_automation.py`
- `S01` `M` `dev/tests/test_release_workflow_contract.py`
- `S01` `M` `release-please-config.json`
- `S01` `D` `scripts/prepare_release.py`
- `S01` `D` `scripts/tests/test_prepare_release.py`
- `S01` `verify:` `uv run --no-sync prek run --files <changed-paths>` -> `pass`
- `S01` `by:` `vaultspec-high-executor`
- `S02` `M` `.github/workflows/test.yml`
- `S02` `M` `.github/workflows/merge-gate.yml`
- `S02` `M` `.github/workflows/release.yml`
- `S02` `A` `dev/tests/test_self_hosted_runners.py`
- `S02` `M` `src/vaultspec_a2a/lifecycle/registry.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_project_confinement.py`
- `S02` `M` `src/vaultspec_a2a/testing/tests/test_runner.py`
- `S02` `M` `.vault/plan/2026-09-22-issue-26-release-automation-plan.md`
- `S02` `M` `.vault/audit/2026-09-22-issue-26-release-automation-audit.md`
- `S02` `verify:` `just test-service-path test_compose_profile_regression.py (Windows Docker Desktop, 17)` -> `pass`
- `S02` `by:` `claude-opus`
- `S02` `verify:` `release.yml Windows leg locally: freeze + frozen-tree check + prove_artifact_lifecycle.sh` -> `pass`
- `S02` `D` `dev/tests/test_self_hosted_runners.py`
- `S03` `M` `src/vaultspec_a2a/desktop_tests/test_lazy_worker.py`
- `S03` `M` `.vault/audit/2026-09-22-issue-26-release-automation-audit.md`
- `S03` `verify:` `lazy-worker reproduction, ~90 runs across isolation, CPU, I/O, ordering, parallel, pinned-CPU conditions` -> `pass`
- `S03` `M` `src/vaultspec_a2a/database/session.py`
- `S03` `M` `src/vaultspec_a2a/database/__init__.py`
- `S03` `A` `src/vaultspec_a2a/database/tests/test_write_transaction.py`
- `S03` `M` `src/vaultspec_a2a/control/thread_service.py`
- `S03` `M` `src/vaultspec_a2a/api/routes/_gateway_run_start.py`
- `S03` `verify:` `dev harness tests (130), ruff, ty on touched files` -> `pass`
- `S03` `by:` `claude-opus`
- `S04` `M` `.github/workflows/release-please.yml`
- `S04` `M` `release-please-config.json`
- `S04` `M` `.github/ci-contract-allow.txt`
- `S04` `M` `dev/tests/test_release_please_automation.py`
- `S04` `M` `dev/tests/test_release_workflow_contract.py`
- `S04` `M` `.github/workflows/test.yml`
- `S04` `M` `.github/workflows/release.yml`
- `S04` `M` `.github/workflows/migrations.yml`
- `S04` `M` `dev/toolchain.py`
- `S04` `M` `.vault/audit/2026-09-22-issue-26-release-automation-audit.md`
- `S04` `verify:` `PR #77 inspected: BLOCKED without merge gate, uv.lock 0.3.0 against pyproject 0.3.1` -> `pass`
- `S04` `by:` `claude-opus`
- `S05` `M` `src/vaultspec_a2a/database/session.py`
- `S05` `M` `src/vaultspec_a2a/database/tests/test_wal_maintenance.py`
- `S05` `verify:` `Windows freeze + prove_artifact_lifecycle.sh on 63cac8ac` -> `pass`
- `S05` `by:` `claude-opus`
- `S03` `verify:` `plan-close review remediation: dev + database/api/control/desktop suites (1634)` -> `pass`
- `S04` `verify:` `just check-workflow after review remediation` -> `pass`
- `S05` `M` `src/vaultspec_a2a/database/__init__.py`
- `S05` `M` `src/vaultspec_a2a/api/app.py`
- `S05` `M` `.vault/audit/2026-09-22-issue-26-release-automation-audit.md`
- `S05` `verify:` `bare migrations leave a fresh store on the delete journal (probe)` -> `pass`

## Notes

- `S02` Repository settings changed outside tracked files: googleapis/release-please-action@* allowlisted; CodeQL default setup moved to labeled runner dev-runner.
- `S02` Operator-owned blockers left open: gh-runner Docker access for the Windows Compose job; offline ARM64 Linux and macOS release runners.
- `S02` Runner-placement contract test and host-describing workflow comments removed at the user's direction: the software does not test or describe its own infrastructure.
- `S03` Root cause not yet identified: the failure reproduces only on the CI Linux runner, and every prior CI failure lost its gateway traceback to a truncated assertion message. S03 stays open pending that evidence.
- `S03` Root cause confirmed from CI evidence; local Windows does not reproduce the race, so the fix is proven by the real-connection unit tests and the next Linux CI run.
- `S04` The lockfile and merge-gate dispatch steps run only on the next release-please execution after this reaches main; their live exercise is pending.
- `S03` Plan-close review: commit path rollback before the worker probe.
- `S04` Plan-close review: guarded checkout ref; merge gate dispatched without a ref input so it validates the commit it reports on.
- `S05` Plan-close review (high): warm-up moved behind migration and behind armed-boot validation as seat_sqlite_posture.
