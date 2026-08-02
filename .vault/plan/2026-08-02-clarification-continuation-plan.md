---
tags:
  - '#plan'
  - '#clarification-continuation'
date: '2026-08-02'
modified: '2026-08-02'
body_hash: 'sha256:7d72fae6c685941750312cb14b15543c2839eaefa9db4c1a6684866a73604a26'
tier: L1
related:
  - '[[2026-08-02-clarification-continuation-adr]]'
  - '[[2026-08-02-clarification-continuation-research]]'
  - '[[2026-08-02-clarification-continuation-reference]]'
---

# `clarification-continuation` plan

Add a typed new-prompt outcome to the existing clarification response path and prove it
through the real worker/checkpoint loop.

## Description

Implement the accepted clarification-continuation ADR without adding a gateway verb or a
parallel follow-up path. The domain contract and graph gate land first, the additive HTTP
mapping follows, and deterministic construction plus real-runtime tests close the behavior.

## Steps

- [x] `S01` - Define the typed continuation outcome and graph resume behavior; `src/vaultspec_a2a/thread/clarification.py, src/vaultspec_a2a/graph/nodes/clarification.py`.
- [x] `S02` - Map the additive prompt response through the existing gateway verb; `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/api/routes/gateway.py`.
- [x] `S03` - Prove contract boundaries and the real worker continuation loop; `src/vaultspec_a2a/thread/tests/test_clarification.py, src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`.

## Parallelization

The Steps are ordered: the gateway consumes the domain contract, and the real-worker proof
depends on both production layers. No Step is delegated in parallel in the shared worktree.

## Verification

- Contract tests prove exactly-one-of answers or prompt, inclusive prompt bounds, and typed serialization.
- Graph tests prove a continuation appends one human message, records no fabricated answer, clears the pending request, and advances through the fixed target.
- The real SQLite, LangGraph, gateway, worker app, and Executor loop proves the submitted prompt reaches durable graph state.
- Existing answer behavior, focused lint, and strict typing remain green.
- Formal review classifies every finding and records deferred concurrency hardening in the audit queue.
