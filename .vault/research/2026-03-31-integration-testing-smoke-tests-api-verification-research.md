---
tags:
  - '#research'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
modified: '2026-03-31'
related:
  - '[[2026-03-30-service-layer-research]]'
  - '[[2026-03-30-service-layer-rolling-audit]]'
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
---

# `integration-testing-smoke-tests-api-verification` research: `real-stack service validation strategy`

Research focused on what issue `#17` must prove after PR `#16`: the
repository needs a real integration pipeline that exercises the public
API, worker execution, durable checkpoints, interrupt/resume flows, and
telemetry against the local stack with deterministic outcomes.

## Mission Statement

Issue `#17` exists to restore a small, trustworthy service-certification
gate for the refactored architecture. The gate must prove that the real
gateway, worker, persistence, streaming, and observability layers work
together against the local development stack with deterministic
VidaiMock-backed provider replay. Success means a developer can run the
stack, observe it, interact with it, cancel or resume it, steer it
through approval flows, and see meaningful output without errors, hangs,
or hidden in-process shortcuts.

The main mission is deterministic, stable, repeatable, controllable, and
predictable output from the real pipeline and its full stack. That
requires repo-owned inputs and explicit conditions: exact file contents,
explicit operator actions, interactive workflow steps, and known control
events such as interrupting, resuming, steering, re-briefing, and
cancelling. The certifying gate should prove controllable execution and
meaningful outcomes, not broad live-provider compatibility.

## Findings

### Constraints inherited from PR `#16`

- PR `#16` intentionally removed the old live-test stack and left the
  repo with a new `service` marker reserved for true Layer 3 tests.
  The marker is declared in `pyproject.toml`, and default pytest runs
  explicitly exclude it with `-m "not service"`.
- The service-layer PR positioned issue `#17` as the next gate before
  service orchestration work. The expected direction is real HTTP,
  real worker execution, real persistence, and real provider behavior,
  not `ASGITransport`, not stub providers, and not patched transports.
- Current middleware tests were deliberately thinned to stop at Layer 2.
  `api/tests/conftest.py` uses an in-process FastAPI worker over
  `httpx.ASGITransport`, which is useful for handler/service coverage
  but does not satisfy the issue definition of integration testing.
- Root test configuration currently suppresses OTel exporter noise at
  collection time by setting `OTEL_METRICS_EXPORTER=none` and redirecting
  OTLP traffic to a non-routable address. This is correct for non-service
  tests, but service tests will need an explicit override so traces flow
  into a real collector.

### Concrete local-stack assets already available

- `service/docker-compose.prod.yml` already defines the closest thing to
  a production-like local test target: gateway, worker, shared SQLite,
  and Jaeger with health checks.
- `service/docker-compose.prod.postgres.yml` already provides a database
  overlay, which means SQLite can be the first service-test backend and
  Postgres can be added later as a second matrix once the harness is stable.
- `service/.env.example` already documents the required ports and control
  variables, including gateway, worker, MCP, Jaeger, Postgres, and
  `MOCK_API_BASE` for VidaiMock.
- The provider layer still contains a deterministic tape-driven model in
  `providers/mock_chat_model.py`. It streams over SSE and resolves tapes
  by agent id, which is directly aligned with issue `#17`'s requirement
  for verifiable work without fake model behavior.
- Mock team presets and provider tapes still exist under
  `team/presets/mock/`, which gives the branch a ready-made source of
  deterministic orchestration scenarios.
- The API surface needed by the issue is present in the current code:
  thread creation, list/detail, follow-up messages, cancellation,
  permission response, health endpoints, WebSocket streaming, and MCP.

### Gaps and branch risks visible now

- There are currently zero collected `service` tests in the tree.
  The marker exists, but no fixture, test package, or harness is wired
  around it yet.
- The current `service/` compose files do not include a VidaiMock
  service. PR `#16` deleted the older `docker-compose.integration.yml`
  and `vidaimock.Dockerfile`, so issue `#17` needs to decide whether
  VidaiMock is started as an external subprocess, as a separate container
  via a new compose overlay, or through another deterministic provider path.
- The Justfile has no service-test lifecycle commands yet. It can start
  gateway, worker, UI, and Postgres, but there is no canonical
  `just dev test service` or stack bootstrap/teardown command for issue `#17`.
- The default compose paths target production images and the shared local
  SQLite file. That is useful for realism but raises cleanup/isolation
  requirements for test runs. The harness will need unique database and
  checkpoint paths per run or isolated container volumes per test session.
- Telemetry assertions are possible because Jaeger is present, but there
  is no helper yet for querying trace presence or waiting for export flush.
- The branch already has a draft PR `#22` carrying only `uv.lock` churn.
  That means implementation work should keep the scope sharply focused on
  issue `#17` and avoid accidental coupling to unrelated lockfile drift.

### External reference points and patterns

- LangGraph official docs on interrupts and durable execution reinforce
  the core behavioral contract that this repo should prove in service
  tests: persistent `thread_id`, durable checkpoints, interrupt payloads
  surfacing during streaming, and deterministic/idempotent replay around
  non-deterministic side effects.
- OpenTelemetry official docs require provider shutdown/flush behavior.
  For this repo, that means service tests should assert observable traces
  only after the stack has had a chance to export and flush, not merely
  after the HTTP request returns.
- Testcontainers for Python is a strong venue for database-scoped service
  tests because it supports real Postgres instances with pytest-friendly
  lifecycle control. It is best suited for the later Postgres track, not
  the first gateway+worker+Jaeger+VidaiMock full-stack gate.
- Temporal Python is a useful adjacent reference because it treats
  orchestration testing as integration against a real server and adds a
  dedicated test environment for deterministic replay/time behavior. The
  conceptual takeaway is to keep business-proof tests at the real boundary
  and keep time/control abstractions explicit.
- DeerFlow is a relevant open-source LangGraph project because it keeps a
  dedicated `tests/integration/test_workflow.py` path and leans on
  LangGraph Studio/LangSmith traces for workflow inspection. The relevant
  lesson is separation: keep graph/workflow integration checks distinct
  from unit and middleware layers.

### Recommended direction for issue `#17`

- Establish one canonical session-scoped `service_stack` fixture that owns
  the full stack lifecycle. It should start gateway, worker, Jaeger, and a
  deterministic model backend, wait on health endpoints, and fail hard if
  readiness is not achieved.
- Start with one stable backend path: SQLite + Jaeger + deterministic
  taped provider. This is enough to satisfy the issue while keeping the
  first PR narrow. Postgres should remain a follow-up expansion or a
  second matrix only after the main harness is green.
- Treat the test suite as scenario-driven, not endpoint-driven. Each test
  should prove a meaningful workflow outcome: thread completion with
  expected final content, interrupt emission followed by permission
  approval and successful resume, follow-up message yielding a second
  meaningful assistant turn, cancel reaching terminal cancelled state,
  and health/telemetry proving the stack wiring.
- Prefer black-box API assertions over internal DB poking for the main
  path. Internal database inspection is useful only as a secondary oracle
  when the public API cannot expose the required state transition clearly.
- Add one minimal telemetry assertion to the service suite. It does not
  need full trace-shape verification in the first pass; proving that the
  request generated at least one exported trace tied to the workflow path
  is enough to show the pipeline is instrumented end to end.
- Keep MCP as an optional second wave unless the current MCP route can be
  brought up cheaply inside the same stack. The core unblocker for issue
  `#17` is public API + worker + replayable provider + interrupt/streaming,
  not breadth for its own sake.

### Audit roadmap for follow-on hardening

- Audit 2b: VidaiMock tape brittleness and template-semantics audit.
  This slice is now proven against the compose-backed service lane. The
  original human-loop tape was brittle because it selected approval,
  denial, and invalid-outcome branches from total message count and a
  fixed resumed-message index. Online VidaiMock docs and direct
  verification against the real VidaiMock process showed two additional
  constraints that matter for this repository: inline `response_body`
  parsing is narrower than the broader Jinja-style constructs the first
  revisions attempted, and complex branching must be proven against the
  real binary rather than assumed from generic template intuition.

  The current certified contract is narrower and more explicit:
  - use a file-backed `response_template` rather than complex inline
    `response_body` branching
  - keep the provider contract tied to the last serialized message,
    which is the worker-owned resume payload on resumed turns
  - branch only on stable tool payload outcomes: approval, denial, and
    invalid option handling
  - prove each branch directly against the real VidaiMock process before
    accepting the tape into the deterministic gate

  This keeps the main mission intact: deterministic, stable, repeatable,
  controllable output from the real stack using repo-owned inputs. It
  also narrows the remaining risk: the tape is no longer coupled to total
  message count or a fixed absolute index, but it still depends on the
  repo-owned convention that the resumed tool result is serialized as the
  last message.

- Interrupt/resume correctness for human approval callbacks.
  Map to LangGraph `interrupt()` semantics, `Command(resume=...)`, and
  checkpoint-backed resumption on the same `thread_id`. The audit should
  prove the worker pauses at approval boundaries, persists state, and
  resumes only with a validated approval payload.
- Streaming and tool-call continuity.
  Map to LangGraph `astream_events(..., version="v2")`, stream event
  propagation, and SSE continuity across disconnect/reconnect. The audit
  should prove stable tool-call chunks and coherent public streaming
  through interrupts and resume.
- Deterministic provider replay with VidaiMock.
  Map to the async `BaseChatModel` wrapper, SSE-backed model chunks, and
  stable tape selection by agent/model ID. The audit should prove that
  the certification gate stays deterministic and does not depend on sync
  generation paths or live provider availability.
- Cancellation and terminal-state cleanup.
  Map to LangGraph cancellation semantics distinct from
  interrupt/resume. The audit should prove cancellation terminates work
  cleanly, emits the expected terminal state, and does not leave zombie
  execution or misleading success traces.
- Multi-agent steering, re-briefing, and supervisor routing.
  Map to LangGraph multi-agent orchestration, supervisor routing,
  handoffs, and state refresh before re-routing. The audit should prove
  the orchestrator can steer a task, re-brief on updated state, and
  avoid stale or duplicated routing decisions.
- Persistence, corruption, and resumability.
  Map to checkpointer-backed replay, state snapshots, and recovery from
  partial or inconsistent thread state. The audit should prove restart
  and replay behavior is visible, durable, and not silently repaired in
  a way that hides corruption.
- Permission hardening and hostile approvals.
  Map to approval-option validation, scope enforcement, and payload
  sanitization for interactive control flows. The audit should prove
  approvals cannot be forged, reused across threads, or escalated by
  malformed resume data.
- Artifact persistence and file-removal safety.
  Map to persistent artifact handling, file-write/file-delete
  operations, and bounded destructive behavior in sandboxed execution.
  The audit should prove artifacts remain attributable to the correct
  thread/agent and that destructive file operations are explicit,
  bounded, and observable.

### LangGraph interrupt/resume clarification for the service lane

The permission/resume boundary has two separate truths that must not be
collapsed into one signal.

LangGraph provides checkpoint-backed interrupt state. An `interrupt()`
is persisted through the checkpointer, resumed via `Command(resume=...)`,
and the node re-runs from the start on resume rather than continuing from
the same source line. Checkpoints are written at super-step boundaries, so
durable execution resumes from the last recorded state and requires
deterministic, idempotent handling around any side effects near the
interrupt boundary. Official grounding: LangGraph interrupts, durable
execution, and persistence docs.

This repository adds a second boundary on top of that guarantee: the
gateway projects pending permissions from checkpoint and execution-state
data, while the permission response API requires a separate durable
permission row and freshness classification before a thread is safely
resumable. A projected pending permission can therefore become visible
before the thread is durably resumable. That is a repo boundary race
between projection and durability, not a LangGraph contract violation.
`pending_permissions` is therefore a projected pending permission signal,
not proof of resume eligibility on its own.

Evidence anchors:

