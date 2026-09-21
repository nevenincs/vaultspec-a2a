---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-09-19'
modified: '2026-09-19'
body_schema: 'body-v2'
body_hash: 'sha256:ec0fa2e6f3fb896bd2ec545110384e08fb3d99b36e8657051d6d8e84346035d0'
related:
  - "[[2026-07-19-repository-tooling-hardening-adr]]"
---

# `repository-tooling-hardening` audit: `optional Node setup review`

## Scope

Reviewed default and full worktree setup, host diagnosis, CI selection, and
documentation after making the ACP Node runtime explicit. Manual checks covered
the host's Node 24 path and the installed pinned Node 26.8.1 path. Result: PASS
for the setup change; one existing harness-test contract drift remains open.

## Findings

### ci-contract-test | medium | Harness test expects retired sentinel recipe spelling

Type: test contract drift. Status: open. `dev/tests/test_ci_contract.py:103`
expects sentinel commands beginning `just lint `, while the tracked workflow
uses `just check-*` recipes at `.github/workflows/test.yml:125`. The full
`dev/tests` run reports 74 passed and this one failure. The mismatch predates
this setup change and does not exercise Node provisioning.

## Recommendations

Update the harness test to inspect the current named recipe contract in the
repository-tooling-hardening work queue, then rerun the full harness suite.
