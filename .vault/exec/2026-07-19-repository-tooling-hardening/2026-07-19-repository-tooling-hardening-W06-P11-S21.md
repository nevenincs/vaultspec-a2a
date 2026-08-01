---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:341d8ac0e90d11e0e841f5c4bfe0cadb72ad736c58bfdecdd9dc47456ad19e9a'
step_id: 'S21'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Establish typed API test-fixture contracts before repairing dependent API tests.

## Scope

- `src/vaultspec_a2a/api/tests/conftest.py`

## Description

- Type concrete SQLAlchemy engine, session, factory, and checkpointer fixtures.
- Declare the existing four-item application fixture contract.
- Bound the dynamic request JSON payload with recursive JSON aliases and one cast.
- Register the real ASGI dispatch routes with explicit response behavior.
- Type the FastAPI lifespan generator without changing its runtime path.
- Verify strict type, lint, format, focused real-dispatch, and independent review evidence.

## Outcome

The shared API fixture passes strict Basedpyright and Ty with the real SQLite and in-process ASGI execution model unchanged. The focused create-thread-to-dispatch regression passes.

## Notes

The full endpoint and middleware test partitions timed out and remain unverified. They are not claimed as broad completion evidence; later dependent API-test steps retain responsibility for their execution proof.
