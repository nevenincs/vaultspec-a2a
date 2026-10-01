---
tags:
  - '#adr'
  - '#clarification-continuation'
date: '2026-08-02'
modified: '2026-10-01'
body_schema: 'body-v1'
body_hash: 'sha256:151c01290ebd4256faa976aebc85b26ac329d6b35277041bc5a81fa04010a4a1'
related:
  - "[[2026-08-02-clarification-continuation-research]]"
  - "[[2026-08-02-clarification-continuation-reference]]"
  - '[[2026-10-01-run-continuation-adr]]'
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

## Amendment - run-continuation (2026-10-01)

The Considered options entry for routing ordinary messages across a parked clarification
rests on a now-false premise. Superseded sentence: "Rejected because the message verb is
outside the engine whitelist and ingest cannot cross an interrupt." The message verb is a
published verb of the R6 surface (`2026-07-14-a2a-edge-conformance-adr`), so the whitelist
half no longer holds. Replacement: rejected because ingest cannot cross an interrupt, and
because a message admitted here would wait behind a pause only an answer can clear. The
ruling is unchanged - a parked run still refuses an ordinary message and the typed respond
verb remains the only continuation for it - and `2026-10-01-run-continuation-adr` extends it
to the busy and settled states. Grounding: `2026-10-01-run-continuation-research`.
