---
tags:
  - '#adr'
  - '#run-continuation'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:21f03b4269cd6e53dd315d2769035894652301dcf773f62b91c43c95ee185887'
related:
  - "[[2026-10-01-run-continuation-research]]"
  - "[[2026-09-24-architecture-review-audit]]"
  - "[[2026-09-24-architecture-review-research]]"
  - "[[2026-08-02-clarification-continuation-adr]]"
  - "[[2026-08-02-control-action-leases-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-02-26-protocol-ecosystem-bridge-adr]]"
  - '[[2026-08-05-served-capability-contract-state-truthfulness-adr]]'
---

# `run-continuation` adr: `enqueue-one continuation for a busy run; typed respond for a parked one; new run for a settled one` | (**status:** `accepted`)

## Problem Statement

`POST /v1/runs/{run_id}/messages` is published and refuses in every lifecycle state, so
the versioned surface can start a run and watch it but can never say anything further to
it. The route itself says so, and its 202 is documented as not served
(`src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py:238-307`). That is a holding
position taken when the previous behaviour was found to quarantine the run, not a
continuation model. A decision is needed now because the refusal shape has already
changed on the dashboard edge, because three audit findings and an accepted ADR's
unbuilt commitments all wait on it, and because every further lifecycle change to this
verb costs another cross-repository contract event. Grounding:
`2026-10-01-run-continuation-research` and `2026-09-24-architecture-review-audit`
(`followup-on-busy-run`, `followup-verb-has-no-reachable-success`,
`run-busy-refusal-contract`, `single-run-threads`, `content-derived-idempotency`,
`settled-prune-early-receipt-window`).

## Considerations

- The four named strategies are a LangSmith Deployment feature and are absent from the
  locked `langgraph@1.2.12`; whichever is chosen is this repository's own control-plane
  code (`2026-10-01-run-continuation-research`).
- Run write authority is single-holder and receipt-bound: a second accepted action on a
  live run refuses the in-flight turn's own terminal as `PRIOR_ACTION`
  (`src/vaultspec_a2a/thread/checkpoint_evidence.py:76-95`).
- A turn ending is a run ending today: the graph reaching END settles the run COMPLETED,
  and COMPLETED's only outgoing transition is ARCHIVED
  (`src/vaultspec_a2a/thread/transitions.py:77-80`).
- `2026-08-02-control-action-leases-adr` already commits to journal-owned pending
  delivery, one renewable dispatcher per run, per-run and service queue limits, and a
  busy worker never removing accepted work. None of it is built; Steps `W02.P04.S16`,
  `W02.P04.S17`, `W02.P04.S18` of `2026-09-05-embedded-runtime-remediation-plan` own it.
- A parked run already has a continuation path: the typed clarification respond verb's
  `prompt` outcome (`2026-08-02-clarification-continuation-adr`).
- The settled-history prune keeps each namespace's latest checkpoint, so a settled run's
  final state survives (`src/vaultspec_a2a/database/checkpoint_retention.py:132-145`).
- Any admitting state changes a published 409 and is a contract event with the dashboard
  under `2026-07-14-a2a-edge-conformance-adr` R6.

## Considered options

- **Enqueue-one behind the in-flight turn, deferring terminal settlement (chosen).**
  Accepts at most one queued continuation per run, promotes it when the in-flight turn's
  terminal checkpoint is proven, and settles the run terminally only when the queue is
  empty. Reuses the accepted lease machinery; costs a deferred terminal frame.
- **Keep refusing in every state.** Honest and cheap, but leaves a published verb with
  no reachable success and leaves the accepted queue commitments permanently unbuilt.
  Rejected as a decision, retained as the behaviour for the states this record does not
  open.
- **Reject on busy; continuation only as a new run in the same context.** The A2A
  reference shape: Agent Server starts a new task per turn inside one `contextId`
  (`2026-10-01-run-continuation-research`). Rejected as the busy answer because it makes
  every interjection a user-visible run boundary and needs the multi-run thread model
  the A2A-capability decision owns; adopted as the SETTLED answer, where it costs
  nothing.
- **Interrupt: stop the in-flight turn at a superstep boundary and resume with the new
  input.** Rejected: it discards accepted work, and the vendor's own page warns that a
  tool call may be half-executed at the cut, which here means a provider CLI's
  filesystem and terminal effects with no compensating action.
- **Rollback: discard the in-flight turn and its record.** Rejected outright: it deletes
  durably accepted work, contradicting `2026-08-02-control-action-leases-adr`, and
  destroys the audit trail the permission and authoring lanes depend on.
