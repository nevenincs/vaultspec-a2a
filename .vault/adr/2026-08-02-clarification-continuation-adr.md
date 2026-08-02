---
tags:
  - '#adr'
  - '#clarification-continuation'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e7ce11145a7a8f8df58fcc5d08ceb03f6e6f058246e0f48bd2130fcd499ab8c0'
related:
  - "[[2026-08-02-clarification-continuation-research]]"
  - "[[2026-08-02-clarification-continuation-reference]]"
---

# `clarification-continuation` adr: `typed new-prompt resolution for parked questions` | (**status:** `accepted`)

## Problem Statement

A user who does not want to answer a clarification must be able to return to the composer,
leave the graph parked until they submit real text, and have that new prompt continue the
same run. The current answer-only resume contract cannot express this without pretending the
prompt is an answer or cancelling the run. The decision is grounded by
`2026-08-02-clarification-continuation-research` and
`2026-08-02-clarification-continuation-reference`.

## Considerations

- Checkpoint request identity remains authoritative for every resolution.
- The dashboard engine admits the existing clarification response verb but not ordinary messages.
- Existing answer-only clients must remain compatible.
- The transcript is durable context; destructive replacement is not required by the product behavior.
- Current clarification ownership is the run/team and fixed graph target, not an arbitrary asking agent.

## Considered options

- **Add a prompt alternative to clarification response (chosen).** Preserves the whitelist and request-scoped resume path while making the outcome explicit.
- **Route ordinary messages across a parked clarification.** Rejected because the message verb is outside the engine whitelist and ingest cannot cross an interrupt.
- **Add a seventh decline or chat verb.** Rejected because it expands the edge for a second outcome of an existing resource transition.
- **Encode the prompt as empty or synthetic answers.** Rejected because it lies about required-answer validation and loses user intent.

## Constraints

- The alternate body must be additive and exactly one of answers or prompt.
- Prompt length follows the existing run-message character ceiling from the shared contract owner.
- The graph gate validates discriminator and request id again before clearing pending state.
- The same compiled graph and fixed continuation target resume; arbitrary agent targeting is out of scope.
- The existing read-then-dispatch concurrency gap is recorded for a later durable claim design rather than silently described as solved.

## Implementation

Add a bounded `ClarificationContinuation` resume model beside the answer model. Widen the
HTTP clarification response request to accept exactly one of `answers` or `prompt`, mapping
each to its own typed resume discriminator. The clarification gate parses that union against
the committed request id. Answers emit a request-keyed reducer delta. A continuation appends
one human message, emits no answer entry, clears the pending request, and routes through the
existing target. Reuse the current worker resume action and IPC payload.

## Rationale

The chosen shape is the only option that simultaneously preserves the six-verb edge, uses
LangGraph's required resume mechanism, retains old answer clients, and names the user's new
prompt honestly. The fixed graph target makes continuation a property of the current run,
while transcript append preserves provenance and lets downstream agents reinterpret the task
without deleting history.

## Consequences

- A user may dismiss the questionnaire locally and submit a new prompt later without cancelling.
- The backend remains parked until prompt submission; no abandonment side effect is introduced.
- Downstream stages receive the new prompt exactly once through normal message state.
- Engine and dashboard schemas still require synchronized additive support for the prompt field.
- Concurrent competing clarification resolutions remain an open control-journal hardening item.
