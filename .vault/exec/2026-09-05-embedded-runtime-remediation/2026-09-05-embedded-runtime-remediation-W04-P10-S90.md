---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:a58676735e9125a17e6aa6d7b4f17a6a2c9e48ecfb37c6257aaf5958532f0e42'
step_id: 'S90'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Remove missing or blank worker-target adoption and refuse unproven incumbents without eviction

## Scope

- `src/vaultspec_a2a/control/worker_management.py`

## Changes

- `M` `src/vaultspec_a2a/control/worker_management.py`
- `M` `src/vaultspec_a2a/control/tests/test_worker_provenance.py`
- `verify:` `.venv/Scripts/python.exe -m vaultspec_a2a.testing.runner --run-timeout 60 --exit-timeout 5 -- src/vaultspec_a2a/control/tests/test_worker_provenance.py -q -k "attaches_to_a_same_gateway or refuses_missing_or_blank or auto_spawn_does_not_evict"` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m ruff check src/vaultspec_a2a/control/worker_management.py src/vaultspec_a2a/control/tests/test_worker_provenance.py` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m ty check src/vaultspec_a2a/control/worker_management.py src/vaultspec_a2a/control/tests/test_worker_provenance.py` -> `pass`

## Notes

The full provenance file emitted eight passing case markers but did not produce a pytest session result within 90 seconds. The bounded owner reported `tree_reaped=true`; that invocation is retained as FAIL. The three changed adoption and refusal cases passed in 2.47 seconds and exited naturally.
