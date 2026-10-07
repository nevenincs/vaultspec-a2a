---
tags:
  - '#adr'
  - '#clarification-continuation'
date: '2026-08-02'
modified: '2026-10-07'
body_schema: 'body-v1'
body_hash: 'sha256:23c560691143339f9755a73d4587ef64e2354ad8c19dcd61a55c97f556998055'
related:
  - "[[2026-08-02-clarification-continuation-research]]"
  - "[[2026-08-02-clarification-continuation-reference]]"
  - '[[2026-10-01-run-continuation-adr]]'
  - '[[2026-10-06-codebase-remediation-audit]]'
  - '[[2026-08-05-served-capability-contract-state-truthfulness-adr]]'
  - '[[2026-08-02-control-action-leases-adr]]'
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

## Amendment (2026-10-07): the checkpoint is the pause authority for every interrupt kind

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

**Change.** The run's checkpoint is the only authority for whether a run is parked, on which interrupt and under which request id, for every interrupt kind: clarification, tool permission, plan approval and document approval. The control plane runs one pause mechanism over the graph's one `interrupt()` and one `RESUME`.

- **Durable rows are journal, audit and disclosure cache.** A `permission_requests` row and its creation action are the request's journal: they hold its lifecycle and cache the description and offered options for disclosure. The decision record is `permission_logs`, per the 2026-10-07 amendment of `2026-08-02-control-action-leases-adr`. No row opens, closes or answers a pause, and no row's status is read as proof of one.
- **One pause recorder.** The shipped `reconcile_clarification_pause` (`src/vaultspec_a2a/control/clarification_service.py:764-819`, commit 8a6fbe62) generalizes into one recorder for every `InterruptType`. It owns both edges of `INPUT_REQUIRED` and is that state's obligated writer under T2 of `2026-08-05-served-capability-contract-state-truthfulness-adr`. It keeps the shipped properties:
  - the checkpoint read decides, and a relayed frame only prompts the read;
  - the write witness is read before the checkpoint, so an election that loses to a newer writer changes nothing;
  - the status is elected under the current writer's identity, whichever graph-run dispatch raised the pause, with no new control-action type and no migration;
  - it runs on the progress nudge, on the resume application receipt and at startup.
- **The permission election moves into it.** `_persist_permission_request` (`src/vaultspec_a2a/control/event_handlers.py:889-1002`) keeps only the journal and audit rows. Removed: its election under a `PERMISSION_REQUEST_CREATED` writer receipt (`:958-968`), the receipt check `_permission_receipt_is_current` (`:874-886`), and the settlement's unfenced `RUNNING` write (`src/vaultspec_a2a/control/_event_application.py:258`).
- **Ruling on the permission park receipt.** A permission park elects under the current writer, as a clarification does. The receipt checks are reworked:
  - recovery recognizes a park by `INPUT_REQUIRED` plus a pending interrupt on the checkpoint, never by the writer's action type (replaces `src/vaultspec_a2a/control/recovery_authority.py:390-398`);
  - the respond verb still leases `PERMISSION_RESPONSE_SUBMITTED` against the current writer expectation (`src/vaultspec_a2a/control/permission_service.py:779-806`), and reads from the live checkpoint whether the request is pending and which options it offers;
  - the journal row's replay idempotency rests on its `permission-request:{request_id}` reservation alone (`event_handlers.py:931-941`).
- **Supersession and reopening follow the checkpoint.** A new request supersedes only requests the checkpoint no longer holds, and a re-park under an existing request id is a park (replaces `event_handlers.py:952-957,972-976`).
- **One vocabulary and one id.** One `InterruptType` StrEnum in `src/vaultspec_a2a/thread/enums.py` names the four kinds with today's wire strings. One `interrupt_request_id` in `src/vaultspec_a2a/thread/snapshots.py` resolves the request id for the stream, run-status and the worker. The divergent fallbacks (`thread/snapshots.py:703-707`, `src/vaultspec_a2a/streaming/_interrupt_projection.py:144-156`) and the duplicate clarification type constants (`thread/snapshots.py:78`, `thread/clarification.py:87`) fold into them.
- **One leased re-entry builder.** A new `src/vaultspec_a2a/control/leased_dispatch.py` builds every follow-on dispatch of an accepted run: follow-up, permission response, clarification response, verdict resume and cancel. It resolves the workspace root, accepted definition and execution authority, builds the `DispatchRequest`, runs the lease tail, and returns a typed `FailureType` failure, never an HTTP status. It computes the recursion budget once as `min(operator ceiling, preset)` and freezes it into the accepted envelope; the worker consumes it as supplied. The copied preambles (`control/clarification_service.py:577-614`, `control/permission_service.py:726-777`, `control/message_service.py:225-285`, `control/verdict_subscriber.py:602-642`) and the divergent budget source (`control/message_service.py:283`) are removed.
- **One settlement owner and one recovery owner.** `commit_proven_application` (`src/vaultspec_a2a/control/_event_application.py:193`) settles every graph-mutating action from its proven receipt. That includes a clarification `RESUME`, matched by its `clarification_resolution_receipts` entry through a typed intent rather than an idempotency-key prefix. `control/direct_control_recovery` is the only recovery owner. Removed: `redrive_clarification_actions` (`control/clarification_service.py:822-879`, called once at `src/vaultspec_a2a/api/app.py:743-760`) and the service's own receipt settlement (`control/clarification_service.py:323,388,753`). The startup trigger the redrive carried moves to the recorder.

**Why.** The graph has one pause mechanism (`src/vaultspec_a2a/graph/nodes/_worker_permissions.py:267`, `src/vaultspec_a2a/graph/nodes/clarification.py:369`, `src/vaultspec_a2a/worker/executor.py:202-229`). The control plane ran two: a permission mirror that elects status and validates answers, and a checkpoint-only clarification that elected nothing until 8a6fbe62. The mirror diverges from the checkpoint and strands requests. It supersedes a parallel branch the worker can still answer (`event_handlers.py:972-976`), persists fabricated options (`streaming/_interrupt_projection.py:278-326`), and refuses to reopen a request the worker re-parked (`event_handlers.py:952-957`). The clarification rule already makes the checkpoint authoritative for disclosure. Follow-ups escaped the operator ceiling because each verb chose its own budget source. Evidence: R4-F1, R4-F2, R4-F3, R4-F8, R4-F9 and R2-F2 in `2026-10-06-codebase-remediation-audit`.

**Constraints.** Wire strings, the edge verbs and the typed respond verbs are unchanged. The builder and the two owners implement `2026-08-02-control-action-leases-adr` ("The accepted request explicitly supplies the recursion budget"; "Startup and ordinary operation drain the same durable recovery owner") and add no lease policy. What a provider hears when a run parks is not ruled here.

**Replaces.** No ruling of this record is reversed. The Considerations line "Checkpoint request identity remains authoritative for every resolution" now also covers the pause itself, for every interrupt kind.