- **Steer: inject text into the live turn.** Rejected as unavailable, not merely
  undesirable. LangGraph offers no mid-node input channel, provider sessions here last
  one model call, and Codex's `turn/steer` requires an addressable live turn this
  service does not expose.
- **Revive a settled run in place.** Rejected: it needs a reverse transition out of a
  terminal state, makes the already-emitted terminal event false for every consumer that
  settled on it, and re-arms `settled-prune-early-receipt-window`.

## Constraints

Binding:

- The messages route is never an answer path. A run parked on `input_required` refuses,
  whether the pause is a clarification or a permission request, and the refusal names
  the typed respond verb. This holds under enqueue for a second reason: a queued turn
  behind a pause would wait for a pause only an answer can clear.
  `.vaultspec/rules/clarifications-are-typed-interrupts.md` is unchanged by this record.
- At most one continuation is queued per run. The limit is a configured positive value
  with a served initial value of 1, paired with a configured service-wide cap. Exceeding
  either is a typed refusal, never a silent drop and never an unbounded queue.
- A run never leaves a terminal state. Continuation after settlement is a new run, and
  nothing in this record adds a transition out of COMPLETED, FAILED, CANCELLED,
  ARCHIVED, or DELETING.
- Follow-up admission and terminal settlement serialize on the same run write
  transaction. A continuation either queues before settlement, and defers it, or meets a
  settled run and refuses. No third outcome exists, which is what keeps
  `settled-prune-early-receipt-window` unreachable.
- Exactly one action holds a run's write authority at a time. A queued continuation is a
  reserved journal action with a lease and no receipt; it acquires the run's write
  authority only at promotion, after the predecessor's terminal checkpoint evidence
  commits.
- A queued follow-up requires a client-supplied idempotency key. Content-derived keys are
  retired for this verb because two deliberate identical continuations are two turns.
- A worker `run_busy` 409 is a semantic conflict about one run. It never opens the shared
  failure breaker and never discards accepted work.
- Each promoted turn carries its own complete accepted dispatch envelope under
  `2026-08-02-control-action-leases-adr`, including its own recursion budget from the
  run's accepted graph definition rather than a global or team fallback.
- The run's execution deadline is re-derived at each promotion and the total run lifetime
  is bounded by a configured maximum. A queue cannot make a run immortal.

Implementation hypotheses, revisable within the constraints: the served per-run queue
depth of 1; the deadline arithmetic at promotion; the bounded transcript depth used to
seed a successor run; whether promotion is driven from the terminal event handler or
from the durable recovery dispatcher.

## Implementation

We will admit exactly one queued continuation on a busy run, keep the typed respond verb
as the only continuation for a parked run, and answer a settled run with a new run that
names its predecessor. The three lifecycle answers are decided together because they are
one question asked of three states.

**Busy (SUBMITTED, RUNNING).** `can_send_followup` returns allowed for these two states
(`src/vaultspec_a2a/thread/message_policy.py:50-82`); CANCELLING stays refused as
`run_busy` because the run is leaving. `send_followup_message` reserves the journal
action and its lease as it does today
(`src/vaultspec_a2a/control/message_service.py:258-297`) but does NOT bind a graph action
receipt, does NOT install the new writer, and does NOT dispatch. It records a queue
position and returns `202` with `action_status="queued"`. A second continuation while one
is queued refuses `409 queue_full`; a repeat of the same idempotency key replays the
queued action and its position; a different payload under that key refuses `conflict`.

**Promotion.** When a proven terminal checkpoint arrives for the run, the control plane
checks the queue inside the same write transaction before settling. With a queued action
present it promotes instead of settling: it binds the graph action receipt, installs the
writer, re-derives the deadline, dispatches the ingest, and leaves the run RUNNING. No
terminal event is published, no terminal settlement is scheduled, and no settled-history
prune runs. With an empty queue it settles exactly as today
(`src/vaultspec_a2a/control/event_handlers.py:662-702`). Promotion is a durable recovery
attempt under the existing lease machinery, so a crash between settlement and dispatch
leaves the queued action eligible again without changing its identity.

**Parked (INPUT_REQUIRED).** Unchanged refusal, with the message narrowed to name the
respond verb for the pause the run actually holds.

**Repairing (REPAIR_NEEDED, RECONCILING).** Unchanged refusal. The served code stays
`terminal` even though these states are not terminal: re-coding a published value is a
contract event with no behavioural gain, and it is better taken with the A2A-capability
decision if that record introduces a wider state vocabulary.

