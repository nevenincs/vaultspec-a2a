---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:5f7d804f6151d56b290b36d1ff64574c682ef839f3e260d2252cc55fe666be92'
step_id: 'S89'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Emit bounded pre-result owner progress with the exact process id, phase and declared deadlines so a silent collection or execution stall remains observable

## Scope

- `src/vaultspec_a2a/testing/runner.py`
- `src/vaultspec_a2a/testing/tests/test_runner.py`
- `src/vaultspec_a2a/testing/tests/_runner_progress_probe.py`

## Changes

- Emit an immediate owner record after the contained pytest child is assigned and resumed.
- Report the exact PID, `awaiting_session_result` phase, configured run deadline and teardown deadline.
- Emit a bounded heartbeat every 30 seconds until the session result arrives.
- Accept a positive diagnostic progress interval without changing the lane's run deadline.
- Add a delayed real pytest probe that must produce progress before completing.

## Review findings

- MEDIUM silent pre-result ownership -> resolved.
- MEDIUM universal pre-result deadline selection -> remains open and separately queued; this step adds evidence without inventing one timeout for unlike lanes.
- No legacy command, environment name, compatibility alias, fallback outcome or default recovery behavior was introduced.

## Verification

- `.venv/Scripts/python.exe -m vaultspec_a2a.testing.runner --run-timeout 90 --exit-timeout 5 -- -q src/vaultspec_a2a/testing/tests/test_runner.py` -> four passed in 32.14 seconds, natural exit 0, with immediate and 30-second progress records.
- Focused Ruff -> pass.
- Focused Ty -> pass.
