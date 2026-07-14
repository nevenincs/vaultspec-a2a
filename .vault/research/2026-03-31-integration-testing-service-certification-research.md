---
tags:
  - '#research'
  - '#integration-testing'
date: '2026-03-31'
modified: '2026-03-31'
related:
  - '[[2026-03-30-service-layer-research]]'
  - '[[2026-03-30-service-layer-rolling-audit]]'
  - '[[2026-03-31-decoupled-mockllm-adr]]'
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
---

# `integration-testing` research: `service-certification-stack-and-real-execution-patterns`

Researched the implementation shape for issue `#17`, which needs to
restore meaningful end-to-end certification after PR `#16` removed the
legacy live-test suite. The goal is not broad test quantity; it is a
small certifying pipeline that proves the public API, worker execution,
provider streaming, persistence, and observability work together against
the local development stack.

## Findings

### Local project state after PR `#16`

- The repo now has a clean three-layer architecture, a `service/`
  directory, thin REST handlers, delegated WebSocket dispatch, and a
  dedicated `service` pytest marker.
- The current test suite exercises real FastAPI routing, real SQLite,
  real LangGraph checkpoint persistence, and real request/response
  serialization, but it still replaces the true process boundary with
  in-process `ASGITransport` worker fixtures.
- The existing middleware harness is therefore useful as a source of
  request payloads and assertions, but it is explicitly insufficient for
  issue `#17` because it does not prove gateway-to-worker networking,
  startup ordering, or service lifecycle.
- The accepted service architecture still assumes gateway, worker, UI,
  and optional infrastructure such as Jaeger, Postgres, and VidaiMock.
  That expectation remains documented in the service lifecycle ADR.

### Immediate gap between issue `#17` and the current branch

- Issue `#17` requires real gateway + worker processes, deterministic
  VidaiMock-backed graph execution, real database persistence, real SSE
  verification, and real OTLP-to-Jaeger trace verification.
- PR `#16` intentionally deleted the old live-test harness, including
  `docker-compose.integration.yml`, `docker/vidaimock.Dockerfile`,
  live-only CI workflows, and service lifecycle recipes for VidaiMock.
- The codebase still retains the `MockChatModel`, `MOCK_API_BASE`
  config, and mock team/agent presets, which means the provider-side
  execution path still exists conceptually but no longer has an owned
  stack launcher.
- The practical consequence is that issue `#17` is not only a test-file
  task. It must also reintroduce a minimal certifying stack for the
  provider and trace infrastructure that the service tests depend on.

### Reference pattern 1: LangGraph local server and streaming APIs

- LangGraph’s local tooling distinguishes between direct local execution
  and Docker-backed execution. The CLI docs explicitly separate
  `langgraph dev` from `langgraph up`, with `langgraph up` running the
  API server locally in Docker.
- LangGraph’s local development docs make the same split explicit:
  `langgraph dev` runs directly in the local environment, while
  `langgraph up` builds a Docker container and runs the code inside that
  isolated container.
- LangGraph’s streaming API treats streaming as a first-class public
  contract. The API is a real HTTP boundary, with `POST /threads`,
  followed by `POST /threads/{thread_id}/runs/stream`, and support for
  structured stream modes such as `updates`, `debug`, `events`, and
  `custom`.
- Relevant source URLs:
  - https://docs.langchain.com/langsmith/cli
  - https://docs.langchain.com/langsmith/local-dev-testing
  - https://docs.langchain.com/langsmith/streaming

### Reference pattern 2: VidaiMock as deterministic streaming provider infrastructure

- VidaiMock is a standalone mock server, not an in-process patching
  mechanism. Its stated value is protocol-accurate streaming over real
  HTTP endpoints.
- The project describes itself as a batteries-included mock server for
  LLM APIs that works with OpenAI-compatible chat completions and emits
  provider-native streaming payloads with realistic token timing.
- This matches the existing repo ADR direction much better than a fake
  chat model or request-patching approach because the repo needs to
  validate SSE tool-call handling and interrupt behavior at the wire
  level.
- Relevant source URL:
  - https://github.com/vidaiUK/VidaiMock

### Reference pattern 3: Testcontainers for ephemeral certifying dependencies

- Testcontainers Python positions itself for functional and integration
  testing with real containerized dependencies rather than mocks.
- The docs expose two useful primitives for this repo: dedicated modules
  such as `PostgresContainer`, and lower-level `DockerContainer` /
  `DockerImage` for custom services.
- The docs also note Docker-in-Docker and Docker socket constraints,
  which matters if these tests are later moved into CI.
- For this repo, Testcontainers is relevant if the preferred shape is a
  per-test or per-session harness that starts Postgres, Jaeger, and
  VidaiMock without depending on a long-lived manually managed stack.
- Relevant source URLs:
  - https://testcontainers-python.readthedocs.io/
  - https://testcontainers-python.readthedocs.io/en/testcontainers-v4.12.0/core/README.html

### Reference pattern 4: Jaeger trace retrieval as an assertable API surface

- Jaeger documents both collector ingestion and query retrieval APIs.
- The recommended programmatic retrieval path is the `QueryService`
  gRPC endpoint, while the JSON HTTP API used by the UI remains
  intentionally undocumented and subject to change.
- For the repo’s immediate local certifying pipeline, the HTTP JSON API
  is pragmatic and likely sufficient for smoke-level assertions, but the
  project should treat it as a test-only convenience, not a stable
  production integration point.