**Settled (COMPLETED, FAILED, CANCELLED, ARCHIVED, DELETING).** Unchanged refusal.
`run-start` gains an optional `continues_run_id`; the successor run seeds its graph input
from the predecessor's surviving final checkpoint and records the link, and `run-status`
discloses it. This is deliberately a single-parent lineage link and not an A2A
`contextId`: it carries no protocol commitment, and the A2A-capability ADR may later map
a context onto a chain of these.

Surfaces that change: `src/vaultspec_a2a/thread/message_policy.py`,
`src/vaultspec_a2a/control/message_service.py`,
`src/vaultspec_a2a/control/event_handlers.py`,
`src/vaultspec_a2a/control/direct_control_recovery.py`,
`src/vaultspec_a2a/thread/idempotency.py`, `src/vaultspec_a2a/api/schemas/gateway.py`,
`src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py`, and one migration adding the
queue position and queued result status to the control-action journal.

Schema changes: `RunMessageResponse.action_status` serves `queued`;
`RunMessageRefusalCode` gains `QUEUE_FULL`; `RunStatusResponse` gains a bounded
`queued_messages` count and a nullable `continues_run_id`; `RunStartRequest` gains an
optional `continues_run_id`. A missing `Idempotency-Key` on this verb is a `422`, not a
lifecycle refusal.

Verification the work owes, as real-behaviour tests against the live gateway and worker:
a continuation queued during a real in-flight turn runs after it with no RECONCILING and
no refused terminal; a run with a queued continuation emits no terminal frame at the
first turn's end and one at the second's; a second continuation refuses `queue_full`
while the first is queued; a repeat idempotency key replays the position and a changed
payload refuses `conflict`; a continuation racing terminal settlement either queues or
meets `terminal`, never both; a worker `run_busy` 409 leaves the breaker closed and the
accepted work intact; a gateway kill between settlement and promotion promotes once on
restart; and the existing
`test_every_lifecycle_status_resolves_to_a_typed_answer` is extended to assert the
queued answer for the two admitting states.

## Reconciliation of existing ADR wording

Proposed here, applied only on authorization; no other record is edited by this draft.

- `2026-08-02-clarification-continuation-adr`, Considered options. Current wording
  rejects routing ordinary messages across a parked clarification "because the message
  verb is outside the engine whitelist and ingest cannot cross an interrupt". The first
  half is now false: the message verb is a published verb of the R6 surface. Proposed
  replacement: "Rejected because ingest cannot cross an interrupt, and because a message
  admitted here would wait behind a pause only an answer can clear." The ruling is
  unchanged; only its stale ground is replaced.
- `2026-08-02-control-action-leases-adr`, Implementation, the pending-delivery paragraph.
  Current wording has one dispatcher draining "eligible messages in durable acceptance
  order" without saying what makes a message eligible. Proposed addition after that
  sentence: "A follow-up is eligible only once the predecessor turn's terminal checkpoint
  evidence has committed; the per-run queue limit is one, and promotion defers the run's
  terminal settlement rather than reviving a settled run." This refines the same decision
  and does not reverse it.
- `2026-08-02-control-action-leases-adr`, Implementation, the breaker paragraph. Current
  wording exempts worker saturation only. Proposed addition: "A worker's `run_busy`
  refusal is likewise a semantic conflict about one run, not transport failure; it does
  not open the shared breaker, and it retains the action lease because the worker is
  executing that run." This also settles the open finding
  `run-busy-not-in-the-recovery-lease-release-set`.
- `2026-08-05-served-capability-contract-state-truthfulness-adr`, T2 and T3. A run whose
  turn ended with a queued continuation is RUNNING with no live worker for the width of
  the promotion window, which T3's abandoned-transition reconciler would move to a
  terminal value and so silently drop the queued turn. Proposed addition to T2: "A run
  holding a queued continuation names the promotion dispatcher as the writer obliged to
  leave RUNNING; T3's reconciler treats it as owned, not abandoned, until that action's
  lease expires." T6 needs no change and is satisfied by construction: this record
  reopens no terminal result, it defers entering one.