- `src/vaultspec_a2a/service_tests/test_permissions_resume.py`
- `src/vaultspec_a2a/service_tests/test_stream_followup.py`
- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/control/thread_state_service.py`

### Audit 4 thread-list stale plan-approval pointer note

Audit `4` also exposed a final mirrored-state leak on the `/api/threads`
summary surface. Thread summaries could still trust stale pending
plan-approval metadata copied from the thread row even when the live durable
plan-approval row was missing, superseded, or no longer projected as active.
That left list summaries advertising `approval_status="pending"` and an old
`approval_request_id` even though the live approval truth had already changed.

The required rule is the same one already established elsewhere in Audit `4`:
live durable plan-approval state outranks mirrored thread-row state, and the
summary surface must clear stale approval metadata when no active projected
plan approval backs it.

Grounding:

- LangGraph checkpoint and persistence truth outrank mirrored repo state, so
  list summaries must not claim pending approval state that the live durable
  plan-approval boundary no longer supports:
  [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
  and
  [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts#interrupts).

VidaiMock note:

- Deterministic request-shape matching remains a versioned contract. Audit `4`
  does not widen that provider contract; it only tightens approval-summary
  projection so replay-visible API state stays aligned with durable truth.

Evidence anchors:

- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Recommended terminology for the follow-on audits:

- `checkpoint-backed interrupt state`
- `projected pending permission`
- `durably resumable`
- `resume eligibility`

Documentation and test cautions:

- Do not claim LangGraph resumes from the same source line. It re-runs the
  node from the start after resumption.
- Do not treat `pending_permissions` alone as proof that the public API can
  safely accept a resume.
- Keep LangGraph guarantees separate from repo-specific projection and
  durability alignment.

### Audit 2c and Audit 2d closure notes

Audit `2c` is now closed by a fast LangGraph-native worker test in
`src/vaultspec_a2a/graph/tests/nodes/test_worker_integration.py`. The new
coverage proves the resumed second `ainvoke()` path after a valid approval,
including LangGraph's rerun-from-node-start behavior and the worker-owned
follow-up provider turn that consumes the approval tool result. That removes
an important blind spot where deterministic resumed work was previously proven
only through the compose-backed service lane.

Audit `2d` is now clarified and closed in two separate branches of the same
permission boundary. The repository already had fail-closed coverage for
malformed durable `allowed_options_json`. The remaining uncovered branch was
idempotent replay when a stored rejected control action has malformed
`payload_json`. That replay path is now covered in
`src/vaultspec_a2a/api/tests/test_endpoints.py`, proving the API falls back to
current durable permission state and still returns the same explicit conflict
instead of drifting into ambiguous or permissive behavior.

Mission alignment:

- exact operator inputs remain repo-owned and deterministic
- approval, rejection, and replay stay stable under VidaiMock-backed execution
- corrupt durable replay metadata fails closed instead of weakening control
- resumed work is now certified both at the service lane and at a fast
  LangGraph-native worker boundary

### Audit 3 active-interrupt binding notes

Audit `3` closes a LangGraph-specific boundary that the repository, not the
library, has to own. LangGraph gives thread-scoped checkpoint-backed resume via
`Command(resume=...)`, but it does not define the repository's outward-facing
permission request identity or guarantee that multiple visible pending requests
for one thread are independently resumable. That means the gateway/control
layer must bind public request ids to the one currently active interrupt for
that thread.

The implemented rule is now explicit:

- there is one active pending permission request per thread
- durable permission rows supersede older pending requests when a newer
  permission interrupt arrives
- the aggregator replaces stale in-memory pending requests for the same thread
- the permission-response API rejects stale request ids even if an older row is
  still present, and only dispatches resume for the active request

This audit also surfaced a mirrored-logic risk. Active pending permission
identity had effectively been implemented in parallel across durable rows,
aggregator memory, and reconnect snapshot assembly. Treating that mirroring as
its own audit concern was necessary because drift between those surfaces can
create false resumability even when the underlying LangGraph interrupt state is
correct.

### Audit 4 replay and bookkeeping note

LangGraph replay semantics keep Audit `4` focused on checkpoint truth rather
than gateway memory. Resume re-enters the node from the checkpoint boundary,
so the durable repair row has to distinguish requested and applied actions
correctly. The repository now does that on the successful permission-response
path: `permission_response_submitted` is recorded as both requested and
applied after the resume dispatch succeeds, and the repair transition helper
now stamps the applied action in the durable thread row. That keeps restart
and reconciliation logic aligned with replay truth instead of mirrored guess
state.

Evidence anchors:

- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/control/event_handlers.py`
- `src/vaultspec_a2a/streaming/emitters.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/streaming/tests/test_aggregator.py`

Verification note:

- fast API and aggregator coverage for Audit `3` is green
- compose-backed service verification is green again in this session, including
  `src/vaultspec_a2a/service_tests/test_permissions_resume.py`

### Audit 4 execution-state staleness note

Audit `4` also exposed a restart-specific projection hazard below the
permission layer. The repository keeps the last good execution-state
projection when a later worker heartbeat is degraded and carries no new
checkpoint payload. That preservation is correct, but the row must not also
adopt the thread's newer `recovery_epoch`, because doing so makes an old
checkpoint snapshot look fresh after restart. The repository now keeps the
older `recovery_epoch` on degraded-only updates, which means stale execution
state is still surfaced explicitly through
`execution_state_projection_stale` when the thread has advanced to a newer
recovery epoch without a matching fresh projection.

Evidence anchors:

- `src/vaultspec_a2a/database/thread_repository.py`
- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/api/tests/test_projection.py`

### Audit 4 startup reconciliation precedence note

Audit `4` now also treats startup reconciliation ordering as checkpoint-first
rather than permission-first. A durable pending permission row is not enough
to prove a thread is resumable if the checkpoint probe comes back missing.
The repository now only classifies the thread as `paused_resumable` when both
the durable permission row and the checkpoint truth agree; otherwise the
startup reconciler marks the thread `repair_needed` with
`checkpoint_unavailable`.

Evidence anchors:

- `src/vaultspec_a2a/lifecycle/reconciliation.py`
- `src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py`
- `src/vaultspec_a2a/database/tests/test_reconciliation.py`

### Audit 4 message-followup bookkeeping note

Audit `4` also uncovered a mirrored follow-up bookkeeping drift. The
successful follow-up dispatch path now records `message_followup_requested`
as the requested action and `message_followup_applied` as the applied action,
and the pure repair-policy lookup now keys the applied phase off the applied
enum instead of reusing the requested one. That keeps the durable repair row
and the policy map aligned with the actual post-dispatch transition instead of
a mirrored placeholder.

Evidence anchors:

- `src/vaultspec_a2a/control/repair_transitions.py`
- `src/vaultspec_a2a/thread/repair_policy.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/thread/tests/test_repair_policy.py`

### Audit 4 dispatch-failure repair/readiness degradation note

Audit `4` also exposed a failure-path durability gap below the message and
permission services. Several dispatch-failure branches were already setting the
thread row to `FAILED`, but the repair and readiness columns could remain stale
and still look healthy after the worker became unreachable. The shared
`mark_dispatch_failed()` transition now degrades those rows to
`operator_intervention_required` across the dispatch failure surfaces so the
durable thread row reflects the true operator state after an unreachable-worker
failure.

Evidence anchors:

- `src/vaultspec_a2a/control/repair_transitions.py`
- `src/vaultspec_a2a/control/message_service.py`
- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/control/diagnostics.py`
- `src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py`

### Audit 4 unreadable execution-state corruption note

Audit `4` also exposed a state-corruption gap in the reconnect snapshot path.
LangGraph's checkpoint is still the authoritative replay source, so a loaded
checkpoint may legitimately keep the replay status `durable`, but an unreadable
durable `thread_execution_state` row is still corruption at the repo boundary
and must not leave the public snapshot looking healthy. The repository now
fails that path closed by degrading both `repair_status` and
`execution_readiness` to `operator_intervention_required` whenever execution
state projection cannot be read, while preserving the checkpoint-backed replay
signal from the real checkpointer.

Evidence anchors:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/api/tests/test_projection.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`

Verification note:

- `uv run pytest src/vaultspec_a2a/api/tests/test_projection.py -q`
- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q`

### Audit 4 missing-thread checkpoint-unverified precedence note

Audit `4` also exposed a websocket diagnostics precedence gap. LangGraph's
checkpoint remains the authoritative persistence surface, so if checkpoint
truth cannot be verified the gateway must not overstate confidence just
because an orphaned durable execution-state row still exists. The repository
now classifies that condition as `THREAD_STATE_UNVERIFIED` instead of
`THREAD_STATE_DRIFT`, which keeps the operator signal aligned with missing
checkpoint truth rather than stale residue.

Evidence anchors:

- `src/vaultspec_a2a/control/diagnostics.py`
- `src/vaultspec_a2a/api/tests/test_app.py`

Verification note:

- `uv run pytest src/vaultspec_a2a/api/tests/test_app.py -q -k classify_missing_ws_thread`

### Audit 4 unreadable durable permission corruption note

Audit `4` also exposed another reconnect/state-corruption gap: a malformed
durable permission row could abort snapshot assembly because
`_permission_data_from_model()` raw-loaded `allowed_options_json` without a
fail-closed boundary. The repository now catches decode/value errors in
`enrich_snapshot_from_durable_state()`, records
`permission_projection_unreadable`, marks the snapshot incomplete, and
degrades readiness to `operator_intervention_required` while skipping the
unreadable permission row.

Checkpoint authority remains intact, so when checkpoint truth is present the
snapshot can still report `replay_status="durable"` while surfacing the
permission-row corruption at the repo boundary.

Evidence anchors:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification note:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "TestThreadState or rejects_permission_request_with_malformed_durable_option_json or rejects_permission_request_without_valid_durable_options"`

### Audit 4 unreadable plan-approval metadata leak note

Audit `4` also exposed a mirrored-state follow-on inside the same durable
permission projection path. An unreadable plan-approval permission row could be
omitted from `pending_permissions` and still seed `approval_status="pending"`
and `approval_request_id` from raw durable state, including stale values
already present on the thread row itself. The repository now derives approval
metadata only from readable projected permissions and explicitly clears stale
thread-row approval metadata when the unreadable row is a plan-approval pause,
so corrupt plan-approval rows no longer leak inconsistent approval state into
reconnect snapshots.

Evidence anchors:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`

Verification note:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "unreadable_plan_approval_row"`

### Audit 4 websocket missing-thread checkpoint precedence note

Audit `4` also exposed a protocol-translation gap on the websocket follow-up
path. LangGraph checkpoint truth remains the authoritative persistence surface,
so when checkpoint verification cannot confirm whether backend state exists the
gateway must surface uncertainty there too, not flatten the error into a plain
`THREAD_NOT_FOUND`. The websocket send-message handler now reuses the same
checkpoint-aware missing-thread classifier as the REST diagnostics path, so
missing-thread follow-up rejections preserve `THREAD_STATE_UNVERIFIED` when
checkpoint truth cannot be verified.

Evidence anchors:

- `src/vaultspec_a2a/api/ws_dispatch.py`
- `src/vaultspec_a2a/api/app.py`
- `src/vaultspec_a2a/api/tests/test_app.py`

Verification note:

- `uv run pytest src/vaultspec_a2a/api/tests/test_app.py -q -k "dispatch_message_handler"`

### Audit 4 thread-list approval summary consistency note

Audit `4` also exposed a summary-surface lag behind the reconnect snapshot
path. The `/api/threads` listing still echoed `approval_status` and
`approval_request_id` directly from the thread row, so a corrupt unreadable
plan-approval permission could be cleared in reconnect snapshots and still
appear as a pending approval in thread summaries. The repository now clears
those summary fields when the backing plan-approval permission row is
unreadable, keeping the list surface aligned with the stricter snapshot
contract.

Evidence anchors:

- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification note:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "TestListThreads"`

