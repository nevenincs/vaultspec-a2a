---
tags:
  - '#research'
  - '#clarification-continuation'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:edeaf8b4bba923dda7e1fcf7243c136c6c6316d6ef7c293f385ae96d00f9ec7a'
related:
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `clarification-continuation` research: `new prompts at a parked clarification`

A parked clarification currently has one successful outcome: a validated answer sheet.
The evidence favors treating a newly submitted prompt as a second typed outcome of the
same checkpoint-addressed response verb. This preserves the six-verb engine whitelist,
keeps the graph parked while the user merely changes composer mode, and resumes only
after real prompt content is submitted. The ADR must settle the wire discriminator,
transcript semantics, graph target, and replay posture.

## Findings

### An ordinary message cannot wake an interrupted graph

The message service dispatches `ingest`, but the worker deliberately skips ingest when
checkpoint projection reports an interrupt. Relaxing message eligibility would therefore
accept the prompt without advancing the graph. The viable transport must produce
`Command(resume=...)`. Evidence: `src/vaultspec_a2a/control/message_service.py:151`,
`src/vaultspec_a2a/worker/executor.py:482`, and
`src/vaultspec_a2a/worker/executor.py:598`.

### The existing clarification verb is the smallest compatible edge

The response route already scopes input by run id and checkpoint-authoritative request id,
then dispatches a dictionary resume value. Extending its request body with an exactly-one-of
prompt alternative leaves answer-only clients compatible and does not add a seventh engine
verb. The alternative message route is absent from the engine whitelist; a new verb expands
both repositories without adding semantics beyond a second outcome. Evidence:
`src/vaultspec_a2a/api/routes/gateway.py:1911`,
`src/vaultspec_a2a/api/schemas/gateway.py:684`, and
`src/vaultspec_a2a/thread/clarification.py:305`.

### The graph can preserve the transcript without new state

`TeamState.messages` already uses LangGraph's `add_messages` reducer. The gate can append one
`HumanMessage` in the same resumed superstep that clears the pending request, while leaving
`clarification_answers` untouched. The fixed `proceed_target` preserves the same compiled
run and team; current preset-declared clarification has no asking-agent ownership to restore.
Evidence: `src/vaultspec_a2a/thread/state.py:170`,
`src/vaultspec_a2a/graph/nodes/clarification.py:323`, and
`src/vaultspec_a2a/graph/compiler.py:1661`.

### The gate needs defensive typed parsing

The current node extracts any `answers` dictionary without checking the discriminator or
request id. An alternate outcome makes that implicit parsing unsafe: both variants must be
validated against the committed request before pending state is cleared. Evidence:
`src/vaultspec_a2a/graph/nodes/clarification.py:235`.

### Concurrency remains a separate lifecycle risk

The route reads a checkpoint and dispatches without a durable per-request claim. Concurrent
responses can both observe the same pending request before either resume advances it. This
pass can preserve existing at-most-once behavior and add node-side stale-payload refusal, but
a durable claim/replay/conflict contract requires a journal design shared by both answers and
prompt continuations. Evidence: `src/vaultspec_a2a/api/routes/gateway.py:1952` and
`src/vaultspec_a2a/api/schemas/gateway.py:705`.

## Sources

- `src/vaultspec_a2a/control/message_service.py:151`
- `src/vaultspec_a2a/worker/executor.py:482`
- `src/vaultspec_a2a/worker/executor.py:598`
- `src/vaultspec_a2a/api/routes/gateway.py:1911`
- `src/vaultspec_a2a/api/routes/gateway.py:1952`
- `src/vaultspec_a2a/api/schemas/gateway.py:684`
- `src/vaultspec_a2a/api/schemas/gateway.py:705`
- `src/vaultspec_a2a/thread/clarification.py:305`
- `src/vaultspec_a2a/thread/state.py:170`
- `src/vaultspec_a2a/graph/nodes/clarification.py:235`
- `src/vaultspec_a2a/graph/nodes/clarification.py:323`
- `src/vaultspec_a2a/graph/compiler.py:1661`
