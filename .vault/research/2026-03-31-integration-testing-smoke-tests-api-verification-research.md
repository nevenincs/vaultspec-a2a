---
tags:
  - '#research'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
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
- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/thread/snapshots.py`
- `src/vaultspec_a2a/api/routes/thread_state.py`

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