### Audit 4 unreadable durable permission projection note

Audit `4` also exposed a corruption gap in the durable permission projection
path for reconnect snapshots. LangGraph checkpoint state remains authoritative
for replay and interrupt resume, but unreadable auxiliary durable permission
rows are still repo-boundary corruption and must not crash the public thread
state surface. The repository now treats malformed `allowed_options_json` as
degraded durable state: snapshot assembly remains alive, the unreadable
permission is omitted, and readiness is failed closed to
`operator_intervention_required`.

Evidence anchors:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Grounding:

- LangGraph interrupts and durable execution remain checkpoint-backed, so
  corrupted repo-owned auxiliary rows must degrade operator confidence rather
  than override checkpoint truth:
  [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts#interrupts)
  and
  [Durable execution](https://docs.langchain.com/oss/python/langgraph/durable-execution#durable-execution).

Verification note:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "TestThreadState or rejects_permission_request_with_malformed_durable_option_json or rejects_permission_request_without_valid_durable_options"`

### Audit 4 stale plan-approval pointer note

Audit `4` also exposed another mirrored-state drift in the plan-approval path.
The permission-response guard could still trust `thread.approval_request_id`
even when the live pending plan-approval row had moved on, and reconnect
snapshots could preserve `approval_status="pending"` on the thread row even
when no readable projected plan approval remained. The repository now prefers
live pending plan-approval rows over the stale thread pointer when validating
responses, and clears stale pending approval metadata when no projected
plan-approval permission actually backs it.

Evidence anchors:

- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`

Grounding:

- LangGraph resume and interrupt semantics are checkpoint-backed, so repo-owned
  mirrored approval metadata must not outrank live durable permission truth or
  the absence of projected approval state:
  [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts#interrupts)
  and
  [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence).

Verification note:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "TestPermissionRespond"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "missing_plan_approval_request_clears_stale_thread_pending_approval"`

### Audit 4 thread summary approval consistency note

Audit `4` also reached the `/api/threads` summary surface. After the stricter
reconnect snapshot path stopped exposing corrupt plan-approval metadata, the
summary route could still echo stale `approval_status="pending"` and
`approval_request_id` from the thread row even when the backing
plan-approval permission row was unreadable. The repository now applies the
same fail-closed rule to thread summaries, clearing unreadable plan-approval
metadata instead of letting the list view overstate confidence.

Evidence anchors:

- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Grounding:

- LangGraph persistence checkpoints state at every step, so repo-owned summary
  projections must not claim a pending approval surface that the stricter
  checkpoint-aligned reconnect snapshot has already rejected:
  [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
  and
  [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts#interrupts).

Verification note:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "TestListThreads"`

### Output containment note

The deterministic gate also depends on bounded filesystem behavior. Test
fixtures and offline provider regressions should not spill SQLite files,
checkpoint files, or synthetic credential artifacts into developer-home
scratch roots or ad hoc repo-root directories. Those writes need to stay
either inside pytest-managed scratch roots or inside explicit repo-owned
runtime directories such as `.vault/runtime/` when persistence is part of the
thing being certified.

This is adjacent to the main LangGraph/VidaiMock work rather than a separate
concern. LangGraph durability relies on real checkpoint files, and VidaiMock
offline/provider tests rely on real credential and request fixtures, so the
filesystem boundary is part of the certification contract. If those artifacts
escape the test-owned boundary, the suite can become stateful and misleading
even when the orchestration logic itself is correct.

### Audit 5 supervisor plan-approval durability note

Audit `5` begins with a repo-boundary relay defect rather than a LangGraph
contract defect. LangGraph's human-in-the-loop model is clear in the primary
docs: `interrupt()` pauses execution, persistence checkpoints that pause under
the same `thread_id`, and `Command(resume=...)` resumes from the start of the
interrupted node rather than from the exact source line. That means a
supervisor-owned approval pause must remain durably discoverable and
respondable at the repository boundary, not just visible in transient stream
events.

This repo already translated supervisor interrupts into outward-facing
`plan_approval_request` events at the streaming layer, but the durable relay
classifier still only treated `permission_request` as a row-creating request.
That created a split-brain failure mode:

- the approval pause was visible in streamed/projection surfaces
- the same request could fail to exist as a durable pending permission row
- `/api/permissions/{id}/respond` could then reject the request even though the
  supervisor had already paused for approval

The minimal fix is to treat `plan_approval_request` as a first-class durable
permission-request event in the same relay path as `permission_request`.
Initial verification is now in place at two levels:

- fast event-handler coverage that proves a supervisor approval relay creates a
  durable pending permission and pending thread approval state
- HTTP coverage that proves `/internal/events` can relay a real
  `plan_approval_request` and the resulting request is then accepted by
  `/api/permissions/{id}/respond`

Remaining risk for this audit slice:

- plan-approval payload construction is still mirrored across supervisor,
  streaming transform, projection, and permission-response logic
- the compose-backed service lane still needs a dedicated supervisor approval
  certification scenario, preferably proving reconnect-safe resume and
  exactly-once post-approval work

Grounding:

- [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

Context7 note:

- attempted again for `langgraph`, but the MCP in this environment still fails
  with an invalid API key, so primary-source docs remain the grounding source

Audit `5` also exposed a supervisor-specific certification gap in the real
stack, and that gap is now closed. LangGraph resume semantics were not the
fault line: `interrupt()` remains checkpoint-backed, resume must reuse the
same `thread_id`, and the interrupted node restarts from its checkpoint
boundary. The actual failures were in repo-owned supervisor routing and
mock-stream decoding. First, supervisor model resolution initially omitted the
supervisor `agent_config`, so the mock provider could not select the
`vaultspec-supervisor` tape. Second, supervisor-route VidaiMock stream chunks
arrived as string-wrapped JSON, and `MockChatModel` dropped those chunks
instead of decoding them. Third, the supervisor tape needed an explicit
terminal `FINISH` branch after the approved worker completion message; without
that, the stack looped back into a fresh worker permission pause instead of
terminating.

Those repo-boundary fixes are now in place across the compiler, mock provider,
service harness, service resume test, and supervisor mock preset artifacts.
The compose-backed certifier now proves the full chain:

- supervisor plan approval pause appears and is durably respondable
- worker permission pause appears after the plan is approved
- the approved worker branch produces meaningful completion text
- the supervisor emits `FINISH` instead of re-routing back into another pause

Evidence anchors:

- `src/vaultspec_a2a/graph/compiler.py`
- `src/vaultspec_a2a/graph/tests/test_compiler.py`
- `src/vaultspec_a2a/providers/mock_chat_model.py`
- `src/vaultspec_a2a/providers/tests/test_mock_chat_model.py`
- `src/vaultspec_a2a/service_tests/harness.py`
- `src/vaultspec_a2a/service_tests/test_permissions_resume.py`
- `src/vaultspec_a2a/team/presets/mock/tapes/providers/vaultspec-supervisor.yaml`
- `src/vaultspec_a2a/team/presets/mock/tapes/templates/vaultspec-supervisor-chat.json.j2`
- `src/vaultspec_a2a/team/presets/teams/mock-supervisor-human-in-loop.toml`

### Audit 6 stale execution-state lineage note

Audit `6` now extends the earlier checkpoint-truth and corruption work to the
stale-lineage case. A durable `thread_execution_state` row can still
deserialize cleanly while pointing at lineage that no longer matches the live
checkpoint or reconnect path after replay, restart, or interrupted recovery.
That condition must not leave reconnect snapshots or
`/api/threads/{id}/state` looking healthy or durably resumable just because
the row is readable. LangGraph's persistence model keeps checkpoint truth
thread-scoped and authoritative, so repo-owned execution-state projections
must fail closed when the durable row no longer matches the active
`recovery_epoch` or checkpoint id.

The repository now does that. Stale durable execution-state lineage degrades
operator-facing readiness to `needs_reconciliation`, keeps
`snapshot_complete=false`, and surfaces
`execution_state_projection_stale` instead of preserving a healthy reconnect
surface. The new regressions prove both the pure state-service path and the
public `/api/threads/{id}/state` endpoint under a readable-but-stale
execution-state row.

Evidence anchors:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k stale_execution_state`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k stale_execution_state_lineage`
- `uv run pytest src/vaultspec_a2a/api/tests/test_projection.py -q`

Audit `6` also exposed a summary-surface mirror of the same stale-lineage
problem. After the reconnect snapshot and `/api/threads/{id}/state` path began
failing closed on stale durable execution-state lineage, `/api/threads` and
the MCP-backed list-thread surface could still echo `repair_status` and
`execution_readiness` straight from the thread row. That split the operator
story across two public surfaces: reconnect state said stale lineage required
reconciliation, while thread summaries could still advertise a healthy thread.

The repository now aligns those surfaces. `list_threads_service()` compares
the thread row `recovery_epoch` against the latest durable execution-state row
and degrades summary readiness to `needs_reconciliation` when lineage is
stale. The new endpoint and MCP regressions prove the list surface no longer
overstates health under stale execution-state lineage.

Evidence anchors:

- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k list_threads_degrades_stale_execution_state_lineage`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k list_threads_degrades_stale_execution_state_summary`

Review follow-up also exposed a correctness gap in approval-state
reconstruction. Durable supervisor plan approvals are allowed to persist with
`tool_call = NULL`, and the supervisor interrupt path emits exactly that
shape. The gateway now normalizes those durable rows back to
`plan_approval` during projection, but that alone was not enough: checkpoint
state enrichment was still replacing `snapshot.pending_permissions` with
checkpoint/aggregator-derived data instead of merging by durable `request_id`.
That made a pending approval vulnerable to disappearing from thread state even
though the durable row and thread approval metadata still said it was pending.

The repository now preserves durable pending permissions during checkpoint
enrichment and keeps nullable plan-approval rows actionable in both pure
thread-state assembly and the public `/api/threads/{id}/state` endpoint. This
is a gateway reconstruction issue, not a LangGraph runtime bug: the checkpoint
exists only as one input to reconnect state, while durable approval truth must
retain precedence until an explicit durable resolution event supersedes it.

Evidence anchors:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/snapshot.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k plan_approval_without_tool_call`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k preserves_plan_approval_without_tool_call`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/control/snapshot.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

This follow-up is now promoted to explicit `Audit 6.1` in the roadmap because
the defect boundary is broader than a single nullable-field bug. The durable
plan-approval row was being projected correctly, but reconnect assembly later
let checkpoint or aggregator-derived state overwrite
`snapshot.pending_permissions` instead of merging by durable identity. That
makes this a deeper durable-versus-checkpoint precedence audit inside the
broader persistence and state-corruption domain, not just a one-off projection
cleanup.

Audit `6` also reached the operator dashboard surface. Team status already
loaded durable pending permissions from the database, but it still derived
`active_threads` only from heartbeat threads and in-memory aggregator state.
After a restart-like loss of worker memory, that could produce a contradictory
operator view: a pending durable approval would still be listed, but the
owning thread would disappear from the active-thread list. The repository now
unions durable pending-permission thread ids into team status `active_threads`,
and the MCP-backed regression proves a durably paused thread remains visible
even when heartbeat and aggregator state are empty.

Evidence anchors:

- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k durable_pending_permission_thread_as_active`
- `uv run ruff check src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-032: failed resume-dispatch rollback drift

This slice confirms the durable-vs-retry boundary for permission resumes. When
worker dispatch is unreachable, the repository now resets the durable
permission row to `pending`, retires the original control-action idempotency
key to a tombstone value, and downgrades the thread to `input_required` so the
permission remains re-actionable on retry. The drift before this fix was
stricter than the durable row alone suggested: the permission could look
pending again while the thread itself remained terminal `failed`, which blocked
retry at the public boundary.

Evidence anchors:

- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/database/permission_repository.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/control/repair_transitions.py`
- `src/vaultspec_a2a/thread/enums.py`

Terminology:

- `pending` for the restored durable permission row
- `input_required` for the retryable thread state
- `paused_resumable` for the healthy pause/readiness projection
- `answered_pending_apply` only as the transient durable submit state before
  dispatch succeeds

LangGraph grounding:

- `interrupts` documentation states that resume restarts from the node
  boundary.
- `durable-execution` documentation states that side effects before interrupt
  must be idempotent.
- That makes rollback at the durable write boundary the correct fix shape,
  instead of patching downstream projection surfaces after a failed dispatch.

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "failed_resume_dispatch_restores_permission_to_pending or rejects_permission_request_when_thread_terminal or stale_permission_request_when_newer_interrupt_exists"`
- `uv run pytest src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py -q`
- `uv run pytest src/vaultspec_a2a/service_tests/test_permissions_resume.py -q -m service`
- `uv run ruff check src/vaultspec_a2a/database/permission_repository.py src/vaultspec_a2a/database/__init__.py src/vaultspec_a2a/control/permission_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-033: stale execution-state public-surface drift

This slice aligns public summary and state surfaces with checkpoint truth.
`/api/threads/{id}/state` now fails closed before stale execution-state fields
are merged. When the durable execution-state row is stale by `recovery_epoch`
or `checkpoint_id`, the snapshot is marked
`execution_state_projection_stale`, `snapshot_complete=false`, readiness
degrades to `needs_reconciliation`, and stale runtime fields are not copied
into the public surface. `/api/threads` summaries now also consult checkpoint
truth, not just `recovery_epoch`, and the route passes the app checkpointer
into `list_threads_service` so summary freshness can compare durable
execution-state lineage against live checkpoint truth.

Evidence:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/api/routes/threads.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Terminology:

- `needs_reconciliation` for stale execution-state summaries and snapshots
- `execution_state_projection_stale` for the stale-lineage marker
- `snapshot_complete=false` whenever stale lineage is detected

Contradictions resolved:

- summaries could look healthier than reconnect/state
- `/state` could leak obsolete runtime truth while already marked stale

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k stale_execution_state_degrades_snapshot_readiness`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_degrades_stale_execution_state_lineage or list_threads_degrades_stale_execution_state_lineage or list_threads_degrades_checkpoint_mismatched_execution_state"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "list_threads_degrades_stale_execution_state_summary or list_threads_degrades_checkpoint_mismatched_summary"`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/control/thread_service.py src/vaultspec_a2a/api/routes/threads.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-034: team-status ghost pending-permission drift

This slice makes `/api/team/status` durable-first for pending permissions.
`build_team_status()` now sources pending permissions only from the DB-backed
`get_pending_permission_requests()` result and no longer appends
aggregator-only permission entries. Aggregator state still contributes
`agents` and `active_threads`, but not permission truth, so ghost permissions
are no longer exposed as public pending work.

Evidence:

- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/api/routes/teams.py`
- `src/vaultspec_a2a/api/schemas/rest.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Terminology:

- `durable-backed` / `durable-first` for public pending permissions
- `ghost permissions` for aggregator-only permission entries with no DB row
- keep aggregator state limited to agent/activity surfaces

Contradiction resolved:

- the old contract could advertise an actionable pending permission without any
  durable backing row

LangGraph grounding:

- the persistence and durable-execution docs reinforce that thread state must
  come from checkpoint-backed persistence, not ephemeral in-memory leftovers

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "TestTeamStatus"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "team_status_lists_durable_pending_permission_thread_as_active or team_status_excludes_aggregator_only_pending_permission or get_pending_permissions_empty"`
- `uv run ruff check src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-035: websocket failure terminal-cleanup drift

This slice aligns WebSocket failure handling with the canonical terminal
cleanup path. `api/ws_dispatch.py` now routes WS dispatch failure through
`mark_thread_failed(...)` with the live aggregator, and
`control/diagnostics.py` now calls the canonical terminal-event handler first
before applying repair/readiness degradation. The terminal path expires
durable pending permissions in the repository and prunes aggregator
pending-permission state, so WS failure no longer leaves stale pending
approvals behind after the thread is terminal.

Evidence:

- `src/vaultspec_a2a/api/ws_dispatch.py`
- `src/vaultspec_a2a/control/diagnostics.py`
- `src/vaultspec_a2a/control/event_handlers.py`
- `src/vaultspec_a2a/database/permission_repository.py`
- `src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py`

## REVIEW-036: failed cancel dispatch durable-state rollback

This slice closes a cancel-path persistence split exposed by the ongoing Audit
`6` repo scan. LangGraph's durable-execution guidance is strict about
pre-interrupt or pre-resume side effects: if a side effect happens before the
external action is actually accepted, the durable state must remain idempotent
and consistent with the caller-visible outcome. Here, `cancel_thread()` was
writing `cancel_pending` via `mark_cancel_requested()` before worker dispatch,
then returning a 502 / `accepted=False` branch without rolling that durable
repair mutation back. The fix in `src/vaultspec_a2a/control/cancel_service.py`
captures the prior repair state and restores it on dispatch failure, so failed
cancel requests no longer leave a ghost in-flight cancel in persistence.

Evidence:

- `src/vaultspec_a2a/control/cancel_service.py`
- `src/vaultspec_a2a/control/repair_transitions.py`
- `src/vaultspec_a2a/api/routes/cancel.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "failed_cancel_dispatch_restores_repair_state"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "cancel_thread_cancels_running_thread or cancel_thread_repeat_request_stays_accepting_until_terminal_event"`
- `uv run ruff check src/vaultspec_a2a/control/cancel_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-037: checkpoint truth over surviving cancelling status

This slice aligns startup reconciliation with LangGraph persistence semantics:
replay and recovery truth come from checkpoint availability, not from a
parallel custom status field that survived a restart. The executor in
`src/vaultspec_a2a/database/reconciliation.py` already probes checkpoint
availability before building reconciliation actions; the defect was that the
pure decision logic in `src/vaultspec_a2a/lifecycle/reconciliation.py` still
trusted `status="cancelling"` ahead of that probe result. The fix now makes
reconciliation fail closed. If the checkpoint cannot be read, the thread is
persisted as `status="repair_needed"` with `repair_status="checkpoint_unavailable"`
and `execution_readiness="checkpoint_unavailable"` instead of `cancel_pending`.

Evidence:

- `src/vaultspec_a2a/lifecycle/reconciliation.py`
- `src/vaultspec_a2a/database/reconciliation.py`
- `src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py`
- `src/vaultspec_a2a/database/tests/test_reconciliation.py`

Verification:

- `uv run pytest src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py -q -k "cancelling"`
- `uv run pytest src/vaultspec_a2a/database/tests/test_reconciliation.py -q -k "cancelling_without_checkpoint"`
- `uv run ruff check src/vaultspec_a2a/lifecycle/reconciliation.py src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py src/vaultspec_a2a/database/tests/test_reconciliation.py`

## REVIEW-038: durable permission truth over aggregator-only thread-state projection

This slice aligns reconnect snapshots with LangGraph persistence semantics:
durable thread state should come from checkpoint-backed and database-backed
truth, not from ephemeral in-memory permission cache entries that survived only
in the aggregator. The defect was in `src/vaultspec_a2a/control/snapshot.py`,
where `enrich_snapshot_from_state()` appended aggregator pending permissions
before durable reconciliation in
`src/vaultspec_a2a/control/thread_state_service.py` and
`src/vaultspec_a2a/control/projection.py`. The fix makes thread-state pending
permissions durable-first by removing the aggregator-only append path, while
still preserving aggregator-derived agent and tool-call liveness data.

Evidence:

- `src/vaultspec_a2a/control/snapshot.py`
- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "aggregator_only_pending_permission_does_not_surface_in_thread_state or plan_approval_without_tool_call_preserves_pending_approval"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_excludes_aggregator_only_pending_permission or state_preserves_plan_approval_without_tool_call"`
- `uv run ruff check src/vaultspec_a2a/control/snapshot.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-039: checkpoint usability must back `/api/health` readiness

This slice aligns the health surface with LangGraph persistence semantics.
Durable execution requires a working checkpointer backend that can save and
load checkpoint state; a non-null handle alone is not enough to certify
resume capability. The defect was in `src/vaultspec_a2a/control/health.py`,
where `/api/health` previously marked the checkpoint subsystem `ok` based only
on object presence. The fix now performs a lightweight `aget_tuple(...)`
probe and degrades the checkpoint check to `error` when the backend is closed,
timed out, or otherwise unusable.

Evidence:

- `src/vaultspec_a2a/control/health.py`
- `src/vaultspec_a2a/api/routes/health.py`
- `src/vaultspec_a2a/api/tests/test_app.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_app.py -q -k "api_health_degrades_when_checkpointer_backend_is_unusable or api_health_reports_sqlite_fallback_diagnostics"`
- `uv run ruff check src/vaultspec_a2a/control/health.py src/vaultspec_a2a/api/tests/test_app.py`

## REVIEW-040: checkpoint probing must back `/api/threads` summary readiness

This slice aligns the list-threads summary surface with LangGraph persistence
semantics. A summary that cannot verify checkpoint truth must not continue to
advertise healthy execution readiness. The defect was in
`src/vaultspec_a2a/control/thread_service.py`, where checkpoint probe
timeouts/exceptions were previously suppressed, allowing `/api/threads`
summaries to remain healthy when checkpoint usability was unverified. The fix
now degrades `repair_status` and `execution_readiness` to
`checkpoint_unavailable` when checkpoint probing cannot be trusted.

Evidence:

- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "list_threads_degrades_when_checkpoint_probe_is_unverified"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "list_threads_degrades_when_checkpoint_probe_is_unverified"`
- `uv run ruff check src/vaultspec_a2a/control/thread_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-041: checkpoint interrupts must not overstate public permission actionability

This slice aligns the reconnect snapshot surface with the repo's actual
approval contract. LangGraph interrupt and persistence docs confirm that a
checkpointed interrupt is real durable graph state: `interrupt()` saves the
graph state through the checkpointer, and resumption later reuses the same
`thread_id` and checkpoint lineage. But those docs do not claim that every
checkpoint interrupt is automatically actionable through an application's own
approval API. In this repo, `src/vaultspec_a2a/control/permission_service.py`
intentionally requires a durable pending permission row before
`/api/permissions/{id}/respond` will accept a resume request. That means the
public thread-state surface must not advertise a checkpoint-only permission as
actionable when no durable row exists.

The defect was in the merge boundary between durable state and checkpoint
projection. `src/vaultspec_a2a/control/thread_state_service.py` merged durable
pending permissions first, but `src/vaultspec_a2a/control/projection.py` later
appended checkpoint interrupt permissions without reconciling them against the
durable request ids. The fix keeps checkpoint pause truth visible while
failing closed on actionability: checkpoint-only permissions are removed from
`pending_permissions`, stale mirrored approval pointers are cleared when they
depended on the dropped permission, and the snapshot is degraded with
`checkpoint_permission_without_durable_row`.

Evidence:

- `https://docs.langchain.com/oss/python/langgraph/interrupts`
- `https://docs.langchain.com/oss/python/langgraph/persistence`
- `https://docs.langchain.com/oss/python/langgraph/durable-execution`
- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "checkpoint_only_pending_permission_does_not_surface_in_thread_state or aggregator_only_pending_permission_does_not_surface_in_thread_state or plan_approval_without_tool_call_preserves_pending_approval"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_excludes_checkpoint_only_pending_permission or state_excludes_aggregator_only_pending_permission or state_preserves_plan_approval_without_tool_call"`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/control/thread_state_service.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-042: operator discovery must not surface malformed durable permissions as actionable

This slice aligns team-status and MCP permission discovery with the repo's
actual permission-response contract. The relevant LangGraph grounding does not
change here: checkpoint truth and interrupt durability still come from the
checkpointer, but application-level actionability is a repo-owned boundary.
In this repo, `src/vaultspec_a2a/control/permission_service.py` rejects a
pending request when its durable row has no valid option ids. That means
operator discovery surfaces must not advertise those rows as actionable even
though they still exist durably.

The defect was in `src/vaultspec_a2a/control/team_service.py`, which treated
all durable pending permission rows as equally discoverable pending work for
`/api/team/status` and MCP `get_pending_permissions()`. The fix now validates
that a durable row still exposes at least one usable option id before it
appears in public `pending_permissions`. The owning paused thread remains in
`active_threads`, so liveness visibility is preserved while false actionability
is removed.

Evidence:

- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "TestTeamStatus"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "team_status_hides_malformed_durable_pending_permission or team_status_excludes_aggregator_only_pending_permission or team_status_lists_durable_pending_permission_thread_as_active or get_pending_permissions_empty"`
- `uv run ruff check src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-043: operator discovery must not keep terminal-thread permission residue actionable

This slice extends the same actionability boundary one step further. LangGraph
durable execution and interrupts docs ground the graph side of the contract:
checkpointed interrupts are durable workflow state bound to a thread and
resume through that same thread lineage. But application-level control APIs
still own whether a surfaced permission is actionable. In this repo, once a
thread is terminal, the control layer rejects further permission responses even
if a stale durable permission row was never expired. That means operator
discovery surfaces cannot continue to advertise those rows as pending work.

The defect was again in `src/vaultspec_a2a/control/team_service.py`. After
`REVIEW-042`, team-status discovery correctly filtered malformed or optionless
durable rows, but it still promoted any remaining durable pending row into
`pending_permissions` and `active_threads` without checking whether the owning
thread had already moved to `completed`, `failed`, or `cancelled`. The fix now
reconciles durable pending rows against terminal thread status first: terminal
threads are excluded from team-status pending discovery and do not become
active solely because of stale permission residue. Non-terminal paused threads
remain visible, including the malformed-row operator case from `REVIEW-042`.

Evidence:

- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/thread/enums.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "pending_permissions_exclude_terminal_thread_rows or pending_permissions_hide_malformed_durable_rows"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "get_pending_permissions_excludes_terminal_thread_rows or team_status_excludes_aggregator_only_pending_permission or team_status_hides_malformed_durable_pending_permission"`
- `uv run ruff check src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-044: `/api/threads` summaries must not keep stale plan approval metadata actionable

This slice extends the same fail-closed rule to list-thread summaries. The
LangGraph grounding remains consistent across the official `Interrupts`,
`Persistence`, and `Durable execution` docs: checkpointed interrupts are
thread-scoped durable workflow state, and resumability depends on persisted
checkpoint lineage rather than transient in-memory projection. That does not
mean every mirrored application summary surface is automatically actionable.
In this repo, approval submission still goes through the gateway-owned durable
permission table and the thread lifecycle guard, so `/api/threads` cannot
advertise a plan approval as pending when the durable row has no usable option
ids or the owning thread is already terminal.

The defect in `src/vaultspec_a2a/control/thread_service.py` was twofold. First,
summary reconstruction treated any parseable `allowed_options_json` as good
enough, which let optionless durable plan approvals keep `approval_status` and
`approval_request_id` visible. Second, mirrored thread-row approval metadata
was evaluated before terminal lifecycle was enforced, which let `completed` or
`failed` threads still appear to have actionable pending approval in
`/api/threads` and MCP list-thread output. The fix now centralizes durable
option-id extraction in `src/vaultspec_a2a/control/permission_options.py`,
reuses that validator across permission discovery surfaces, and clears summary
approval metadata for terminal threads before pending-plan reconstruction.

Evidence:

- `src/vaultspec_a2a/control/permission_options.py`
- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "list_threads_hides_optionless_plan_approval_metadata or list_threads_clears_terminal_thread_pending_approval"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "list_threads_hides_optionless_plan_approval_summary or list_threads_clears_terminal_pending_approval_summary"`
- `uv run ruff check src/vaultspec_a2a/control/permission_options.py src/vaultspec_a2a/control/permission_service.py src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/control/thread_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Terminology:

- `FAILED` for the terminal thread status
- `operator_intervention_required` for the degraded repair/readiness outcome
- canonical `terminal-event` / `terminal cleanup` path
- distinguish durable pending permissions from aggregator pending-permission
  state

Contradiction resolved:

- WS failure could previously leave stale pending approvals in persistence and
  aggregator memory after the thread was already terminal

Verification:

- `uv run pytest src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py -q`
- `uv run ruff check src/vaultspec_a2a/control/diagnostics.py src/vaultspec_a2a/api/ws_dispatch.py src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py`

## REVIEW-045: terminal-thread state surfaces must fail closed on stale pending permissions

LangGraph checkpoint and interrupt durability still support the same stricter
rule used throughout Audit `6`: resumability and actionability are defined at
the persisted thread boundary, not by stale public projections after terminal
lifecycle has already won. Once a thread is terminal, repo-owned public state
must not continue to advertise actionable pending permissions even if durable
permission residue still exists.

The repo-specific defect was in `src/vaultspec_a2a/control/projection.py`.
`enrich_snapshot_from_durable_state()` was still loading durable pending
permissions and mirrored plan-approval metadata without reconciling them
against terminal thread lifecycle. That let `/api/threads/{id}/state` expose
`pending_permissions`, `approval_status`, and `approval_request_id` for
terminal threads. Because MCP `get_thread_status` formats its pending
permission output directly from that state payload in
`src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`, the same stale
actionability leaked into the operator surface there as well.

The fix now fails closed at the durable projection boundary. When a thread is
already terminal, pending-permission residue is removed from the public
snapshot, mirrored approval metadata is cleared, and the snapshot degrades with
`terminal_thread_pending_permission_residue` so the inconsistency remains
visible without being actionable.

Evidence:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "terminal_thread_excludes_durable_pending_permission_from_thread_state or plan_approval_without_tool_call_preserves_pending_approval"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_excludes_terminal_thread_pending_permission_residue or state_preserves_plan_approval_without_tool_call"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "get_thread_state_excludes_terminal_pending_permission_residue"`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-046: public permission reads must not treat answered-not-applied rows as actionable pending state

LangGraph checkpoint and interrupt semantics still support the same boundary
rule: durable state can retain an apply-in-flight transition, but public
resumability and actionability must reflect current user-facing truth, not
intermediate internal bookkeeping. In this repo, `answered_pending_apply` is an
internal state used to complete permission application after an accepted
response; it must not be treated as a second pending request by public summary
or snapshot code.

The defect was that the repository read primitive did not distinguish internal
apply bookkeeping from public pending reads. `get_pending_permission_requests()`
was feeding `answered_pending_apply` rows into `/api/team/status`,
`/api/threads`, `/api/threads/{id}/state`, and the MCP mirrors, so multiple
surfaces could still advertise already-answered permissions as actionable
pending work. The fix now splits the read boundary so internal completion paths
keep their answered-not-applied visibility while public surfaces only expose
genuinely actionable `pending` rows.

Evidence:

- `src/vaultspec_a2a/database/permission_repository.py`
- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "answered_pending_apply_permission_does_not_surface_in_thread_state"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "list_threads_hides_answered_pending_apply_plan_approval or state_excludes_answered_pending_apply_permission or team_status_excludes_answered_pending_apply_permission"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "list_threads_hides_answered_pending_apply_summary or get_pending_permissions_excludes_answered_pending_apply"`
- `uv run ruff check src/vaultspec_a2a/database/permission_repository.py src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/control/thread_service.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-047: startup reconciliation must not treat answered-not-applied permissions as resumable pending state

LangGraph durable execution still implies the same boundary rule after restart:
reconciliation may inspect persisted state, but it must not reinterpret
internal in-flight bookkeeping as user-actionable pending work. In this repo,
`answered_pending_apply` is a valid intermediate state for internal apply
completion after a permission response has already been accepted. It is not
restart truth for resuming a user pause, because the user has already answered
and the remaining work is internal application rather than a fresh pending
approval.

The defect was in startup reconciliation. `reconcile_threads_on_startup()` in
`src/vaultspec_a2a/database/reconciliation.py` built `pending_map` from
`get_pending_permission_requests(...)`, which still included
`answered_pending_apply`. That let the restart classifier in
`src/vaultspec_a2a/lifecycle/reconciliation.py` overstate resumability by
assigning `paused_resumable` and pushing threads back to `input_required`
despite there being no user-actionable permission left to answer.

The fix now scopes startup reconciliation to true pending rows only. Internal
completion flows still retain access to answered-not-applied rows, but restart
reconciliation no longer uses them to classify a thread as user-paused or
resumable.

Evidence:

- `src/vaultspec_a2a/database/permission_repository.py`
- `src/vaultspec_a2a/database/reconciliation.py`
- `src/vaultspec_a2a/lifecycle/reconciliation.py`
- `src/vaultspec_a2a/database/tests/test_reconciliation.py`
- `src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py`

Verification:

- `uv run pytest src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py -q -k "answered_not_applied_does_not_count_as_resumable_pending or pending_permission_transitions_to_input_required"`
- `uv run pytest src/vaultspec_a2a/database/tests/test_reconciliation.py -q -k "answered_pending_apply_with_checkpoint_is_not_marked_resumable or pending_permission_without_checkpoint_is_not_marked_resumable"`
- `uv run ruff check src/vaultspec_a2a/database/reconciliation.py src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py src/vaultspec_a2a/database/tests/test_reconciliation.py`

## REVIEW-048: thread-state snapshots must clear stale pause_cause after actionability is removed

LangGraph durable execution still supports the same boundary rule: persisted
state can be inspected and resumed, but public/operator state must reflect
current actionable truth, not stale pause metadata left behind after permission
actionability has been cleared. In this repo, `pause_cause` is derived from
permission and checkpoint projection, so it must not survive when the snapshot
no longer has any user-actionable pending permissions or mirrored approval
fields.

The defect was in projection cleanup. `enrich_snapshot_from_durable_state()` in
`src/vaultspec_a2a/control/projection.py` already cleared the actionable
permission fields in answered-not-applied, checkpoint-only, and similar
fail-closed cases, but it did not also clear `pause_cause`. That left
`/api/threads/{id}/state` suggesting the workflow was still paused even though
the reconnect snapshot no longer contained any actionable permission state.

The fix now clears `pause_cause` whenever the snapshot no longer has remaining
actionable permission state. That keeps the reconnect view aligned with
deterministic public truth rather than stale projection residue.

Evidence:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "answered_pending_apply_permission_does_not_surface_in_thread_state or checkpoint_only_pending_permission_does_not_surface_in_thread_state"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_excludes_answered_pending_apply_permission or state_excludes_checkpoint_only_pending_permission"`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-049: thread-state must fail closed when checkpoint truth is missing or unavailable

LangGraph interrupt semantics still keep the same hard boundary: a human pause
is resumable only through persisted checkpoint state for the same `thread_id`.
The checkpointer is the authority that keeps the exact graph state needed to
resume; durable permission rows are recovery evidence, not sufficient proof
that the graph can still accept a user response.

The defect was in reconnect snapshot assembly. `build_thread_state()` in
`src/vaultspec_a2a/control/thread_state_service.py` loaded durable pending
permissions first, then degraded checkpoint-missing and
checkpoint-unavailable cases without clearing that user-actionable state. That
let `/api/threads/{id}/state` overstate actionability by returning
`pending_permissions`, `approval_status="pending"`, `approval_request_id`, and
`pause_cause` even while the snapshot declared checkpoint truth unavailable.

The fix now fails closed on that boundary. When checkpoint truth is missing or
unavailable, reconnect snapshots clear public permission/approval state and
record `pending_permission_without_checkpoint_truth` as an additional degraded
reason. This keeps public resumability aligned with LangGraph’s
checkpoint-backed interrupt model instead of durable residue.

Evidence:

- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "missing_checkpoint_hides_durable_pending_permission_state"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_hides_pending_approval_when_checkpoint_is_unavailable"`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/control/thread_state_service.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-050: hard delete must not treat paused/resumable threads as disposable

LangGraph interrupt semantics still impose the same pessimistic boundary:
`input_required` is not disposable transient noise when it is backed by a
checkpoint and pending permission state. In this repo, paused permission
threads are explicitly treated as durable operator handoff state in restart
reconciliation and the service permission tests, so hard delete must not erase
that state before the operator resolves it.

The defect was in lifecycle delete eligibility. `can_delete()` in
`src/vaultspec_a2a/thread/lifecycle_guards.py` only blocked `running`, which
left the REST delete path free to destroy an `input_required` thread even
though the same repo semantics treated it as resumable, operator-actionable
work. That was destructive eligibility drift: the system could erase a valid
checkpoint-backed pause instead of forcing explicit cancel/archive or repair.

The fix now narrows delete eligibility to terminal or archived states only.
Paused, reconciling, submitted, or otherwise non-terminal work is no longer
hard-deletable through the public API.

Evidence:

- `src/vaultspec_a2a/thread/lifecycle_guards.py`
- `src/vaultspec_a2a/api/routes/threads.py`
- `src/vaultspec_a2a/thread/tests/test_lifecycle_guards.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/thread/tests/test_lifecycle_guards.py -q`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "rejects_input_required_thread_with_pending_permission"`
- `uv run ruff check src/vaultspec_a2a/thread/lifecycle_guards.py src/vaultspec_a2a/thread/tests/test_lifecycle_guards.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-051: follow-up messaging must fail closed for repair-state threads

LangGraph durability and restart semantics still support the same pessimistic
boundary: a thread in `repair_needed` or `reconciling` is not safe for normal
user follow-up input. Those states exist because checkpoint truth is
unavailable or reconciliation is still in progress, so accepting a new
follow-up would bypass the very recovery gate that is supposed to protect the
workflow from unsafe continuation.

The defect was in follow-up message eligibility. `can_send_followup()` in
`src/vaultspec_a2a/thread/message_policy.py` only blocked `input_required` and
terminal/archive states, which let `POST /api/threads/{id}/messages` accept
new work for `repair_needed` and `reconciling` threads. That overstated
interactability and let ordinary ingest race explicit repair/recovery logic.

The fix now fails closed for both repair states. Follow-up messaging is
rejected while a thread is `repair_needed` or `reconciling`, keeping message
dispatch aligned with the repo’s repair contract instead of papering over
checkpoint or reconciliation uncertainty.

Evidence:

- `src/vaultspec_a2a/thread/message_policy.py`
- `src/vaultspec_a2a/control/message_service.py`
- `src/vaultspec_a2a/thread/tests/test_message_policy.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/thread/tests/test_message_policy.py -q`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "test_rejects_followup_while_thread_requires_repair or test_rejects_followup_while_thread_is_reconciling"`
- `uv run ruff check src/vaultspec_a2a/thread/message_policy.py src/vaultspec_a2a/thread/tests/test_message_policy.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-052: MCP delete must match the stricter non-terminal delete contract

The delete hardening in Audit `6` created a new surface-alignment requirement:
once REST delete rejects non-terminal threads, the MCP delete tool must not
present a weaker or less legible contract. MCP is an operator-facing control
surface, so backend `409 Conflict` responses need to be translated into clear
tool-level errors rather than leaking as raw HTTP failures.

The defect was that `delete_thread` in
`src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py` still relied on
the generic request helper path and did not map backend conflict responses into
`ToolError`. That left the tool contract behind the backend lifecycle guard and
made non-terminal delete rejections look like transport-level failures instead
of explicit lifecycle protection.

The fix now maps backend `409` responses into `ToolError`, preserves the
backend detail when available, and updates the MCP delete documentation so
non-terminal rejection is explicit.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "delete_thread_raises_tool_error_for_nonterminal_thread or archive_thread_raises_tool_error_when_server_unavailable or delete_thread_raises_tool_error_when_server_unavailable"`
- `uv run ruff check src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-052: MCP delete must surface non-terminal delete conflicts as ToolError

The stricter delete contract introduced a new surface-level requirement:
anything that fronts the REST delete endpoint must translate non-terminal
delete rejection into a clear operator-facing error, not a raw transport or
HTTP failure. After `REVIEW-050`, the REST backend correctly failed closed on
non-terminal threads, but the MCP `delete_thread` tool still lagged behind
that contract.

The defect was in MCP error mapping. `delete_thread()` in
`src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py` did not catch
backend `409` conflicts, so MCP callers saw a lower-level failure instead of a
clear tool-level explanation that the thread was still non-terminal. The fix
now maps delete-side `409` responses into `ToolError` with backend detail and
updates the tool help text to describe non-terminal rejection explicitly.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "delete_thread_raises_tool_error_for_nonterminal_thread or archive_thread_raises_tool_error_when_server_unavailable or delete_thread_raises_tool_error_when_server_unavailable"`
- `uv run ruff check src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

### Open questions that affect scope quality

- What exact output makes a run count as “meaningful work” for this repo:
  terminal status only, final assistant content, emitted plan artifacts,
  or persisted thread metadata plus content?
- Should the first implementation prove permission approval using a
  purpose-built deterministic tape, or should it reuse an existing mock
  preset that already triggers `interrupt()` behavior?
- Is MCP flow required in the first merge for issue `#17`, or acceptable
  as a follow-up once the HTTP/SSE/permission/cancel path is stable?

### Assumptions to state explicitly

- The certification gate uses exact local stack inputs owned by this
  repository, not ad hoc shell overrides or hidden fixtures.
- VidaiMock is the deterministic provider backend for the main gate, and
  the chosen tape must remain stable across runs.
- The worker must remain controllable throughout execution: start,
  observe, interrupt, resume, cancel, and stop cleanly.
- The service gate validates real sockets, real persistence, and real
  SSE rather than `ASGITransport`-collapsed behavior.
- The main success criterion is stable, demonstrable work output under
  interruption and approval control, not merely process liveness.
- Tests may make broad but explicit assumptions about exact file-input
  text elements, interactive workflow steps, and deterministic operator
  choices so long as those assumptions are visible, repo-owned, and
  repeatable.

## REVIEW-053: `/api/threads` summaries must not advertise approvals without verified checkpoint truth

LangGraph’s interrupt and durable-execution model keeps resumability anchored
to the persisted checkpoint for the same `thread_id`. The interrupt docs say
the checkpointer writes the graph state that is later resumed, and the
durable-execution docs say workflows resume from the last recorded state
rather than from durable side-channel residue alone. That means a public
summary surface can degrade readiness when checkpoint probing fails, but it
cannot continue to expose `approval_status="pending"` and
`approval_request_id` as if a resumable human pause were still proven.

Audit `6` found that this stricter rule had only been applied to
`/api/threads/{id}/state`. `list_threads_service()` in
`src/vaultspec_a2a/control/thread_service.py` already degraded
`repair_status` and `execution_readiness` to `checkpoint_unavailable` when the
checkpointer probe timed out or raised, but it still preserved pending
approval metadata from the thread row or live durable permission rows. That
made `/api/threads` and the MCP-backed summary path overstate user-actionable
resumability at the exact boundary where checkpoint authority was unverified.

The fix keeps the summary contract consistent with the stricter thread-state
surface: once checkpoint probing is unverified, summaries fail closed by
clearing public approval metadata alongside readiness degradation. This does
not erase durable permission bookkeeping; it only stops public/operator
surfaces from presenting those rows as actionable approvals until checkpoint
truth can be established again.

Evidence:

- LangGraph interrupts docs: same-thread resume depends on checkpointer state
  for the `thread_id`
- LangGraph durable-execution docs: resume semantics come from the last
  recorded checkpointed state
- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "list_threads_hides_pending_approval_when_checkpoint_probe_is_unverified or list_threads_degrades_when_checkpoint_probe_is_unverified"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "list_threads_hides_pending_approval_when_checkpoint_probe_is_unverified or list_threads_degrades_when_checkpoint_probe_is_unverified"`
- `uv run ruff check src/vaultspec_a2a/control/thread_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-054: MCP `send_message` must match repair-state follow-up rejection

`REVIEW-051` tightened the backend follow-up contract so normal message ingest
fails closed for `repair_needed` and `reconciling` threads. That made the MCP
messaging surface subject to the same operator-facing requirement as the other
tool wrappers in Audit `6`: once the backend rejects a control action with
`409`, the MCP tool should surface a clear `ToolError` rather than leaking a
raw HTTP conflict.

The defect was in `src/vaultspec_a2a/protocols/mcp/tools/messaging.py`.
`send_message()` still relied on the generic request helper path, so when the
backend refused a follow-up to a repair-state thread, MCP callers saw a lower
level HTTP failure instead of a direct tool-level explanation that the thread
was not accepting follow-up messages. That weakened the operator contract even
though the backend behavior was already correct.

The fix now maps backend message-side `409` conflicts into `ToolError`,
preserves the backend detail when available, and keeps MCP follow-up behavior
aligned with the stricter repair-state messaging rules.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/tools/messaging.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "send_message_raises_tool_error_for_repair_needed_thread"`
- `uv run ruff check src/vaultspec_a2a/protocols/mcp/tools/messaging.py`

## REVIEW-055: MCP `respond_to_permission` must match stale-request conflict rejection

Audit `6` exposed the same operator-surface lag on the MCP permission-response
tool that previously existed on MCP delete and follow-up messaging. The
backend permission-response path already rejects stale requests when a newer
interrupt has taken ownership of the thread, but
`respond_to_permission()` in
`src/vaultspec_a2a/protocols/mcp/tools/discovery.py` still surfaced that
`409 Conflict` as a lower-level HTTP failure instead of a usable `ToolError`.

This is not a LangGraph defect; it is MCP error-mapping drift relative to the
repo’s stricter permission-response contract. Once the backend says a
permission request is no longer pending, the MCP tool must preserve that
meaning directly so operators do not mistake stale-request protection for
transport failure.

The fix now maps backend `409` responses into `ToolError`, preserves backend
detail when available, and adds a focused MCP regression proving that stale
permission requests surface as a clear tool-level error.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/tools/discovery.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "respond_to_permission_raises_tool_error_for_stale_request or respond_to_permission_dispatches_for_existing_thread or respond_to_permission_raises_when_server_unavailable"`
- `uv run ruff check src/vaultspec_a2a/protocols/mcp/tools/discovery.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-056: team status must ignore non-actionable durable permission residue

Audit `6` exposed a persistence-corruption leak in the team-status assembly
path. `build_team_status()` in `src/vaultspec_a2a/control/team_service.py`
already filtered out terminal owner threads, but it still treated all other
durable permission rows as public pending work. That left two non-actionable
cases leaking through the public team-status surface: orphaned permission rows
whose owning `ThreadModel` no longer existed, and permission rows owned by
threads already degraded to `checkpoint_unavailable`.

This is not a LangGraph checkpoint issue directly; it is a repo persistence
and public-state integrity issue. Team status is supposed to present
actionable, operator-facing work. Once the owning thread row is gone, or once
the owning thread has already lost checkpoint-backed actionability, a durable
permission row is only residue and must not be treated as live work.

The fix now requires a live non-terminal thread row before a durable
permission can contribute to `pending_permissions` or `active_threads`, and it
also hides public pending permissions for threads already degraded to
`checkpoint_unavailable`. The regressions prove the REST and MCP discovery
surfaces no longer surface orphaned residue or checkpoint-unverified pending
approvals as live work.

Evidence:

- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "team_status_excludes_orphaned_durable_permission_rows or team_status_hides_pending_permissions_without_checkpoint_truth or pending_permissions_hide_malformed_durable_rows or pending_permissions_do_not_surface_from_aggregator_without_durable_row"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "team_status_excludes_orphaned_durable_permission_rows or team_status_hides_checkpoint_unavailable_pending_permission or team_status_hides_malformed_durable_pending_permission or team_status_excludes_aggregator_only_pending_permission"`
- `uv run ruff check src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-057: MCP thread-query output must surface checkpoint-authority degradation

Audit `6` still had an operator-facing drift on the MCP thread-query surface.
`get_thread_status()` in
`src/vaultspec_a2a/protocols/mcp/tools/thread_query.py` only rendered the raw
thread `status`, even though the underlying `/api/threads/{id}/state` payload
already carried `repair_status` and `execution_readiness`. That meant a thread
degraded to `checkpoint_unavailable` could still read like a normal
`input_required` pause to an MCP operator, despite the checkpoint contract
already saying the pause was not currently actionable.

LangGraph grounding stayed the same here. The persistence layer and
human-in-the-loop interrupt docs make checkpoint-backed state the authority for
resume semantics. A public/operator surface that hides the degraded
`repair_status` and `execution_readiness` is therefore still overstating
actionability even if the raw data endpoint is correct. The fix now renders
those fields directly in the MCP tool output so resumable pauses and
checkpoint-unverified repair states are visibly distinct.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`
- LangGraph docs MCP pages:
  - `oss/python/langgraph/persistence`
  - `oss/python/langgraph/interrupts`
  - `oss/python/langchain/human-in-the-loop`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "get_thread_status_reports_repair_and_readiness or get_thread_status_raises_when_server_unavailable"`
- `uv run ruff check src/vaultspec_a2a/protocols/mcp/tools/thread_query.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-058: submitted thread-state snapshots must not expose stale approval residue

Audit `6` exposed another public-state drift at the thread-state surface.
`build_thread_state()` in
`src/vaultspec_a2a/control/thread_state_service.py` already failed closed when
checkpoint truth was missing, but it treated all `submitted` threads as a
special case and skipped that cleanup unconditionally. That was too broad. A
corrupted or stale durable approval row on a never-started thread could still
surface as pending permission state even though no checkpoint-backed pause had
ever been created.

The checkpoint-first grounding still applies. LangGraph persistence and
interrupt semantics make a paused, resumable approval meaningful only when it
belongs to a persisted thread checkpoint. A `submitted` thread with no
checkpoint truth is fine if it is clean, but once it already carries durable
approval residue it has crossed into the same non-actionable territory as the
other checkpoint-unverified cases. The fix now preserves the clean submitted
startup case while clearing stale approval residue when no checkpoint-backed
pause exists.

Evidence:

- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- LangGraph docs MCP pages:
  - `oss/python/langgraph/persistence`
  - `oss/python/langgraph/interrupts`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "submitted_thread_missing_checkpoint_clears_stale_pending_approval or missing_checkpoint_hides_durable_pending_permission_state"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_clears_submitted_stale_pending_approval_without_checkpoint or state_hides_pending_approval_when_checkpoint_probe_is_unverified"`
- `uv run ruff check src/vaultspec_a2a/control/thread_state_service.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-059: MCP guidance must match checkpoint-backed actionability

Audit `6` reached the point where the remaining mismatch was operator guidance
rather than raw state assembly. The server-level MCP instructions and the
permission-discovery help text still implied that a thread with
`status == input_required` necessarily had an actionable permission response
waiting. That was no longer true after the earlier hardening: this codebase now
distinguishes checkpoint-backed resumable pauses from checkpoint-unavailable
repair states, and the operator guidance needed to reflect that distinction.

The change does not alter behavior; it aligns the MCP guidance with the
contract already enforced by the API and tool outputs. Operators are now told
to inspect repair status and execution readiness before assuming a pause is
actionable, and `get_pending_permissions()` is described as the source of
currently actionable approvals rather than all paused threads in general.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/server.py`
- `src/vaultspec_a2a/protocols/mcp/tools/discovery.py`

Verification:

- `uv run ruff check src/vaultspec_a2a/protocols/mcp/server.py src/vaultspec_a2a/protocols/mcp/tools/discovery.py`

## REVIEW-060: MCP `list_threads` must surface checkpoint-authority degradation

LangGraph checkpoint truth is still the resumability authority. Audit `6`
found one more operator-surface drift on the MCP discovery path:
`list_threads()` was rendering only raw thread `status`, even though the
underlying REST summary already carried `repair_status` and
`execution_readiness`. That meant a degraded thread could still read like an
ordinary `input_required` pause even when the summary had already classified it
as `checkpoint_unavailable` or `needs_reconciliation`.

The MCP discovery surface now includes `repair_status` and
`execution_readiness`, matching the public REST summary and making degraded
checkpoint authority visible before an operator decides whether the thread is
actually resumable. This keeps the discovery surface aligned with the same
checkpoint-first contract already enforced elsewhere in Audit `6`.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "list_threads_reports_repair_and_readiness or list_threads_raises_when_server_unavailable"`
- `uv run ruff check src/vaultspec_a2a/protocols/mcp/tools/thread_query.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## Audit 6 closeout

LangGraph checkpoint truth remains the authority, and the Audit `6`
hardening now reflects that contract across the public and MCP surfaces.
After `REVIEW-060`, no stronger persistence/public-state or operator-surface
drift is obvious, so the remaining work should move forward into Audit `5`
supervisor plan-approval certification and Audit `7` multi-agent
cooperation and re-briefing rather than continuing to slice the same
boundary.

## Audit 5 slice 1: certify the supervisor-owned pause contract

The first Audit `5` service-certification slice strengthens the existing
real-stack supervisor approval scenario rather than broadening the matrix.
The service test now asserts the supervisor-owned contract directly:

- the first pause is `plan_approval_request`
- mirrored approval metadata stays aligned with that pending request
- the permission tool call is `plan_approval`
- the option set is the supervisor-owned `{approve, reject}` pair
- the later worker-owned permission pause is distinct and remains separately
  controllable

This keeps the audit focused on the supervisor boundary that is specific to the
LangGraph-driven orchestration layer, instead of treating both pauses as
undifferentiated permission events.

Evidence:

- `src/vaultspec_a2a/service_tests/test_permissions_resume.py`

Verification:

- `uv run pytest src/vaultspec_a2a/service_tests/test_permissions_resume.py -q -m service -k supervisor_plan_approval_pause_can_resume_through_real_stack`

## REVIEW-061: supervisor plan-approval service certification now asserts the supervisor-owned contract directly

LangGraph human-in-the-loop checkpoints are not just generic permission
pauses. The real-stack supervisor certification now checks the
supervisor-owned plan-approval pause explicitly, then distinguishes it from
the later worker-owned permission pause that follows plan approval. That
keeps the service lane aligned with the actual supervisory contract instead
of treating all pauses as the same kind of actionable work.

Evidence:

- `src/vaultspec_a2a/service_tests/test_permissions_resume.py`
- `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`

## REVIEW-062: supervisor rejection must carry revision context into the resumed worker path

LangGraph's rejection semantics are feedback-bearing resumes, not just a false
branch on the original interrupt. The rejection needs to survive checkpointed
resume as explicit next-node context; otherwise the resumed worker falls back
to the same privileged permission request path that the rejected plan was
supposed to revise. For Audit `5`, the bounded hardening keeps this explicit:
the anchoring context now includes rejected approval state and the routing
note, the VidaiMock worker tape uses that anchored context to emit a revision
message instead of requesting `session_request_permission`, and the compose
service lane proves the real reject -> revise -> fresh `plan_approval_request`
sequence before any privileged work resumes.

Evidence:

- `src/vaultspec_a2a/context/anchoring.py`
- `src/vaultspec_a2a/team/presets/mock/tapes/templates/mock-coder-human-chat.json.j2`
- `src/vaultspec_a2a/service_tests/test_permissions_resume.py`

Verification:

- `uv run pytest src/vaultspec_a2a/service_tests/test_permissions_resume.py -q -m service -k supervisor`
- `uv run ruff check src/vaultspec_a2a/context/anchoring.py src/vaultspec_a2a/context/tests/test_anchoring.py src/vaultspec_a2a/service_tests/test_permissions_resume.py`

## REVIEW-063: supervisor permission-response payload must report the submitted decision, not a flattened pending state

LangGraph's interrupt contract treats the resume payload as the human decision
that continues the graph. In the approval/reject examples, resuming with a
truthy or falsy decision immediately routes execution onward; the decision is
no longer "pending" at the response boundary. Audit `5` still had one public
surface that flattened this: the REST permission-response payload reported
`approval_status="pending"` for supervisor-owned plan decisions, even after
the operator had already approved or rejected the plan. That was especially
misleading for rejection because it made a feedback-bearing resume look like an
unanswered approval. The fix now reports `approved` or `rejected` on the
response payload itself while preserving checkpoint-backed thread state as the
authority for whether a fresh actionable approval exists.

Evidence:

- `https://docs.langchain.com/oss/python/langgraph/interrupts`
- `https://docs.langchain.com/oss/python/langchain/human-in-the-loop`
- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/service_tests/test_permissions_resume.py`

Verification:

- `uv run pytest src/vaultspec_a2a/service_tests/test_permissions_resume.py -q -m service -k "supervisor_plan_approval_pause_can_resume_through_real_stack or supervisor_plan_rejection_requires_revision_before_reapproval"`
- `uv run pytest -m service src/vaultspec_a2a/service_tests -q`
- `uv run ruff check src/vaultspec_a2a/control/permission_service.py src/vaultspec_a2a/service_tests/test_permissions_resume.py`

## REVIEW-064: stale rejected supervisor approval residue must not shadow live durable plan approval

LangGraph HITL reject semantics are feedback-bearing resume data, not a still-
pending approval target. Once the reject decision has been submitted, public
actionability has to be derived from the next live durable pending
`plan_approval_request`, not from stale `approval_status="rejected"` residue
left on the thread row. Audit `5` still had one stronger public-state
derivation defect after `REVIEW-063`: stale rejected metadata could remain on
thread-state and summary surfaces, and could even hide a fresh durable pending
plan approval that should have replaced it. The fix now recomputes public
approval metadata from live durable pending plan approvals, clears rejected
residue when no live plan approval exists, and proves the contract across the
reconnect snapshot, REST thread list, and MCP list-thread surfaces.

Evidence:

- `https://docs.langchain.com/oss/python/langchain/human-in-the-loop`
- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "rejected_thread_approval"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "test_list_threads_prefers_live_plan_approval_over_stale_rejected_status or test_list_threads_clears_stale_rejected_plan_approval_residue"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k test_list_threads_prefers_live_plan_after_rejected_residue`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/control/thread_service.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## Audit 5 closeout

After `REVIEW-064`, the bounded supervisor-certification scan no longer
exposed a stronger remaining public or operator-surface drift in the
supervisor plan-approval flow. The real-stack lane now certifies:

- the first interrupt is a supervisor-owned `plan_approval_request`
- plan rejection resumes with revision context instead of collapsing into
  generic privileged permission
- a fresh supervisor-owned approval is required before execution can continue
- the immediate REST response no longer misreports a completed human decision
  as a still-pending approval
- stale rejected approval residue neither surfaces publicly nor hides a fresh
  durable pending supervisor approval

That does not make the higher-level stack simple or low risk. It means the
strongest remaining risks have moved to the next roadmap layers: multi-agent
cooperation and re-briefing, sandbox/artifact behavior, and streaming/trace
lineage.

Verification:

- `uv run pytest src/vaultspec_a2a/service_tests/test_permissions_resume.py -q -m service -k supervisor_plan_approval_pause_can_resume_through_real_stack`
- `uv run ruff check src/vaultspec_a2a/service_tests/test_permissions_resume.py`

## Audit 6 closeout

After `REVIEW-060`, no stronger persistence/public-state or operator-surface
drift remained obvious in the audited public surfaces. The checkpoint-first
contract now holds consistently across the thread-state snapshot, thread
summary, team-status, MCP thread query, MCP discovery, and operator guidance
layers that Audit `6` targeted.

That does not mean the system is simple; it means the remaining risk has
shifted. The next meaningful fronts are no longer about stale durable residue
masquerading as resumable public state. They are the higher-level behavior
audits:

- Audit `5`: supervisor plan-approval service certification
- Audit `7`: multi-agent cooperation and re-briefing

## Audit 6 closeout

After `REVIEW-060`, the remaining repo scan no longer exposed a stronger
persistence/public-state or operator-surface defect in the audited surfaces:
REST thread state, REST summaries, team status, MCP thread queries, MCP
discovery, health readiness, and lifecycle public gates. The material pattern
behind Audit `6` has now been made explicit across those surfaces: checkpoint
truth governs resumability, durable residue alone is not actionable, and
public/operator tooling must surface degradation rather than flatten it into
raw thread status.

That does not mean the system is simple or risk-free. It means the strongest
remaining risks have shifted away from persistence/public-state drift and into
the next roadmap layers: supervisor plan-approval certification, multi-agent
cooperation and re-briefing, sandbox/artifact behavior, and trace lineage.

## REVIEW-065: rejected exec-plan re-briefs must route by phase ownership, not worker list order

Audit `7` opened with a concrete supervisor handoff defect. After a rejected
exec-phase plan approval, the supervisor node was hardcoding the re-brief path
to `workers[0]`. That happened to work for the single-worker certification
team, but it made multi-agent revision ownership depend on declaration order
instead of the worker that owns the plan phase. LangGraph handoff guidance
frames routing as persistent state-driven behavior across turns; the handoff
contract should follow the state/phase model, not positional list order. The
fix now prefers the worker mapped to the `plan` phase when a rejected exec
plan needs revision, and only falls back to the first worker when no plan-
phase worker exists.

Evidence:

- `https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs`
- `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`
- `src/vaultspec_a2a/team/presets/teams/vaultspec-adaptive-coder.toml`
- `src/vaultspec_a2a/team/presets/teams/vaultspec-continuous-audit.toml`

Verification:

- `uv run pytest src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py -q`

## REVIEW-068: recovered supervisor handoffs must clear stale approval residue

Audit `7` exposed the adjacent ownership-versus-approval split after
`REVIEW-067`. Clean supervisor reroutes were still leaving `approval_status`
and `approval_request_id` in shared graph state even after the workflow had
recovered from the original plan-approval exchange. That meant later worker
handoffs and re-briefing context could still read obsolete approval state as if
it were current, even though the routed owner had already moved on.

The grounding here is the LangChain human-in-the-loop and multi-agent handoff
guidance. HITL approval decisions are action-scoped to the interrupted action,
not durable authority for unrelated later turns, and handoff state should
reflect the current routed owner. Once the supervisor has recovered and rerouted
cleanly, stale approval residue is no longer valid handoff context.

The fix now clears `approval_status` and `approval_request_id` on recovered
supervisor routes so later worker handoffs and re-brief context reflect the
current owner instead of an obsolete plan-approval exchange.

Evidence:

- `https://docs.langchain.com/oss/python/langchain/human-in-the-loop`
- `https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs`
- `src/vaultspec_a2a/context/anchoring.py`
- `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`

Verification:

- `uv run pytest src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py -q`

## REVIEW-069: supervisor handoffs must stamp active_agent ownership

Audit `7` exposed a broader handoff-contract gap after `REVIEW-068`. This
repo's shared `TeamState` already defines `active_agent`, and LangGraph's
handoff guidance uses that kind of owner-tracking state variable as the
authoritative route context across turns. But the supervisor node in the
star-topology path was not updating `active_agent` on clean routes, recovered
reroutes, or `FINISH`, so the checkpointed handoff owner could remain stale or
blank even when the supervisor had already decided which worker owned the next
turn. The fix stamps `active_agent` on supervisor routes and clears it on
`FINISH` so checkpointed ownership matches the actual routed worker.

Evidence:

- `https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs`
- `src/vaultspec_a2a/thread/state.py`
- `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`

Verification:

- `uv run pytest src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py -q`

## REVIEW-070: supervisor reroutes must replace stale current_plan summaries

Audit `7` exposed the plan-summary mirror of the same handoff drift after
`REVIEW-069`. This repo already models `current_plan` as a full-replacement
reducer, but the supervisor was only writing it on the clean-route path.
Rejected reroutes, approval resumes, and routing-error reroutes all changed the
effective owner without replacing the shared route summary, which leaves the
old plan route sticky in checkpoint state. LangGraph handoff guidance treats
shared routing state as authoritative across turns, so later worker handoffs
and re-briefing should not inherit a stale route summary after ownership has
already moved. The fix stamps `current_plan` on every supervisor outcome so the
shared route summary matches the actual routed worker.

Evidence:

- `https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs`
- `src/vaultspec_a2a/thread/state.py`
- `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`

Verification:

- `uv run pytest src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py -q`
- `uv run ruff check src/vaultspec_a2a/graph/nodes/supervisor.py src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`

## REVIEW-066: routed worker phase must override artifact-derived phase during multi-agent handoff

Audit `7` immediately exposed a second supervisor/worker drift after
`REVIEW-065`. The supervisor had started rerouting rejected exec plans to the
correct plan-phase worker, but it was still persisting `pipeline_phase` from
`infer_phase_from_vault_index(...)`, which prefers the highest artifact phase
already present in `vault_index`. That is not a safe handoff contract once a
multi-agent team starts revising or re-briefing work after later-phase
artifacts already exist.

This mattered because the mount node selects phase documents from
`state["pipeline_phase"]`. A rerouted planning worker could therefore receive
mounted `exec` documents instead of the planning documents it actually owned.
That is a direct state/context split at the handoff boundary: supervisor
routing says one worker should act next, while mounted phase context tells the
worker it is still in a later phase. LangGraph handoff guidance is explicit
that handoffs should be driven by persistent state variables such as
`active_agent` or the current step, not by incidental historical artifacts.

The fix now treats the routed worker as the authority for `pipeline_phase`
whenever a `worker_phase_map` entry exists, and rejected plan revisions also
recompute phase ownership from the chosen revision worker rather than
reusing the previously selected exec phase.

Evidence:

- `https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs`
- `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `src/vaultspec_a2a/graph/nodes/vault_reader.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`

Verification:

- `uv run pytest src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py -q`
- `uv run ruff check src/vaultspec_a2a/graph/nodes/supervisor.py src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`

## REVIEW-067: recovered supervisor handoffs must clear stale routing_error context

Audit `7` exposed a third bounded handoff-state defect immediately after
`REVIEW-066`. The supervisor was persisting rejection and reroute notes in
`routing_error`, but later clean routes and successful approval resumes were
not actively clearing that field. In LangGraph handoff terms, that leaves
obsolete handoff context in the shared state even after the state-driven route
has recovered. The risk is not abstract: worker anchoring reads `routing_error`
directly, so a later worker turn could still be told that a plan was rejected
or rerouted when the supervisor had already moved back onto a clean path.

The fix now clears `routing_error` on clean supervisor routes and on successful
plan-approval resumes. That keeps the shared handoff state aligned with the
current owner of the turn instead of letting stale rejection notes continue to
shape later worker context.

Evidence:

- `https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs`
- `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`
- `src/vaultspec_a2a/thread/state.py`

Verification:

- `uv run pytest src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py -q`
- `uv run ruff check src/vaultspec_a2a/graph/nodes/supervisor.py src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py src/vaultspec_a2a/thread/state.py`

## REVIEW-071: consumed supervisor approval requests must clear on resume

Audit `7` exposed the next adjacent handoff-state problem after `REVIEW-069`.
The supervisor's resume paths for both approved and rejected plan-approval
decisions were still omitting `approval_request_id`, which meant shared
checkpoint state could keep an old request id alive even after that reviewed
action had already been consumed. LangGraph handoff guidance treats the shared
owner state as the authority across turns, so a consumed approval handle should
not remain in checkpoint state once the workflow has resumed. In this codebase
that residue matters because later graph-state consumers can misread the stale
request id as still-actionable approval context. The fix now clears
`approval_request_id` on both approval and rejection resumes so the resumed
handoff cannot carry a dead approval handle forward.

Evidence:

- `https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs`
- `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`

Verification:

## REVIEW-072: missing-review FINISH gates must reroute to the audit-phase owner

Audit `7` exposed a multi-agent ownership error in the blocked-FINISH path.
When exec work existed but the audit artifact was still missing, the
supervisor rerouted to the first worker instead of the audit-phase owner. That
meant the next turn could go to the wrong specialist, `next` and
`active_agent` could point at a worker that did not satisfy the blocked-finish
condition, and the workflow could loop or re-brief the wrong agent instead of
producing the missing audit output.

The grounding here is the LangChain multi-agent handoff guidance. Handoffs are
about transferring control to the specialist who should own the next subtask,
so a blocked-FINISH review gap should route to the audit/review owner rather
than an arbitrary first worker.

The fix reroutes blocked-FINISH review cases to the audit-phase owner so the
next handoff matches the actual missing work.

Evidence:

- `https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs`
- `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`

Verification:

- `uv run pytest src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py -q`
- `uv run ruff check src/vaultspec_a2a/graph/nodes/supervisor.py src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`

## REVIEW-073: worker turns must consume approved exec gate residue

Audit `7` exposed the next adjacent handoff-state problem in the worker exec
gate flow. An approved exec gate is action-scoped interrupt/resume state for
the specific paused worker turn it unlocked, not a durable general grant that
later worker turns, re-briefs, or handoffs may reuse. If that approved residue
survives past the unlocked turn, downstream multi-agent flows can silently
over-authorize later work, skip a fresh exec gate, and violate the intended
human-in-the-loop boundary.

The LangGraph and LangChain grounding is the same checkpoint-first contract
behind the earlier Audit `7` findings. Human-in-the-loop approvals belong to a
specific paused action on a specific thread and must be consumed when that
action resumes. The repo now enforces that in the worker turn path by consuming
approved exec-gate residue in `worker.py`, with the integration coverage
locking the handoff semantics at the worker boundary.

Evidence:

- `https://docs.langchain.com/oss/python/langgraph/interrupts`
- `https://docs.langchain.com/oss/python/langchain/human-in-the-loop`
- `src/vaultspec_a2a/graph/nodes/worker.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_worker_integration.py`

## Audit 7 closeout

No new confirmed live-path defect remains on the multi-agent cooperation and
re-briefing path. The residual watch item is
`src/vaultspec_a2a/context/token_budget.py::prepare_handoff()`, which still
omits phase, vault, and approval-state fields when constructing handoff
context. It is not a proven live bug in the current graph path because the
active runtime handoff path remains grounded in persisted/checkpoint-backed
state, but it should stay on watch because promoting the helper into a live
handoff surface later could reintroduce owner-vs-context drift.

## REVIEW-075: hard delete must purge thread-scoped checkpoint state

Audit `8` found that the delete path only proved the gateway row was removed
and that a root-namespace checkpoint lookup no longer returned state for the
thread. That does not satisfy LangGraph's thread-scoped persistence model.
A correct hard delete must purge all checkpoint state for the `thread_id`,
including subgraph namespaces and checkpoint history, not just absence of
`checkpoint_ns=""`. If any thread-scoped checkpoint state survives, the
application can report the thread as deleted while LangGraph still retains
resumable or inspectable state for that same `thread_id`.

The grounding is the same checkpoint-first contract used elsewhere in the
audit trail: checkpoints are thread-scoped, `thread_id` is the durable pointer
used to save and resume state, and `get_state` / `get_state_history` operate
over that persisted thread state. The delete boundary therefore has to fail
closed across the full thread scope, not just a single namespace probe.

Sources:

- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/langsmith/use-remote-graph#persist-state-at-the-thread-level
