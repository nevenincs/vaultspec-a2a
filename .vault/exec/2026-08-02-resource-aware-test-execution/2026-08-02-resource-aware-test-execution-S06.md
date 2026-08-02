---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:a8bcb07e1ba555c8e95edb3f41d2f49a97c7c58e2b8127a203035a8e216b0854'
step_id: 'S06'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Implement the scheduling plugin with group computation, dist-mode guard, backstop derivation, and acquisition fixtures

## Scope

- `src/vaultspec_a2a/testing/plugin.py`

## Description

- Implement the plugin in `src/vaultspec_a2a/testing/plugin.py`: xdist group computation via union-find over declared exclusive keys, the serial catch-all for undeclared live-tier items, the loadgroup-only guard, backstop-timeout derivation, the autouse lease fixture, and the `gateway_endpoint`/`worker_endpoint`/`leased_port` acquisition fixtures.
- Publish the package facade in `src/vaultspec_a2a/testing/__init__.py`.

## Outcome

Committed as 79990d17; corrected by 2eae4ec5 (lone exclusive keys must be registered in the union-find) and d7d026f2 (collection hook must run tryfirst so the xdist worker's nodeid rewrite sees the computed markers).

## Notes

The dist-mode guard lives in trylast `pytest_configure`: a guard in `pytest_cmdline_main` never runs because that hook is firstresult and the default impl consumes it.
