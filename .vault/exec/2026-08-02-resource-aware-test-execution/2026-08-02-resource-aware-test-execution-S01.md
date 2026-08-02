---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:c40ad2d214d51c95da25f4f007bfbf01fcdda623b87f652bdd387aae7bbd2bed'
step_id: 'S01'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Add the pytest-xdist dev dependency under the locked profile

## Scope

- `pyproject.toml`

## Description

- Add `pytest-xdist>=3.8` to the tooling dependency group with a comment binding its admission to strict loadgroup use.
- Relock and install additively (`uv lock`, then a frozen inexact sync).

## Outcome

Committed as bd0d33f1. `xdist 3.8.0` importable from the project venv; no existing package removed or upgraded besides the lock's torch source split.

## Notes

None.
