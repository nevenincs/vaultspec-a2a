---
tags:
  - '#exec'
  - '#issue-26-release-automation'
date: '2026-09-22'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:bfc81674f30a0f012e5f8140643fc2ebb11fee7b7641f8e8522ef9ae55dd313b'
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
