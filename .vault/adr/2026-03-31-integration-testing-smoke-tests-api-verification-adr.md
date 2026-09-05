---
tags:
  - '#adr'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
modified: '2026-09-05'
body_hash: 'sha256:11b51d42c764965e12fcd0e2ab14cbb070fcac3746fe3c8c0bb09e032c33130c'
related:
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-research]]'
  - '[[2026-03-31-integration-testing-service-certification-research]]'
  - '[[2026-03-30-service-layer-research]]'
  - '[[2026-03-30-service-layer-rolling-audit]]'
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
  - '[[2026-03-31-decoupled-mockllm-adr]]'
---

# `integration-testing-smoke-tests-api-verification` adr: `real-stack service certification for issue #17` | (**status:** `accepted`)

## Problem Statement

PR `#16` removed the legacy live-test harness and intentionally left the repository without any real cross-layer certification path. Issue `#17` must restore a small but trustworthy integration gate that proves the refactored service layer can deliver meaningful work against the local stack, without collapsing back into in-process test doubles.

## Considerations

The repository already has a clean Layer 3 service layout, a `service` pytest marker, deterministic mock provider tapes, real HTTP routes, and a production-like compose topology with gateway, worker, SQLite, and Jaeger. The missing piece is a certifying test harness that exercises the real process boundary and produces observable outcomes that developers can trust.

The issue explicitly requires real public API testing, real gateway and worker processes, deterministic provider replay, durable persistence, SSE verification, and trace verification. It does not require the reintroduction of broad live-test sprawl. The repo also supports real Claude, Gemini, OpenAI/Codex, and Zhipu provider paths, but those should be validated separately because live auth and upstream availability are not stable certification inputs.

## Constraints

The main certification suite must not use `ASGITransport`, monkeypatching, fake chat models, or patched transports. It must fail hard when the stack is not reachable, and it must remain small enough to run regularly. SQLite is the first persistence target; Postgres can be added later as an extension, not as a blocker. Live provider compatibility checks are opt-in and should not determine whether the main service gate is green.

## Implementation

Add a session-scoped `service_stack` test fixture that owns the real service lifecycle for the certification suite. The stack should bring up the gateway, worker, deterministic mock provider path, and Jaeger, then wait for health/readiness before tests execute.

Write the `@pytest.mark.service` suite as scenario tests against public interfaces:

- thread lifecycle over real HTTP
- SSE stream verification to terminal completion
- permission pause and resume
- cancel flow
- health and trace verification

Keep provider compatibility smoke separate from the certification suite. If retained, it should exercise real Claude, Gemini, OpenAI/Codex, or Zhipu paths as an explicit opt-in track with its own failure semantics and runtime expectations.

## Rationale

This decision preserves the meaning of `service` tests as proof of actual stack function. VidaiMock gives deterministic replay for the certification gate, while the real provider paths remain available for later compatibility smoke without contaminating the deterministic signal. That split matches the repo's architecture, the LangGraph local-testing pattern, and the operational reality that live providers are variable inputs.

## Consequences

The first pass on issue `#17` will be narrower, but much more trustworthy: developers get a repeatable certification gate for real work, not a brittle live-provider matrix. The downside is that live Claude/Gemini/OpenAI/Zhipu compatibility is not proven by the main suite and must be covered by a separate opt-in smoke track if the project wants that guarantee.

## Amendment - provider smoke follows current catalog membership; Gemini is retired (2026-09-06, owner no-legacy directive)

The deterministic real-stack certification decision remains unchanged. Any
separate opt-in provider compatibility smoke ranges only over lanes present in
the current provider-model catalog and must use each current lane's own failure
semantics and runtime prerequisites.

The original references to a real Gemini path, available real-provider paths,
and a possible Gemini compatibility smoke describe the inventory understood
when this record was written. They create no present availability claim. The
`gemini/gemini-cli-acp` lane is retired in full and has no retained
compatibility route, opt-in smoke, credential gate, availability promise, or
future test/proof obligation. Completed historical plans and test results
remain records of their captured revisions; they do not reactivate a removed
provider.

A current catalog member may receive explicit opt-in compatibility coverage
when its own active contract requires it. Such coverage remains separate from
the deterministic service certification gate and cannot be used to justify
support for a lane absent from the current catalog.
