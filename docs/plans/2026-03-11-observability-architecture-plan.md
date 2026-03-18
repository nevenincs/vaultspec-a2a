## Purpose

This plan starts the observability architecture track opened by the
2026-03-11 pivot. It converts the grounded conclusions for `#88`, `#89`, and
the verifier follow-on in `#87` into an execution order.

This is intentionally a design-first plan. The current gap is not only
"capture more logs"; it is the lack of a formal authority model for:

- debug evidence across gateway, worker, Docker, and ACP subprocesses
- local ACP vs Docker-bundled provider runtime authority
- how verifier artifacts should join logs, traces, and runtime state

---

## Grounding Inputs

- `docs/plans/2026-03-11-observability-pivot-handoff.md`
- `docs/research/2026-03-11-observability-debug-correlation-grounding.md`
- `docs/adrs/010-observability-telemetry-integration.md`
- `docs/adrs/017-containerization-strategy.md`
- `docs/adrs/031-worker-process-architecture.md`
- `docs/adrs/036-debug-evidence-surface.md`
- `docs/adrs/037-acp-runtime-authority.md`
- `docs/audits/2026-03-08-continuous-backend-readiness-audit.md`
- `docs/audits/2026-03-08-prod-readiness-consolidated-audit.md`

---

## Locked Workflow Rules

Every slice in this track still follows the repo mandate:

1. Ground the slice first with Context7 or official docs when library/runtime
   behavior is involved.
2. Implement only after the architecture stays coherent with ADR-036 and
   ADR-037.
3. Verify with real code paths and real services where applicable.
4. Run a review pass on the actual diff.
5. Sync findings back into the audit and queue docs before closing the slice.

This plan does not relax the no-mocks/no-fakes/no-tautological-tests rule.

---

## Architectural Decisions Now In Force

### Debug evidence model

- Jaeger remains the authoritative trace backend.
- Structured service logs remain the authoritative debug-log surface.
- Log records must gain automatic `trace_id` / `span_id` correlation where a
  current span exists.
- OTLP logs are deferred until the repo chooses a real log-capable backend and
  operator workflow.

### ACP/runtime authority model

- Local native execution remains authoritative for non-Docker flows.
- Docker-bundled provider runtime is a separate authority for prod-like worker
  verification and deployment parity.
- The worker remains the sole ACP execution authority in both modes.
- ACP subprocess protocol state is the authoritative provider-runtime truth
  surface; traces and logs must correlate back to it, not replace it.

---

## Current Open Queue

### Primary design tasks

- `#88` OBS-ARCH-01
  - Formal log/trace correlation architecture
  - Authoritative multi-service debugging surface

- `#89` ACP-ARCH-01
  - ADR-backed local ACP vs Dockerized provider runtime authority
  - Observability boundaries for local CLI, bundled runtime, container worker,
    and ACP subprocesses

### Dependent implementation task

- `#87` PG-VERIFY-03
  - Prod-like Docker verifier times out at gateway readiness
  - Diagnostics remain too thin before teardown

### Still-active workflow task

- `#71` AUDIT-LOOP-01

### Still-partial provider task

- `#86` PROV-DOCKER-02
  - Live credential-backed Docker provider certification remains pending in the
    target environment

---

## Execution Tracks

### Track 1: Log/Trace Correlation Implementation for `#88`

Goal:

- make structured logs authoritative for debug use across gateway, worker, and
  verifier flows

Required slice outcomes:

- inject OTel correlation fields into first-party structured logs by default
- standardize stable correlation keys where available:
  - `thread_id`
  - `dispatch_id`
  - `worker_id`
  - `client_id`
  - `provider`
  - `session_id`
  - service/runtime identity
- preserve Rich as an operator-facing presentation layer only

Verification requirements:

- real service logs show correlation fields during traced execution
- verifier artifacts preserve those fields in captured logs

### Track 2: ACP Observability Boundary Hardening for `#89`

Goal:

- make ACP subprocess/runtime failures classifiable by authority boundary

Required slice outcomes:

- log resolved runtime authority at ACP launch:
  - local-project
  - local-system
  - docker-bundled
  - binary-experimental when applicable
- normalize ACP stderr/stdout/session-phase diagnostics into structured logs
- surface subprocess lifecycle evidence with enough context to distinguish:
  - runtime resolution failure
  - spawn failure
  - initialize failure
  - session/new failure
  - session/prompt failure
  - provider auth/quota/network failure

Verification requirements:

- real local probe runs and repo-owned provider paths emit structured,
  phase-aware evidence
- Docker provider verification persists probe/runtime artifacts explicitly

### Track 3: Verifier Evidence Hardening for `#87`

Goal:

- turn `vaultspec test prodlike-docker` into a coherent evidence collector
  rather than a timeout wrapper around compose logs

Required slice outcomes:

- capture pre-teardown container inspect and health-state artifacts
- persist repeated readiness probe observations during startup
- add a manifest linking:
  - run timestamp
  - services/containers
  - thread ids if created
  - discovered trace ids
  - artifact files containing correlated evidence
- persist provider probe stdout/stderr artifacts for
  `prodlike-provider <claude|gemini>`

Verification requirements:

- a failing run produces enough artifacts to classify the failure without
  rerunning immediately
- a successful run still proves gateway/worker trace evidence in Jaeger

---

## Recommended Order

1. Keep `#71` active throughout.
2. Implement the minimum logger correlation slice for `#88`.
3. Implement ACP runtime/phase-aware observability for `#89`.
4. Rework verifier artifact capture for `#87` on top of the new authority
   model.
5. Return to `#86` only when real provider credentials are available for the
   target Docker environment.

Why this order:

- `#87` depends on `#88` and `#89` for a coherent evidence model.
- `#86` should not be used to infer architecture; it is a certification task,
  not a design task.

---

## Exit Criteria For This Plan

- ADR-036 and ADR-037 remain consistent with implemented behavior.
- Logs and traces can be joined by stable identifiers in real runs.
- ACP failures can be classified by runtime authority and protocol phase.
- `vaultspec test prodlike-docker` preserves enough pre-teardown evidence to
  diagnose startup stalls.
- The audit and queue docs reflect implementation findings after each slice.
