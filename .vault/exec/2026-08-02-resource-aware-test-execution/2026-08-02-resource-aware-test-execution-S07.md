---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:29925e550794ce508b18921d722fd48fb868c11102c71277130ef7f97b0bdfc5'
step_id: 'S07'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Wire the plugin into the root conftest and register the resource marker

## Scope

- `src/vaultspec_a2a/conftest.py`

## Description

- Load the plugin through `-p vaultspec_a2a.testing.plugin` in the configured addopts and register the `resource` marker text in `pyproject.toml`.

## Outcome

Committed as 6721f541. Wired via addopts rather than the planned conftest edit because pytest 9 forbids `pytest_plugins` below the rootdir conftest; the root conftest needed no change.

## Notes

Scope divergence from the plan row (conftest -> pyproject) recorded here deliberately.
