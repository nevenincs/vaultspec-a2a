---
tags:
  - '#plan'
  - '#clarification-decline'
date: '2026-08-02'
modified: '2026-08-02'
body_hash: 'sha256:f321be9029d48ba94463a5e2fc7db6874aa3e8eabf62e2f82d8d33c000851046'
tier: L1
related:
  - '[[2026-08-02-clarification-decline-adr]]'
  - '[[2026-08-02-clarification-decline-research]]'
---

# `clarification-decline` plan

Add a typed decline outcome to the existing clarification response path and prove it
through the real worker/checkpoint loop.

## Description

Implement the proposed clarification-decline ADR as a third exactly-one-of body
alternative on the existing respond verb. The domain contract, fixed marker text, and
graph gate land first, the additive HTTP mapping follows, and contract plus
real-runtime tests close the behavior. The leased dispatch journal is untouched by
design.

## Steps

- [x] `S01` - Define the typed decline outcome, its fixed marker text, and the graph resume behavior; `src/vaultspec_a2a/thread/clarification.py, src/vaultspec_a2a/graph/nodes/clarification.py`.
- [x] `S02` - Map the additive decline response through the existing gateway verb; `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/api/routes/gateway.py`.
- [x] `S03` - Prove contract boundaries and the real worker decline loop; `src/vaultspec_a2a/thread/tests/test_clarification.py, src/vaultspec_a2a/graph/tests/nodes/test_clarification.py, src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`.

## Parallelization

The Steps are ordered: the gateway consumes the domain contract, and the real-worker
proof depends on both production layers. No Step is delegated in parallel in the
shared worktree.

## Verification

- Contract tests prove exactly-one-of answers, prompt, or decline, the decline
  discriminator and request-id binding, and typed serialization.
- Graph tests prove a decline appends exactly one fixed marker message, records no
  answer entry, writes the resolution receipt, clears the pending request, and
  advances through the fixed target.
- The real SQLite, LangGraph, gateway, worker app, and Executor loop proves a
  submitted decline resumes the parked run and leaves the marker in durable graph
  state.
- Existing answer and continuation behavior, focused lint, and strict typing remain
  green.
- Formal review classifies every finding and appends deferred items to the feature's
  rolling audit queue.
