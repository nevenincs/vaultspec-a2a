---
adr_id: 037
title: ACP Runtime Authority and Observability Boundaries
date: 2026-03-11
status: Proposed
related:
  - docs/adrs/010-observability-telemetry-integration.md
  - docs/adrs/017-containerization-strategy.md
  - docs/adrs/031-worker-process-architecture.md
  - docs/audits/2026-03-08-continuous-backend-readiness-audit.md
  - docs/research/2026-03-11-observability-debug-correlation-grounding.md
---

# ADR-037: ACP Runtime Authority and Observability Boundaries

**Date:** 2026-03-11
**Status:** Proposed

## 1. Context and Problem Statement

VaultSpec now supports two distinct ACP execution environments:

- **Local / non-Docker execution**: the worker launches ACP-capable provider
  CLIs from the host environment or project-local `node_modules`.
- **Dockerized prod-like execution**: the worker image carries bundled provider
  runtime dependencies so Linux container verification can run without relying
  on the host machine's Node.js or Gemini CLI installation.

Recent live verification proved that the local ACP bridge still works:

- Gemini local ACP completed `initialize -> session/new -> session/prompt`.
- Claude local ACP completed `initialize -> session/new` and then failed at
  `session/prompt` due to provider quota, not bridge failure.

This means Dockerized provider runtime support did **not** replace local ACP
authority. It added a second runtime surface for containerized verification and
deployment parity.

The missing architecture statement is:

- which runtime is authoritative in which environment
- what Docker does and does not replace
- which observability signals must exist at the local CLI/runtime, worker
  process, and ACP subprocess boundaries for debugging to be authoritative

Without that statement, Docker/provider failures and local ACP failures are too
easy to misclassify as the same problem.

## 2. Decision

### 2.1 Runtime authority is environment-scoped

VaultSpec adopts the following authority model:

- **Local authority**: in non-Docker flows, the authoritative ACP runtime is
  the host-resolved runtime chosen by `ProviderFactory`:
  - Claude: project-local Node entrypoint for `@zed-industries/claude-agent-acp`
  - Gemini: project-local package if present, otherwise system `gemini` on PATH
- **Docker authority**: in prod-like Docker verification, the authoritative ACP
  runtime is the runtime bundled into the worker image and configured by the
  compose stack.

These are separate supported execution environments. A Dockerized runtime is
not the source of truth for local execution, and a successful local run does
not by itself certify the Docker image.

### 2.2 Docker augments deployment parity; it does not replace the local bridge

Docker exists to provide:

- Linux-target runtime packaging
- version-pinned provider runtime dependencies inside the worker image
- repo-owned prod-like verification for gateway, worker, Postgres, and Jaeger

Docker does **not** replace:

- the local ACP subprocess model
- host/system CLI execution for local development
- the worker-owned ACP session lifecycle in ADR-031
- the need to verify provider credentials separately in the target environment

### 2.3 Worker remains the execution authority

Per ADR-031, the worker remains the sole authority for:

- ACP subprocess launch
- ACP session lifecycle
- provider runtime selection
- ACP stdout/stderr capture
- worker-to-gateway event emission about execution outcomes

The gateway does not become an ACP runtime authority in either local or Docker
mode. Docker packaging changes the worker's available executables; it does not
move ACP control into the gateway.

### 2.4 Observability authority is layered, not collapsed

The authoritative debug story must preserve three layers of evidence:

1. **Gateway / worker service telemetry**
   - OTel traces
   - structured service logs
   - container/service health and readiness state
2. **Worker-owned ACP runtime evidence**
   - resolved executable / entrypoint identity
   - working directory / workspace root
   - selected provider and model
   - environment mode (`local`, `docker`, or equivalent runtime classification)
3. **ACP subprocess evidence**
   - startup failure details
   - protocol phase reached (`initialize`, `session/new`, `session/prompt`)
   - stderr diagnostics, rate limits, auth failures, and exit conditions

No single layer replaces the others:

- traces do not replace logs
- container logs do not replace ACP protocol evidence
- ACP stderr does not replace worker and gateway spans

## 3. Consequences

### 3.1 Positive

- Local ACP success or failure can be classified independently from Docker image
  certification.
- Docker verification can be treated as a production-parity contract instead of
  an implicit replacement for host execution.
- The worker remains the single execution authority, preserving ADR-031.
- Observability work can be scoped correctly: gateway/worker correlation,
  subprocess diagnostics, and verifier evidence capture are related but not the
  same responsibility.

### 3.2 Negative / trade-offs

- There are now two supported runtime authorities to document and verify.
- Provider certification is matrix-shaped:
  - local Claude
  - local Gemini
  - Docker Claude
  - Docker Gemini
- Debugging requires correlating evidence across service, container, and
  subprocess boundaries rather than pretending one backend is sufficient.

## 4. Required observability contract

### 4.1 Local / non-Docker flows

For local ACP execution, the minimum authoritative evidence is:

- resolved command and runtime source logged by the worker at process launch
- structured worker logs for ACP session startup and failure phase
- ACP stderr capture preserved in worker logs
- OTel trace context for the worker-side request and dispatch path

### 4.2 Docker prod-like flows

For Docker verification, the minimum authoritative evidence is:

- compose service state and container health before teardown
- container logs for gateway, worker, Postgres, and Jaeger
- worker logs identifying the bundled provider runtime path actually used
- ACP stderr and protocol-phase failure evidence from the worker container
- Jaeger trace evidence for gateway and worker

### 4.3 Required classification rule

Observed failures must be classified into one of these buckets:

- local runtime resolution/configuration failure
- local provider auth/quota failure
- Docker image/runtime packaging failure
- Docker credential/materialization failure
- worker-process orchestration or readiness failure
- ACP protocol/runtime failure after successful spawn

The repository must not treat these as one undifferentiated "provider broken"
state.

## 5. Compatibility with existing ADRs

### 5.1 ADR-017

Partially superseded in practice, but still directionally relevant.

ADR-017 correctly established Docker as a production-like deployment path, but
its single-container topology language is now stale relative to the repo's
actual gateway + worker + Postgres production-like stack. This ADR does not
replace ADR-017 wholesale; it narrows the point that matters here:

- Docker packaging adds an environment-specific worker runtime authority
- Docker does not redefine local host execution as invalid or deprecated
- current runtime-authority and observability decisions must follow the actual
  multi-container worker topology, not the older single-container assumption

### 5.2 ADR-031

Compatible, with clarification.

ADR-031 makes the worker the graph and provider execution authority. This ADR
extends that decision by stating that runtime resolution authority remains in
the worker across both local and Dockerized environments.

## 6. Rejected alternatives

### 6.1 Treat Dockerized provider runtime as the global authority

Rejected. That would incorrectly mark verified local ACP behavior as
non-authoritative and would contradict the current supported local execution
path.

### 6.2 Treat local host runtime as sufficient for Docker certification

Rejected. Docker packaging exists specifically to certify the Linux-target
worker image and its bundled runtime dependencies.

### 6.3 Collapse debugging into Jaeger traces only

Rejected. Jaeger remains trace-centric. ACP subprocess failures, container
health failures, and provider stderr require structured logs and verifier
artifacts in addition to traces.

## 7. Follow-up requirements

- Add formal log/trace correlation architecture for service logs.
- Enrich worker ACP launch logs with runtime classification and resolved command
  identity.
- Improve `vaultspec test prodlike-docker` to capture pre-teardown container
  health, inspect state, and worker-owned ACP diagnostics.
- Keep Docker provider certification separate from local ACP probe results in
  the audit queue.
