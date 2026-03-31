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

### Open questions that affect scope quality

- What exact output makes a run count as “meaningful work” for this repo:
  terminal status only, final assistant content, emitted plan artifacts,
  or persisted thread metadata plus content?
- Should the first implementation prove permission approval using a
  purpose-built deterministic tape, or should it reuse an existing mock
  preset that already triggers `interrupt()` behavior?
- Is MCP flow required in the first merge for issue `#17`, or acceptable
  as a follow-up once the HTTP/SSE/permission/cancel path is stable?