- `2026-07-14-a2a-edge-conformance-adr`, R6. Proposed addition in the style of the
  existing 2026-07-19 discovery-event paragraph, recording two additive contract events:
  the messages verb gaining a reachable 202 with `action_status="queued"`, a sixth
  refusal code `queue_full`, and a `queued_messages` disclosure on run-status; and
  `run-start` plus `run-status` gaining an optional `continues_run_id`. The paragraph
  must also state the behavioural change neither schema shows: a run with a queued
  continuation emits no terminal frame at the end of its first turn, so a consumer must
  not treat a quiet turn boundary as completion.
- `2026-02-26-protocol-ecosystem-bridge-adr` is NOT edited by this decision: its heading
  still reads `proposed`, so it is not an accepted home for this record's wording, and its
  own proposed A2A-drop remains an open item this decision does not resolve. The
  clarifying sentence - "Adopting A2A's new-task-in-the-same-context SHAPE for a settled
  run is not adopting the protocol; `continues_run_id` is a local lineage link and the
  A2A-capability question stays open." - is instead carried in the amendment this record
  adds to `2026-07-14-a2a-edge-conformance-adr` R6.
- No change is proposed to `.vaultspec/rules/clarifications-are-typed-interrupts.md`. Its
  prohibition holds verbatim and this decision strengthens it.

## Rationale

Enqueue-one wins on a knockout the other busy-state options fail: it is the only one that
neither destroys durably accepted work nor requires a capability the stack does not have.
Interrupt and rollback both cut a turn that may hold half-finished provider side effects,
and rollback additionally deletes the record; steer has no injection point in LangGraph,
in this service's per-call provider sessions, or in its worker dispatch path. Reject is
defensible but leaves a published verb permanently unreachable and an accepted ADR's
queue commitments permanently unbuilt.

Deferring terminal settlement, rather than reviving a settled run, is what makes enqueue
fit a service where a run is a thread with one turn. It adds no state transition, keeps
the terminal event truthful for every consumer, and leaves the settled-history prune and
its accepted early-receipt risk exactly where they are. The cost is a delayed terminal
frame, which is the honest signal: the run has not ended.

The settled case takes the A2A reference answer because that is where it is free. Agent
Server itself rejects a message naming a terminal task and starts a new task in the same
context (`2026-10-01-run-continuation-research`); copying the shape without the protocol
gives continuity at the price of one optional field.

## Consequences

- The published 202 becomes reachable, and the refusal vocabulary grows by one code. Both
  are additive; existing clients that only ever see 409 keep working.
- A run's terminal frame can arrive one or more turns after a turn ends. Any consumer
  inferring completion from a quiet stream breaks; this is the contract event's most
  important sentence.
- Checkpoint growth per run rises with conversation length, against no retention policy
  until the run settles (`checkpoint-growth`, `mounted-content-checkpointed`). A
  multi-turn run is the first workload that makes the open context-window decision
  urgent.
- `breaker-fed-by-backpressure` becomes a prerequisite rather than a standalone finding:
  a promotion path that retries delivery must not open the shared breaker first.
- Steps `W02.P04.S16`, `W02.P04.S17`, and `W02.P04.S18` gain their missing policy input
  and can be executed against this record rather than against an undecided queue shape.
- Reconsider if a measured multi-turn run shows the deferred terminal confusing recovery
  more than it helps, if the dashboard declines the delayed-terminal semantics, or if the
  A2A-capability decision adopts a multi-run thread, which would make a turn boundary a
  run boundary and retire the deferral entirely.

Accepted 2026-10-01 under the user's blanket approval of that date.

## Amendment 2026-10-01: a failed or cancelled turn refuses its continuation

Promotion waits behind a proven terminal checkpoint, which only a completed turn
produces; a turn that settles FAILED or CANCELLED settles from failure or cessation
evidence and is not the boundary a continuation queued behind. Such a run settles with
its own terminal, and every continuation queued on it is refused in the same settlement
transaction with `rejected_invalid_state`, its position retained and `applied_at` set.
It is never promoted past a failed turn and never left waiting on a settled run, which
would be the silent drop the binding constraints forbid. A client that wants to go on
after a failure starts a new run naming its predecessor, as for any settled run.

Promotion is durable and its delivery belongs to the existing recovery dispatcher, the
revisable hypothesis this record names; the abandonment bound for a promoted turn is the
action's run-derived recovery deadline, and for a still-queued continuation its claim
lease. Evidence: the P02-P03 execution of `2026-10-01-run-continuation-plan`, recorded in
`2026-10-01-run-continuation-audit` as `queued-continuation-survives-a-failed-or-cancelled-run`.

Accepted 2026-10-01 under the user's blanket approval of that date.
