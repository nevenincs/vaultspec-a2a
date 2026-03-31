---
tags:
  - '#plan'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
related:
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-adr]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-research]]'
  - '[[2026-03-31-integration-testing-service-certification-research]]'
  - '[[2026-03-30-service-layer-research]]'
  - '[[2026-03-30-service-layer-rolling-audit]]'
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
  - '[[2026-03-31-decoupled-mockllm-adr]]'
---

# `integration-testing-smoke-tests-api-verification` implementation plan

Restore a small, trustworthy service-certification path for issue `#17`.
The goal is to prove the refactored architecture can run end-to-end against
the local stack without errors, remain controllable during execution, and
produce meaningful observable work that developers can trust. This plan keeps
the deterministic service gate separate from any live-provider compatibility
smoke.

## Mission Statement

This work is aimed at deterministic, stable, repeatable, controllable,
and predictable output from the real pipeline and its full stack, with
VidaiMock as the certification provider surface. The intent is not to
prove only that the code executes, but that the live system can be
driven through exact file contents, interactive workflows, cancellation,
resumption, steering, re-briefing, and hostile permission conditions
while continuing to behave in a meaningful and observable way.

The certification gate should prefer exact, repo-owned file inputs and
explicit operator actions over implicit behavior or magic fixtures. Its
success condition is that the stack remains runnable, observable,
interactable, and controllable throughout the scenario, and produces the
same expected outcomes when the tested conditions are held constant.

## Proposed Changes

Build a real-stack certification tier around the existing `service` marker.
The certifying path should use real gateway and worker processes, durable
persistence, deterministic provider replay, SSE verification, and trace
verification. It must reject the current `ASGITransport`-style boundary
collapse as insufficient for this issue.

The implementation should start with the smallest stack that can prove the
feature:

- gateway
- worker
- deterministic mock provider backend
- Jaeger
- SQLite persistence

Postgres and live provider compatibility smoke remain separate extensions, not
prerequisites for the first green certification gate.

## Tasks

- **Phase 1 — Restore the certifying local topology**
  1. Reintroduce an owned integration topology for the service suite so the
     gateway, worker, deterministic provider backend, and Jaeger can be
     started together from the repository.
  1. Define the service-test environment contract so the stack can force the
     deterministic provider path and use isolated persistence and checkpoint
     state per run.
  1. Keep the topology aligned with the current `service/` layout and
     document the exact stack shape used by the certification suite.
  1. Confirm the stack can start, become healthy, and remain addressable over
     real sockets before any scenario tests run.

- **Phase 2 — Build the service test harness**
  1. Add the `service`-scoped test harness entry point and session-scoped
     stack fixture that owns startup, readiness checks, teardown, and artifact
     capture.
  1. Make readiness fail hard if the gateway, worker, deterministic provider,
     or Jaeger cannot be reached.
  1. Capture logs, health payloads, and partial stream events on failure so a
     failed run is diagnosable without rerunning manually.
  1. Ensure trace export has a real flush path so the suite can verify that
     the distributed trace pipeline actually emitted data.
  1. Keep the harness explicit about runtime control: start, wait, interact,
     assert, and stop cleanly every run.

- **Phase 3 — Add certifying scenario tests**
  1. Add the full thread lifecycle scenario over public HTTP, including create,
     dispatch, polling, and terminal-state verification.
  1. Add an SSE scenario that consumes the real stream and asserts semantic
     milestone events through completion.
  1. Add the permission approval scenario that proves pause, user response, and
     resume are all controllable through the public API.
  1. Add the cancel scenario and verify the observable transition through the
     terminal cancellation path.
  1. Add the health and trace scenario so the suite proves both backend status
     reporting and at least one end-to-end exported trace.
  1. Add the MCP path only if the current product surface still requires it for
     issue `#17`; otherwise leave it as a follow-up track.
  1. Keep assertions outcome-oriented and resilient: test the workflow result
     and state transitions, not brittle implementation details or full payload
     snapshots.

- **Phase 4 — Add operator-facing commands and docs**
  1. Add a canonical command path for the service suite so developers can run
     the certification gate without ad hoc shell steps.
  1. Document the service stack, the deterministic provider requirement, the
     expected health endpoints, and the trace verification expectations.
  1. Document how to inspect failure artifacts and how to tell whether the
     stack remained controllable during a run.
  1. Call out the live-provider compatibility path as a separate opt-in smoke
     lane, not part of the deterministic certification gate.

- **Phase 5 — Verification and gating**
  1. Prove the new service suite passes as a standalone gate against the real
     stack.
  1. Verify the suite actually exercises sockets, persistence, streaming, and
     observability rather than collapsing back to in-process substitutes.
  1. Confirm the stack can be started, observed, controlled, and shut down
     cleanly throughout the scenario flow.
  1. Keep the existing non-service test tiers intact and ensure the new gate
     does not weaken them.

## Parallelization

Phase 1 and Phase 2 can be prepared together, but the harness must follow the
chosen stack shape. Phase 3 depends on Phase 2 because the scenario tests need
the fixture and diagnostics. Phase 4 can proceed once the stack and harness are
stable. Phase 5 is the final gate and should run after the earlier phases are
merged together in the same branch.

## Verification

Mission success means the repository has a small, repeatable `service` suite
that certifies the real local architecture without errors or exceptions in the
happy path. The proof must include:

- real gateway and worker processes
- deterministic provider execution through the chosen replay backend
- real HTTP and SSE interaction
- observable permission, cancel, and completion flows
- health checks that reflect the actual backend state
- at least one exported trace proving the gateway-to-worker path ran
- clean startup, interaction, and teardown so the stack remains controllable
  and interactable throughout the run

The first pass should fail the PR if it still depends on in-process worker
fixtures, fake provider execution, or unverified trace behavior. Live Claude,
Gemini, OpenAI/Codex, or Zhipu compatibility can be added as a separate opt-in
smoke lane once the deterministic certification gate is stable.

## Follow-On Audit Roadmap

The remaining work should be divided into separate audits rather than
treated as one broad hardening effort. Each audit should have its own
acceptance criteria and its own deterministic service-level checks so
regressions can be isolated quickly and the certification signal remains
stable across future changes.

- Audit 1: interrupt, permission, and resume correctness.
  Cover stale approvals, wrong-thread resume, denied approvals,
  malformed approval payloads, and repeated resume idempotency.
- Audit 2: persistence, corruption, and restart resumability.
  Cover checkpoint replay, restart after interruption, degraded
  snapshots, and corruption surfacing instead of silent repair.
- Audit 3: streaming continuity and replay behavior.
  Cover SSE reconnect, ordered event replay, terminal replay, and
  tool-call chunk continuity across reconnect and completion.
- Audit 4: multi-agent steering and re-briefing.
  Cover supervisor routing, stale-context prevention, re-brief on state
  change, and no-double-route guarantees during collaborative work.
- Audit 5: cancellation and cleanup behavior.
  Cover cancel vs interrupt semantics, in-flight cancellation, terminal
  cancellation visibility, and absence of zombie execution.
- Audit 6: hostile-environment and sandbox-boundary behavior.
  Cover non-permitted actions, approval refusal paths, bounded file
  access, and destructive-action gating inside supported sandboxes.
- Audit 7: VidaiMock tape brittleness and deterministic replay quality.
  Cover tape selection stability, prompt-shape sensitivity, exact output
  determinism, and operator-visible failure modes when the mock backend
  is unavailable.
- Audit 8: artifact persistence and file-removal safety.
  Cover artifact attribution, cross-thread isolation, persistence across
  turns, explicit removal flow, and approval-gated deletion behavior.
