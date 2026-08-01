---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:b94772b9bfb33860a13b54e315ee3332ee047345fdc45edd70f4f45a7816b43e'
step_id: 'S16'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Schedule one named hosted step per deterministic sentinel on every push and pull request, guarded by !cancelled and advisory until promotion.

## Scope

- `.github/workflows/test.yml`

## Description

- Added one advisory hosted step for each deterministic strict sentinel.
- Kept each command as a named `just lint` target with no repeated tool policy.
- Preserved canonical CI and all pre-existing workflow stages.

## Outcome

Direct Actionlint and a structural workflow assertion passed: exactly eight sentinel steps target `type-strict`, `type-platforms`, `complexity`, `cyclomatic`, `shape`, `limits`, `nesting`, and `size`; every one runs when not cancelled and is advisory pending promotion. Independent review found no blocker.

## Notes

The `just lint workflow` wrapper timed out without output in the shared environment on two bounded attempts. Direct Actionlint passed; the wrapper boundary is recorded in the audit and is not claimed as verified.
