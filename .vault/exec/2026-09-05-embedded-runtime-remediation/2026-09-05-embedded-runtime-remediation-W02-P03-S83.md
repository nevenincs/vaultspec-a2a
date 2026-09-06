---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:c3114cccb0f712ad1a197dce588925f2054e9b8dfe43a6c96913c39d73b395f8'
step_id: 'S83'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Persist one leased recovery attempt per run revision and action receipt with classified condition, attempt count, next eligible attempt and run-derived deadline; drain it during startup and ordinary operation so circuit-open, capacity, typed rejection and transport loss cannot strand accepted work or depend on client polling

## Scope

- `src/vaultspec_a2a/database/models.py`
- `src/vaultspec_a2a/database/migrations`
- `src/vaultspec_a2a/control/recovery.py`

## Changes

- `M` `src/vaultspec_a2a/control/direct_control_recovery.py`
- `M` `src/vaultspec_a2a/control/tests/test_direct_control_recovery_current.py`
- `verify:` `complete current direct-control recovery module, three cases in 21.63 seconds` -> `pass`
- `verify:` `strengthened permanent project-refusal discriminator, one case in 5.27 seconds` -> `pass`
- `verify:` `focused Ruff and Ty` -> `pass`

## Notes

This partial S83 increment removes an immediate infinite-retry path. Once exact current accepted input cannot be reconstructed because its project, credentials or schema authority is unusable, recovery locks and revalidates the current thread/action, elects RECONCILING when needed, settles the exact action as `rejected_invalid_state`, and records `operator_intervention_required` with the typed refusal reason. A concurrent newer or terminal writer wins instead. The refused action no longer re-enters the unapplied scan on every pass.

Formal review findings:

- HIGH / infinite permanent-refusal loop: recovery rolled back the acquired lease for an impossible accepted action, making it immediately eligible forever -> resolved.
- HIGH / missing durable schedule: retryable circuit, capacity and transport outcomes still have no attempt row, next eligible time or run-derived deadline -> open in S83.
- HIGH / missing ordinary-operation owner: the gateway still runs startup recovery plus at most one lease-delay retry -> open in S83/S14.
- HIGH / classification locality: the refusal type is durable only in the thread repair reason while the action result uses the generic closed rejection member -> open for the S83 classified-attempt schema.
- MEDIUM / recovery precedence: checkpoint-proven completion may later supersede a project refusal, which is intentional durable truth precedence and requires an explicit scheduler test.

S83 remains open.