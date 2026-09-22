---
tags:
  - '#exec'
  - '#issue-26-release-automation'
date: '2026-09-22'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:26916f946726d1cac06f6132dcd1bbd2a276ea0e10d9e5078038fbe97f66fbc5'
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

## Notes

- `S02` Repository settings changed outside tracked files: googleapis/release-please-action@* allowlisted; CodeQL default setup moved to labeled runner dev-runner.
- `S02` Operator-owned blockers left open: gh-runner Docker access for the Windows Compose job; offline ARM64 Linux and macOS release runners.