- Relevant source URL:
  - https://www.jaegertracing.io/docs/latest/deployment/

### Reference pattern 5: Temporal’s split between real-server integration tests and accelerated determinism tools

- Temporal’s Python SDK explicitly states that workflow testing can be
  done against a real server in an integration-test fashion, but that
  special harnesses are valuable for time-heavy cases.
- The important lesson for this repo is architectural, not product
  choice: keep a clear distinction between certifying real-stack tests
  and faster deterministic tests that collapse parts of the environment.
- Issue `#17` belongs on the certifying side of that split. Existing
  middleware tests already cover the faster boundary-collapsed tier.
- Relevant source URL:
  - https://github.com/temporalio/sdk-python

### Reference pattern 6: Mature self-hosted AI stacks certify Docker Compose topologies directly

- Dify’s self-hosted docs treat Docker Compose as the operational unit
  and require users to verify container health with `docker compose ps`
  after startup.
- Open WebUI’s observability docs ship a dedicated Docker Compose file
  for OTEL-enabled local stacks and document the exact environment
  variables used to wire traces and metrics into a collector.
- The shared lesson is that local stack certification should assert the
  composed topology, not only the application code.
- Relevant source URLs:
  - https://docs.dify.ai/en/self-host/quick-start/docker-compose
  - https://docs.openwebui.com/reference/monitoring/

### Recommended approach for issue `#17`

- Build a two-tier testing model.
- Tier 1 remains the current `core` and `middleware` suite, which is
  fast and isolates layers without requiring external services.
- Tier 2 becomes a very small `service` suite whose sole purpose is
  certification of the real stack.
- The `service` suite should run against one managed stack fixture per
  test session, not per test case. Service startup cost is too high for
  function-level isolation, and issue `#17` is about proving the stack,
  not maximizing case count.
- The fixture should own startup, readiness checks, environment
  propagation, teardown, and artifact capture.
- The first certifying stack should be the smallest topology that proves
  meaningful work:
  - gateway
  - worker
  - VidaiMock
  - Jaeger
  - SQLite-backed persistence first, with Postgres as an optional
    follow-up or separate track
- The tests should drive only public/protocol surfaces:
  - real HTTP for REST endpoints
  - real SSE stream consumption for thread events
  - real MCP stdio only if MCP is still considered part of the supported
    surface for this issue
- Assertions should be outcome-oriented:
  - terminal thread status
  - persisted thread/message state
  - expected permission request creation and later resolution
  - observable streamed event sequence
  - presence of at least one end-to-end trace spanning gateway and worker

### Harness recommendation

- Prefer a Python-owned stack fixture instead of delegating the entire
  problem to ad-hoc shell scripts.
- There are two viable ownership models:
  - Compose-driven fixture that shells out to `docker compose` against a
    repo-owned integration compose file
  - Testcontainers-driven fixture that starts the required dependency
    containers and launches gateway/worker as subprocesses
- For this repo, the Compose-driven fixture is the better first move.
  The repo already uses Compose as an accepted deployment unit, has
  existing `service/` conventions, and needs to restore a documented
  multi-service topology anyway.
- The likely shape is a dedicated integration compose file or overlay
  that adds VidaiMock and Jaeger back on top of the current service
  definitions, with environment values that force `Provider.MOCK`
  presets through the real provider path.

### Minimal certifying scenarios

- Thread lifecycle certifier:
  create thread through public HTTP, let worker complete against
  VidaiMock, poll until terminal, assert persisted content and final
  status.
- SSE certifier:
  subscribe before or immediately after dispatch, collect events until
  terminal completion, assert ordered lifecycle milestones rather than
  brittle exact payload snapshots.
- Permission certifier:
  use a mock preset that deterministically emits a permission tool call,
  assert paused/input-required state, respond through public REST, then
  assert resumed completion.
- Cancel certifier:
  start a long enough deterministic run, submit cancel through public
  REST, assert `cancelling` then `cancelled`.
- Health/trace certifier:
  assert `GET /api/health`, then retrieve Jaeger data to prove at least
  one distributed trace crossed the gateway and worker boundary.

### Design constraints for meaningful work

- Do not reintroduce the deleted live-test sprawl. The success condition
  is a narrow certifying pipeline, not dozens of environment-sensitive
  cases.
- Do not use `ASGITransport`, monkeypatching, or fake chat-model paths
  in the `service` marker suite. Those remain valid only in lower test
  tiers.
- Do not assert exact whole-payload snapshots for every streamed event.
  Assert semantic milestones and selected fields so the tests remain
  strict about behavior but resilient to harmless metadata drift.
- Capture stack diagnostics on failure: container logs, gateway/worker
  stderr, streamed events captured so far, and health payloads. Without
  this, service tests will be too expensive to debug.

### Open questions that affect implementation scope

- Whether issue `#17` should certify SQLite only or both SQLite and
  Postgres. The issue text says Postgres-specific tests are out of scope,
  which suggests SQLite should be the certifying baseline.
- Whether MCP stdio remains in scope for the first PR. The issue says
  “if MCP retained,” so this should be treated as optional unless the
  current product surface still promises MCP thread operations as a
  supported path.
- Whether VidaiMock should be restored via Docker image, downloaded
  binary, or both. Given the existing service architecture, Docker-based
  restoration is the least surprising path for issue `#17`.
