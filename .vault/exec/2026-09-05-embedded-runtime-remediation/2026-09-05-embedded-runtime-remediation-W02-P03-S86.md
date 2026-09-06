---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:a42441641d371f71909e1def8951dab9ce0f10ed6b966621d42237d0169416b4'
step_id: 'S86'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Commit the complete non-secret initial dispatch input and stable receipt atomically with run acceptance before network delivery; build configuration and workspace inputs before taking the database write lock, retain actor-token requirement without secrets, and reject invalid input without a partial durable reservation

## Scope

- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/control/tests/test_thread_service_tokens.py`
## Changes

- `M` `src/vaultspec_a2a/control/thread_service.py`
- `M` `src/vaultspec_a2a/control/tests/test_thread_service_tokens.py`
- `M` `.vault/adr/2026-08-02-control-action-leases-adr.md`
- `M` `.vault/research/2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-research.md`
- `M` `.vault/audit/2026-09-06-embedded-runtime-remediation-recovery-architecture-audit.md`
- `M` `.vault/plan/2026-09-05-embedded-runtime-remediation-plan.md`
- `verify:` `resource-aware runner: six thread-service admission and race tests` -> `pass`
- `verify:` `Ruff and Ty on the two changed source/test paths` -> `pass`

## Notes

A preceding six-case attempt printed case dots but exceeded its 60-second process deadline; it was terminated with zero survivors and remains failed verification evidence. The bounded resource-aware rerun completed naturally: six passed in 3.54 seconds, exit 0. Recovery consumption remains under S11/S12/S83.
