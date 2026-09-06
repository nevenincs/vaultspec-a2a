---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:dfeb9ec1d16eb62fb4a69f832607a3a3d5b8af92c29fbde0d843ae937d6fed61'
step_id: 'S11'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Replace fragmented startup redispatch, read-time abandonment and pre-election projection with one durable recovery coordinator covering conditions 1-16

## Scope

- `src/vaultspec_a2a/control/recovery.py`
- `src/vaultspec_a2a/control/dispatch.py`
- `src/vaultspec_a2a/control/run_discovery_service.py`
- `src/vaultspec_a2a/control/thread_state_service.py`

## Changes

- `M` `src/vaultspec_a2a/control/dispatch.py`
- `M` `src/vaultspec_a2a/control/run_discovery_service.py`
- `M` `src/vaultspec_a2a/control/tests/test_reconciling_abandonment.py`
- `M` `src/vaultspec_a2a/control/tests/test_redispatch_failure_ladder.py`
- `A` `.vault/audit/2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-audit.md`
- `A` `.vault/research/2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-research.md`
- `verify:` `focused 14-case S11 pytest gate` -> `pass`
- `verify:` `two exact post-adjustment nodes` -> `pass`
- `verify:` `uv run ruff check <S11 paths>` -> `pass`
- `verify:` `uv run ty check <S11 paths>` -> `pass`

## Notes

Commit `4001cc77` is a partial implementation and received formal **FAIL**. Active discovery can serve one pre-election `reconciling` projection after a newer terminal writer wins, and the test checks only durable state. The plan and binding ADRs now replace split recovery ownership with one durable coordinator covering conditions 1-16. The Step remains open.

The focused pytest command emitted `14 passed in 25.05s` but did not exit naturally by 30 seconds. Exact session `74355` was interrupted and no matching pytest process survived. Condition 17 is now explicit plan Step S85 under the verification lifecycle owner.
