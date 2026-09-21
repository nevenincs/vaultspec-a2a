---
tags:
  - '#exec'
  - '#ci-merge-gate'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:c9a1727d4634ec4f432d6db840cb781097314e61ec39354a01462934c9b8b511'
related:
  - "[[2026-09-21-ci-merge-gate-plan]]"
---

# `ci-merge-gate` ledger

## Changes

- `S01` `A` `.github/workflows/merge-gate.yml`
- `S01` `M` `.github/workflows/test.yml`
- `S01` `M` `dev/toolchain.py`
- `S01` `M` `justfile`
- `S01` `A` `.vault/reference/2026-09-21-ci-merge-gate-reference.md`
- `S01` `A` `.vault/plan/2026-09-21-ci-merge-gate-plan.md`
- `S01` `A` `.vault/index/ci-merge-gate.index.md`
- `S01` `verify:` `just ci-merge` -> `pass`
- `S01` `by:` `vaultspec-high-executor`
- `S02` `M` `dev/tests/test_ci_contract.py`
- `S02` `M` `.github/ci-contract-allow.txt`
- `S02` `verify:` `just check-workflow` -> `pass`
- `S02` `by:` `vaultspec-high-executor`
- `S03` `D` `.github/actionlint.yaml`
- `S03` `M` `.github/workflows/test.yml`
- `S03` `M` `dev/actionlint.py`
- `S03` `M` `dev/tests/test_ci_contract.py`
- `S03` `M` `.vault/reference/2026-09-21-ci-merge-gate-reference.md`
- `S03` `M` `.vault/audit/2026-09-21-ci-merge-gate-audit.md`
- `S03` `verify:` `pytest dev/tests/test_ci_contract.py` -> `pass`
- `S03` `by:` `vaultspec-high-executor`
