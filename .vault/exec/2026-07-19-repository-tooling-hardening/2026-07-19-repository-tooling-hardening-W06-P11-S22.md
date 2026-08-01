---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:cae98ce1f0095d79131712722bfb151e9d1a0f12424aff6bdcb530becaa6e7ad'
step_id: 'S22'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Repair the API endpoint test partition against the typed fixture contract.

## Scope

- `src/vaultspec_a2a/api/tests/test_endpoints.py`

## Description

- Annotate every injected SQLite, checkpointer, path, and capture fixture boundary.
- Define local SQLAlchemy and recursive JSON type vocabulary for endpoint assertions.
- Narrow the real run-list response at its JSON boundary before indexing it.
- Replace checkpoint configuration literals with a typed helper that preserves omitted and explicit namespaces.
- Replace private aggregator-state setup with public real event APIs.
- Validate structured log extras defensively without changing the asserted behavior.
- Run strict static gates, real endpoint class shards, and independent review.

## Outcome

The endpoint partition has no scoped Basedpyright diagnostics, while Ty and Ruff remain clean. Every endpoint test class was exercised in bounded real SQLite and ASGI shards; the checkpoint deletion regression proves history reads still span root and child namespaces when the namespace key is omitted.

## Notes

The original monolithic endpoint suite timed out, so execution evidence is the four bounded class groups: create/list/health, state/send/presets, team/permission, and delete/autonomous/cancel. The standard Python 3.13 metadata deprecation warning remains unrelated to this change.
