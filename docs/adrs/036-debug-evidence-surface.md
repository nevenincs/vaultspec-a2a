---
adr_id: 036
title: Debug Evidence Surface
date: 2026-03-11
status: Proposed
related:
  - docs/adrs/010-observability-telemetry-integration.md
  - docs/adrs/017-containerization-strategy.md
  - docs/adrs/031-worker-process-architecture.md
  - docs/plans/2026-03-11-observability-pivot-handoff.md
---

# ADR-036: Debug Evidence Surface

**Date:** 2026-03-11
**Status:** Proposed

## 1. Context & Problem Statement

ADR-010 established OpenTelemetry tracing as mandatory from day one. That
decision remains correct, but it did not define the full debugging model for
the current multi-process system.

The repository now has a real distributed runtime:

- **Gateway** process with REST and WebSocket surfaces
- **Worker** process with graph execution and provider orchestration
- **Dockerized production-like stack** with gateway, worker, Postgres, and
  Jaeger
- **ACP subprocesses** spawned by the worker for Claude and Gemini provider
  flows

Trace evidence exists and Jaeger is functioning as the trace backend, but the
remaining failures show that tracing alone is not enough to support debugging:

- structured logs are present but do not carry OTel correlation identifiers by
  default
- verifier artifacts capture service logs and Jaeger traces separately, without
  one authoritative join key
- ACP subprocess stderr/stdout is still mostly an opaque text stream from the
  perspective of the overall diagnostic model
- Jaeger is being used successfully as a trace backend, but it is not the
  complete answer for operator-grade debug evidence

The missing architectural decision is therefore:

- what the authoritative debug evidence surface is today
- whether log transport should remain structured stdout/container logs with
  trace correlation, or whether the repository should add an OTLP logs pipeline
  immediately

## 2. Decision

The authoritative debug evidence model for the current system is:

1. **Jaeger remains the authoritative trace backend.**
2. **Structured logs remain the authoritative log/debug surface.**
3. **All first-party log records must carry trace correlation fields whenever a
   current span exists.**
4. **OTLP logs export is explicitly deferred until the repository adopts a real
   log-capable backend and retention/query model.**

This means the current architecture chooses:

- **structured logs + trace correlation now**
- **not** structured logs + trace correlation + OTLP logs pipeline now

## 3. Why This Decision

### 3.1 Spans do not replace logs

Tracing answers request flow, causality, latency, and service-boundary
questions. It is not a complete substitute for debug output such as:

- container startup failures
- subprocess stderr lines
- retry loops
- health/readiness probes
- configuration and environment diagnostics
- operator-oriented failure summaries

Those belong in logs or explicit verifier artifacts, not in synthesized spans.

### 3.2 Jaeger is trace-centric, not the full debug surface

Jaeger is the correct place for distributed traces, span relationships, and
cross-service timing analysis. It is not the authoritative home for:

- general debug logs
- full-text search over operational log lines
- retained process stderr/stdout
- certifying startup diagnostics for Docker and ACP subprocess failures

Treating Jaeger as a log backend would force debug data into the wrong signal
and create a misleading operator model.

### 3.3 The repository already has a viable log surface

The codebase already emits structured JSON logs in non-interactive contexts and
uses Rich output for interactive local use. The missing corrective step is
correlation and evidence discipline, not wholesale replacement of the current
logging surface.

### 3.4 OTLP logs without a real backend would add transport, not authority

An OTLP logs pipeline is only useful when the repository also chooses:

- a log-capable backend
- retention expectations
- query and operator workflows
- verifier and production support boundaries

Adding OTLP log export now, without that backend decision, would increase
complexity while leaving the real authority question unresolved.

## 4. Authoritative Evidence Model

### 4.1 Trace authority

- Jaeger is the trace authority for gateway, worker, and any propagated
  cross-process spans.
- The primary join keys are `trace_id` and `span_id`.
- Trace evidence is required for successful production-like cross-service
  verification.

### 4.2 Log authority

- Structured process logs are the authority for operational debugging.
- In containers, stdout/stderr and captured compose logs are authoritative log
  artifacts.
- For local interactive runs, Rich/console formatting is an operator-facing
  presentation layer over the same underlying logging model.

### 4.3 Verifier authority

The production-like verifier must gather a coherent evidence bundle, not just a
 pass/fail result. That bundle must include:

- structured service logs
- Docker/container inspect and health state
- Jaeger trace query results
- explicit correlation identifiers where available

The verifier is therefore a supported **debug client and evidence collector**,
not just a smoke-test wrapper.

## 5. Required Properties Of The Logging Surface

All first-party structured log records should converge on a common minimum
shape:

- timestamp
- severity / level
- logger or service name
- message
- `trace_id` when an active span exists
- `span_id` when an active span exists
- trace flags / sampled indicator when available
- service/runtime metadata where appropriate
- operation-specific correlation fields such as `thread_id`, `dispatch_id`,
  `worker_id`, `client_id`, or provider/session identifiers

Additional rules:

- logs must remain useful when there is no active span
- correlation fields must be additive, not mandatory for emission
- log records must remain readable in container capture and local developer
  output

## 6. ACP And Subprocess Implications

This ADR does not define local-vs-Docker ACP runtime authority in full; that is
handled by the companion ACP authority ADR. It does, however, define how ACP
evidence relates to the debug surface:

- ACP subprocess stderr/stdout is log evidence, not trace authority
- the worker must log enough structured context around ACP process lifecycle to
  correlate subprocess output back to the owning request/thread/provider flow
- verifier artifacts must preserve ACP-relevant worker/container diagnostics as
  logs, not attempt to encode them into Jaeger

## 7. Consequences

### Positive

- preserves the existing successful trace setup
- aligns debugging with the correct telemetry split: traces for causality,
  logs for operational detail
- gives the verifier and Docker debugging path a clear architectural target
- avoids premature commitment to a log backend the repository has not selected

### Negative / Trade-offs

- log search and retention remain limited to the current stdout/container
  artifact model until a log backend is chosen
- cross-service debugging still depends on disciplined correlation fields being
  added to log records
- operators must currently inspect both logs and traces rather than a single
  unified backend

## 8. Rejected Alternative

### 8.1 Add OTLP logs pipeline now

Rejected for the current slice.

Reasons:

- no chosen log-capable backend
- no retention/query authority model
- no operator workflow that depends on OTLP logs today
- would add signal-export complexity before the repository fixes the more basic
  gap of missing log/trace correlation fields

This remains a valid future extension after a backend decision is made.

## 9. Relationship To ADR-010

ADR-010 remains in force for tracing and OTLP export of trace data.

This ADR extends ADR-010 by clarifying that:

- OTel traces are mandatory but not sufficient for debugging
- structured logs remain a first-class operational surface
- Jaeger is the trace authority, not the universal debug backend
- the current supported design is trace/log correlation, not trace-only
  debugging

## 10. Next Required Implementation Work

The following work is required to make this ADR real:

1. Inject OTel correlation identifiers into first-party structured logs by
   default.
2. Standardize service/runtime correlation fields across gateway, worker, and
   verifier paths.
3. Improve verifier artifact capture so logs, inspect data, and Jaeger trace
   evidence are preserved before teardown.
4. Add explicit ACP subprocess lifecycle correlation fields in worker-side
   logging.
5. Revisit OTLP logs only after selecting a log-capable backend and defining
   its operational authority.
