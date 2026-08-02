---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:14fee212334ebac8e1e2446581b7e6799984380124fee7e83784caf5188a4983'
step_id: 'S17'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Load the plugin through its pytest11 entry point and guard against addopts stripping

## Scope

- `pyproject.toml`

## Description

- Register the plugin under a pytest11 entry point and drop the addopts
channel; strip the now-colliding explicit plugin flags from the
subprocess proof runners.
- Add the guard test driving the toolchain's exact override shape and
asserting a plugin-only fixture still resolves.

## Outcome

Entry-point hunk landed via the concurrent deptry commit bb1030a3 (it swept this file's staged change together with its own dependency declarations); guard and runner changes in 1bff981f. Verified live: the wholesale addopts override runs with the plugin active, and the explicit -p now raises already-registered, proving the entry point is the one loader.

## Notes

The earlier S07 wiring row is superseded by this Step; the audit records the correction.
