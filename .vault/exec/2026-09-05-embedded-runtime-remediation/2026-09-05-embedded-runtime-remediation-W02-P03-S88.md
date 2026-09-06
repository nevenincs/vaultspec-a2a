---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:5219726a7c2fa04f1e13e4bbf36813d847b50ec9ff19f220aadb3989f9c5313f'
step_id: 'S88'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Replace the filesystem completion marker with an authenticated loopback receipt so Windows file locks cannot overwrite the owned pytest exit outcome after tree reaping

## Scope

- `src/vaultspec_a2a/testing/runner.py`
- `src/vaultspec_a2a/testing/plugin.py`
- `src/vaultspec_a2a/testing/tests/test_runner.py`

## Changes

- Replaced the filesystem completion marker with a PID-bound, random-token-authenticated loopback receipt.
- Bounded receipt parsing to 256 bytes and accepted fragmented socket delivery.
- Redirected nested runner self-test output to files so inherited pipe handles cannot make timeout cleanup unbounded.
- Preserved distinct owned outcomes for post-result root hangs and surviving descendants.
- Updated the condition 17 audit with severity, disposition, and the remaining pre-result deadline item.

## Verification

- `.venv/Scripts/python.exe -m vaultspec_a2a.testing.runner --run-timeout 90 --exit-timeout 5 -- -q src/vaultspec_a2a/testing/tests/test_runner.py` -> `3 passed in 18.58s`, natural exit 0.
- `uv run ruff check src/vaultspec_a2a/testing/runner.py src/vaultspec_a2a/testing/plugin.py src/vaultspec_a2a/testing/tests/test_runner.py` -> pass.
- `uv run ty check src/vaultspec_a2a/testing/runner.py src/vaultspec_a2a/testing/plugin.py src/vaultspec_a2a/testing/tests/test_runner.py` -> pass.

## Notes

The filesystem cleanup overwrite and nested self-test pipe hang are resolved. The separately classified medium finding for pre-result startup and collection deadlines remains queued in the audit.
