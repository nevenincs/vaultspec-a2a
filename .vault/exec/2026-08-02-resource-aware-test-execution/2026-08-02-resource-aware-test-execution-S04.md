---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:5eda683c0ae511d057ac3b24e1b6749b4ade1726ac56e9758ca5e94986169305'
step_id: 'S04'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Implement progress deadlines with pid-and-heartbeat liveness watch

## Scope

- `src/vaultspec_a2a/testing/progress.py`

## Description

- Implement `ProgressDeadline`, `LivenessWatch`, `registry_watch`, and `wait_for` in `src/vaultspec_a2a/testing/progress.py`.
- Fail on resource death (dead owner pid, heartbeat past the role's staleness window, vanished record) or observed-state stall past the idle window; elapsed wall time is never a failure reason.

## Outcome

Committed as 4c034a6b. `registry_watch` reuses the production `classify_record`, so the watch and the lifecycle verbs cannot disagree about LIVE.

## Notes

None.
