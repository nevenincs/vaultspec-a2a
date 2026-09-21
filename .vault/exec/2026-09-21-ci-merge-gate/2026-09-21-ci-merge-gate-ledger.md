---
tags:
  - '#exec'
  - '#ci-merge-gate'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:7bd4a7774ab079a3989c2d589f09576a0f65d2144b36121b79ff54c09befbd14'
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

