---
tags:
  - '#research'
  - '#run-continuation'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:cb571b8c999f29ba7e2899a733e1513156c344d66055243db66c8c07e562db93'
related:
  - "[[2026-09-24-architecture-review-audit]]"
  - "[[2026-09-24-architecture-review-research]]"
---

# `run-continuation` research: `multitask and continuation models for a busy, parked, or finished run`

What should `POST /v1/runs/{run_id}/messages` do when a run is RUNNING, parked on
`input_required`, or settled? The verb is published and refuses in every lifecycle
state, so the versioned surface can start a run and watch it but can never say anything
further to it. This record gathers the external baseline and the local mechanics that
bear on the choice; `2026-09-24-architecture-review-audit` names the decision as owed
and does not make it. Evidence picture: the four named strategies come from a hosted
product, not from the framework this service runs, so none of them arrives as library
behaviour; two of the four are unavailable here for reasons that are structural rather
than effort; and the local control plane already carries most of the machinery a queued
continuation needs, declared in an accepted ADR and not yet built.

## Findings

### The four multitask strategies are a LangSmith Deployment feature, not a LangGraph one

`reject`, `enqueue`, `interrupt`, and `rollback` are selected per run through the
`multitask_strategy` field of the Agent Server runs-create call, and the hosted docs
state plainly that "these features belong to LangSmith Deployment only and are
unavailable in the open-source LangGraph framework"
(https://docs.langchain.com/langsmith/double-texting). The SDK reference confirms the
field and its closed vocabulary - "must be one of 'reject', 'interrupt', 'rollback', or
'enqueue'" - with no client-side default
(https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/create);
the guide names `enqueue` as the server's default. This service locks `langgraph@1.2.12`
and `langgraph-checkpoint@4.2.0` (`uv.lock`) and runs no Agent Server, so whichever
strategy is chosen is this repository's own control-plane code, not a configuration
value. The framework offers no concurrency control for two concurrent invocations on one
`thread_id`; the hosted server supplies it above the graph.

### Each strategy's cost is set by what it does to the in-flight turn's checkpoint

`enqueue` "allows the current run to finish before processing any new input": nothing is
cancelled and the second input waits. `reject` "rejects any additional incoming runs
while a current run is in progress". `interrupt` "halts the current execution and
preserves the progress made up to the interruption point", keeps the first run in the
database with status `interrupted`, and starts the new input from the saved state; the
same page warns that "a tool call may have been initiated but not yet completed", so
partial external effects are the caller's problem
(https://docs.langchain.com/langsmith/interrupt-concurrent). `rollback` "interrupts the
prior run of the graph and starts a new one", and "the first run is completely deleted
from the database and cannot be restarted"
(https://docs.langchain.com/langsmith/rollback-concurrent). Interrupt and rollback are
therefore both destructive to accepted work; rollback additionally destroys the record
of it.

### Codex separates steering from interrupting; steering mutates a live turn

`turn/steer` appends "more user input to the active in-flight turn" and takes
`threadId`, `input`, and an `expectedTurnId` that must match the active turn; it fails
when no turn is active, accepts no turn-level overrides, and emits no turn-started
notification. `turn/interrupt` takes `threadId` and `turnId` and the turn "finishes with
status: interrupted". Steering is additive to a running turn, interrupting ends it
(https://learn.chatgpt.com/docs/app-server). The same server exposes `thread/resume` and
`thread/fork`, the latter branching a thread into a new id optionally truncated at a
`lastTurnId`. Steer has no analogue in this service: a provider session here lasts one
model call (`per-call-provider-sessions` in `2026-09-24-architecture-review-audit`), and
the turn boundary a steer would target is a LangGraph superstep this service does not
expose a mid-flight input channel to.

### A2A permits a message to a working task and forbids one to a terminal task

The specification restricts only terminal states: "messages sent to Tasks that are in a
terminal state (`TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, `TASK_STATE_CANCELED`,
`TASK_STATE_REJECTED`) cannot accept further messages", answered with
`UnsupportedOperationError`; it does not prohibit a message naming a task in
`TASK_STATE_WORKING`, and leaves the agent's behaviour there unspecified
(https://a2a-protocol.org/latest/specification/). `contextId` "logically groups multiple
Task objects and Message objects that are part of the same conversational context", and
`SendMessage` "MAY be idempotent", with agents free to "utilize the messageId to detect
duplicate messages". The reference deployment resolves the unspecified case by not using
it: Agent Server maps `contextId` to `thread_id` and "each turn starts a new task inside
the same context - send the `contextId` alone", rejecting a message that names a
terminal task with `-32004` (https://docs.langchain.com/langsmith/server-a2a). So the
protocol's own reference implementation answers continuation with a NEW task in the same
context rather than with a second message into a live one.

### LangGraph's resume contract makes a mid-turn injection unsafe here

Resuming passes `Command(resume=...)`, whose value "becomes the return value of the
`interrupt()` call", and on resume "the runtime restarts the entire node from the
beginning - it does not resume from the exact line where `interrupt()` was called", so
side effects before an interrupt "should (ideally) be idempotent"
(https://docs.langchain.com/oss/python/langgraph/interrupts). A drained run resumes with
`invoke(None, config)` on the same `thread_id`, and drain "is cooperative and operates
between supersteps, never preempting work that is already running"
(https://docs.langchain.com/oss/python/langgraph/fault-tolerance). The only sanctioned
injection point is therefore a parked interrupt or a fresh invocation at a superstep
boundary; there is no supported way to hand new text to a node that is mid-execution.

### Admitting a follow-up on a RUNNING run quarantines the run today

This is the local mechanism the chosen model must avoid re-creating. Accepting a
follow-up installs it as the run writer and binds a new graph action receipt
(`src/vaultspec_a2a/control/message_service.py:258-297`). The worker refuses a thread it
is already executing with a typed 409 `run_busy` rather than 429, because "a thread that
is already running is a semantic conflict about one run, while a full worker is
backpressure about all of them" (`src/vaultspec_a2a/worker/app.py:358-376`,
`src/vaultspec_a2a/worker/executor.py:353-370`). The in-flight turn's own terminal is
then refused as `PRIOR_ACTION` evidence because the active receipt no longer matches
(`src/vaultspec_a2a/thread/checkpoint_evidence.py:76-95`), and the run quarantines to
RECONCILING at its deadline. The refusal in force today therefore protects a real
invariant: run write authority is single-holder and receipt-bound.

### Every lifecycle state currently refuses, and the refusal vocabulary is already closed

`can_send_followup` refuses `input_required` as `INPUT_REQUIRED`, `repair_needed` and
`reconciling` as `TERMINAL`, `submitted`, `running`, and `cancelling` as `RUN_BUSY`, and
every member of `NON_ACTIVE_STATUSES` as `TERMINAL`
(`src/vaultspec_a2a/thread/message_policy.py:26-82`). Those groups exhaust
`ThreadStatus` (`src/vaultspec_a2a/thread/enums.py:45-56,290-315`), so the `allowed=True`
branch is unreachable, which is the audit's `followup-verb-has-no-reachable-success`.
The edge serves that as `409` with a closed `RunMessageRefusalCode` of `input_required`,
`terminal`, `conflict`, `incompatible_state`, `run_busy`
(`src/vaultspec_a2a/api/schemas/gateway.py:716-750`), and documents on the route that no
state admits a follow-up and the 202 is not served
(`src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py:238-307`). Any admitting
state is an additive change to a published 409, which is what makes it a dashboard
contract event.

### The enqueue machinery is already an accepted commitment and is not built

`2026-08-02-control-action-leases-adr` already rules that "the journal owns pending
delivery", that "one renewable dispatcher per run drains eligible messages in durable
acceptance order during ordinary operation and after restart", that "a busy worker never
removes accepted work", that admission "atomically enforces configured positive per-run
and service queue limits before acknowledgement" with "a typed retryable disposition" on
overflow, and that "duplicate requests retain their original position and payload, while
conflicting retries refuse". None of it exists: `ControlActionType` has
`MESSAGE_FOLLOWUP_REQUESTED` and `MESSAGE_FOLLOWUP_APPLIED` but no queued or deferred
member (`src/vaultspec_a2a/thread/enums.py:191-204`), no position or queue-limit column
is written by the message path, and the owning Steps `W02.P04.S16`, `W02.P04.S17`, and
`W02.P04.S18` of `2026-09-05-embedded-runtime-remediation-plan` are open. Enqueue is
therefore the only candidate that needs no new accepted authority for its core
mechanism, only authority for the admitting state and the edge shape.

### Two mechanical obstacles bear on the finished-run case

First, a settled run's checkpoint history is pruned to the latest checkpoint per
namespace on the terminal event, scheduled as a background task
(`src/vaultspec_a2a/control/event_handlers.py:642-654,698`,
`src/vaultspec_a2a/database/checkpoint_retention.py:132-145`). The latest checkpoint
survives, so resuming a completed run from it remains possible, but forking from an
earlier point does not. Second, a terminal state's only outgoing transition is
`ARCHIVED` (`src/vaultspec_a2a/thread/transitions.py:77-80`), so reviving a completed run
in place would need a new reverse transition and would make the terminal event a lie for
every consumer that already settled on it. The audit's `settled-prune-early-receipt-window`
is accepted as currently unreachable precisely because "no run state admits a follow-up
today"; admitting one re-arms it.

### Follow-up idempotency keys are content-derived and would collide in a queue

The default key hashes thread, agent, and content
(`src/vaultspec_a2a/thread/idempotency.py:29-33`), so two identical follow-ups in one run
deduplicate to one. Under reject that is harmless. Under enqueue it silently drops a
deliberate second "continue", and the control-action-leases rule that duplicates "retain
their original position and payload" would be satisfied by the wrong reading of what a
duplicate is. A2A's client-supplied `messageId` deduplication is the baseline alternative
(https://a2a-protocol.org/latest/specification/). Any admitting model must settle whether
the client supplies the key.

### The typed respond verbs stay the only answer path for a parked run

A parked clarification is disclosed authoritatively on run-status as
`pending_clarification` (`src/vaultspec_a2a/api/schemas/gateway.py:553-558`), raised as a
checkpointed `interrupt()` in the gate node
(`src/vaultspec_a2a/graph/nodes/clarification.py:323-375`), and resolved by the typed
respond verb carrying exactly one of `answers`, `prompt`, or `decline`
(`src/vaultspec_a2a/api/schemas/gateway.py:795-837`,
`src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py:399-430`). The `prompt`
outcome is the accepted continuation shape of `2026-08-02-clarification-continuation-adr`
and already covers "the user wants to say something else instead of answering". A
message routed across that pause would start a new turn and orphan the parked interrupt,
which `.claude/rules/clarifications-are-typed-interrupts.md` forbids. This is the one
state where a continuation capability already exists and the correct answer is to point
callers at it.

### Residual local risks that an admitting model inherits

A worker `run_busy` 409 is not in the recovery lease release set
(`src/vaultspec_a2a/control/direct_control_recovery.py:514-520`), so recovery holds the
lease until expiry; the audit records this as unstated and untested. Non-2xx dispatch
outcomes still feed the shared circuit breaker (`breaker-fed-by-backpressure`), so a
queued-delivery retry loop can open it against unrelated runs. Both are named open
findings in `2026-09-24-architecture-review-audit` and are prerequisites for any model
that retries delivery.

### What was not investigated

No live multi-message run was executed: this environment holds no provider credential,
so the queue behaviour under a real long turn is unmeasured. The dashboard repository's
side of the edge was not read, so the consumer cost of an admitting state is stated as a
contract event rather than estimated. Agent Server was not deployed to observe `enqueue`
empirically; its behaviour here is taken from the vendor documentation cited above. No
measurement was taken of checkpoint growth under a multi-turn thread beyond the 22
checkpoints / 2.16 MB figure already recorded in `2026-09-24-architecture-review-audit`.

## Sources

- https://docs.langchain.com/langsmith/double-texting
- https://docs.langchain.com/langsmith/interrupt-concurrent
- https://docs.langchain.com/langsmith/rollback-concurrent
- https://docs.langchain.com/langsmith/server-a2a
- https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/create
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.langchain.com/oss/python/langgraph/fault-tolerance
- https://learn.chatgpt.com/docs/app-server
- https://a2a-protocol.org/latest/specification/
- `src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py:238-307,399-430`
- `src/vaultspec_a2a/api/schemas/gateway.py:553-558,716-750,795-837`
- `src/vaultspec_a2a/thread/message_policy.py:26-82`
- `src/vaultspec_a2a/thread/enums.py:45-56,191-204,290-315`
- `src/vaultspec_a2a/thread/transitions.py:77-80`
- `src/vaultspec_a2a/thread/idempotency.py:29-33`
- `src/vaultspec_a2a/thread/checkpoint_evidence.py:76-95`
- `src/vaultspec_a2a/control/message_service.py:258-297`
- `src/vaultspec_a2a/control/event_handlers.py:642-654,698`
- `src/vaultspec_a2a/control/direct_control_recovery.py:514-520`
- `src/vaultspec_a2a/database/checkpoint_retention.py:132-145`
- `src/vaultspec_a2a/graph/nodes/clarification.py:323-375`
- `src/vaultspec_a2a/worker/app.py:358-376`
- `src/vaultspec_a2a/worker/executor.py:353-370`
- `uv.lock` (`langgraph@1.2.12`, `langgraph-checkpoint@4.2.0`, `langgraph-sdk@0.4.5`)
