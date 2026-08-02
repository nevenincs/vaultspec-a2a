---
tags:
  - '#reference'
  - '#clarification-continuation'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:0cc3a60a50b36aa1c0ccd46eb3548531b42b7d3d1b613f9cc5e22a8b9b326ccb'
related:
  - "[[2026-08-02-clarification-continuation-research]]"
---

# `clarification-continuation` reference: `typed prompt resume seam`

This reference maps the existing checkpoint, HTTP, worker, and graph surfaces that a
prompt continuation must compose without adding a parallel message path.

## Summary

The authoritative parked request is parsed by `pending_clarification` in
`src/vaultspec_a2a/thread/clarification.py:371`. `run_clarification_respond_endpoint` in
`src/vaultspec_a2a/api/routes/gateway.py:1911` resolves that request before dispatch and
is therefore the correct HTTP seam for both answer and prompt outcomes.

The domain contract belongs beside `ClarificationAnswers` in
`src/vaultspec_a2a/thread/clarification.py:305`. A `ClarificationContinuation` should
carry a literal discriminator, the request id, and bounded prompt content. The existing
message bound is `MAX_RUN_MESSAGE_CHARS` in
`src/vaultspec_a2a/api/schemas/gateway.py:83`; its value should remain single-homed when
the domain model begins consuming it.

The gate in `src/vaultspec_a2a/graph/nodes/clarification.py:323` is the only graph node
that should interpret the union. An answer emits only the request-id keyed reducer delta.
A continuation emits one `HumanMessage`, no empty answer map, clears the committed request,
and follows the existing `proceed_target`. `TeamState.messages` already owns append semantics
at `src/vaultspec_a2a/thread/state.py:170`.

No new worker action is required. `DispatchRequest.option_id` already accepts dictionaries
in `src/vaultspec_a2a/ipc/schemas.py:52`, and `_handle_resume` passes that value to
`Command(resume=...)` in `src/vaultspec_a2a/worker/executor.py:598`.

The strongest deterministic proof is the existing real gateway-to-worker loop in
`src/vaultspec_a2a/api/tests/test_clarification_loop_live.py:64`. It uses a real SQLite
checkpointer, compiled LangGraph, worker app, and `Executor`, and asserts on graph state
rather than a recorded dispatch. Contract-level construction and exactly-one-of validation
belong in `src/vaultspec_a2a/thread/tests/test_clarification.py` and the gateway schema tests.
