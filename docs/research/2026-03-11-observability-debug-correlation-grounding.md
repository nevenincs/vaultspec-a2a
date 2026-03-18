# 2026-03-11 Observability Debug + Trace Correlation Grounding

## Scope

Grounding for:

- `#88` OBS-ARCH-01: formal log/trace correlation architecture and authoritative
  multi-service debugging surface
- `#89` ACP-ARCH-01: local ACP vs Dockerized provider runtime authority and
  observability boundaries

This document intentionally precedes implementation. The current need is not
another verifier patch in isolation; it is a coherent debugging architecture
for gateway, worker, Docker runtime, and ACP subprocess boundaries.

---

## Current repo state

### What is already true

- Real distributed tracing exists and is already useful.
  - `src/vaultspec_a2a/telemetry/instrumentation.py` configures OTel traces and
    metrics with separate `service.name` attribution.
  - `src/vaultspec_a2a/telemetry/middleware.py` manually creates HTTP server
    spans and injects/extracts W3C trace context.
  - `src/vaultspec_a2a/api/websocket.py` already injects trace context into
    outgoing WebSocket payloads via `_trace.traceparent` / `tracestate`.
- Jaeger is already the active trace backend in the repo-owned Docker flows.
  - `docker-compose.prod.yml` exports OTLP to Jaeger on `http://jaeger:4317`.
  - `src/vaultspec_a2a/cli/_verify.py` queries Jaeger directly through
    `/api/traces`.
- Structured logging already exists.
  - `src/vaultspec_a2a/utils/logging.py` emits JSON logs in non-interactive or
    production-shaped contexts.
  - The same module uses Rich terminal logging in interactive local dev.
- Local ACP authority still works.
  - Local Gemini ACP was previously verified end to end.
  - Local Claude ACP reached `initialize` and `session/new`; its failing
    `session/prompt` was provider quota, not bridge startup failure.
- Dockerized provider runtime now exists as an explicit supported runtime path.
  - `src/vaultspec_a2a/providers/factory.py` resolves Gemini differently in
    Docker by preferring the bundled package entrypoint under Node.
  - `docker-compose.prod.providers.yml` passes explicit provider auth material
    into the worker container for certifying provider runs.

### What is still missing

- The JSON logger does not inject OTel correlation identifiers by default.
  - `src/vaultspec_a2a/utils/logging.py` includes explicit `extra={...}` fields
    but does not attach `trace_id`, `span_id`, or sampling state automatically.
- Telemetry setup is trace-and-metrics only at present.
  - `src/vaultspec_a2a/telemetry/instrumentation.py` configures trace and
    metric exporters only; there is no log pipeline or logging bridge.
- ACP subprocess diagnostics are present only as loose stderr text.
  - `src/vaultspec_a2a/providers/acp_chat_model.py` logs stderr as
    `ACP STDERR: ...` lines, but without a durable subprocess/session/debug
    envelope that can be correlated across services.
- The prod-like verifier captures traces and logs as separate artifacts but
  does not yet create one authoritative diagnostic record.
  - `src/vaultspec_a2a/cli/_verify.py` persists `compose ps`, per-service logs,
    Jaeger trace payloads, and failure JSON, but correlation across those
    artifacts is still manual and weak.
- There is no ADR yet that states:
  - what the authoritative debug surface is,
  - whether logs remain structured stdout/container logs only,
  - whether OTLP logs are in scope now or later,
  - what authority local CLI, system-installed runtime, bundled Docker runtime,
    worker process, and ACP subprocess each hold.

---

## Official-source grounding

### OpenTelemetry Python

Context7 grounding for OpenTelemetry Python confirms:

- Python has a real logs SDK and OTLP log exporter support.
- OTel log records can carry current trace context automatically when emitted
  through the OTel logging bridge or handler.
- The Python logging bridge includes `trace_id`, `span_id`, and `trace_flags`
  in translated OTel log records when current context exists.

Implication:

- The repo does not need to invent its own correlation model. The correct shape
  is to expose trace correlation fields on log records and keep them aligned
  with OTel context.

### OpenTelemetry specification

Context7 grounding for the OTel specification confirms:

- the logs data model explicitly includes `TraceId`, `SpanId`, and
  `TraceFlags`,
- `SpanId` implies `TraceId` should also be present,
- logs remain their own signal with body, severity, timestamp, attributes, and
  resource identity.

Implication:

- correlation is a first-class logs concern, not an ad hoc repo-specific
  convention.
- the spec supports attaching trace identity to logs, not replacing logs with
  spans.

### Jaeger

Context7 grounding for Jaeger confirms:

- Jaeger is a distributed tracing system centered on ingesting, storing,
  querying, and visualizing traces,
- the query surface is trace-centric: services, operations, traces, spans,
  storage-backed search,
- Jaeger v2 is built on an OTel collector-style pipeline for tracing.

Implication:

- Jaeger is the right trace evidence backend for this repo.
- Jaeger is not, by itself, the authoritative backend for arbitrary debug logs.

---

## Current code-path grounding

### Logging surface

`src/vaultspec_a2a/utils/logging.py`

- JSON logging already normalizes common fields:
  - `timestamp`
  - `level`
  - `name`
  - `message`
- extra fields pass through cleanly.
- correlation today depends on each caller remembering to attach fields
  manually.
- there is no automatic OTel log correlation filter/formatter layer.

Conclusion:

- the current logger is structurally compatible with correlation, but it is not
  yet authoritative for cross-service debugging because required identifiers are
  optional and inconsistent.

### Trace surface

`src/vaultspec_a2a/telemetry/instrumentation.py`

- OTel resource identity is already set with `service.name` and
  `service.version`.
- trace and metric exporters are configured.
- there is no log exporter or log provider wiring.
- the module explicitly treats runtime restart as the configuration boundary,
  which fits observability infrastructure decisions well.

Conclusion:

- trace infrastructure is mature enough to anchor a correlation model.
- adding automatic log correlation is a bounded extension.
- adding OTLP logs now would be a real architectural expansion, not a trivial
  toggle.

### WebSocket and request context surface

`src/vaultspec_a2a/telemetry/middleware.py`
`src/vaultspec_a2a/api/websocket.py`

- HTTP requests already extract and continue W3C trace context.
- WebSocket events already inject `_trace` metadata into outgoing frames.

Conclusion:

- the repo already accepts that traces must cross transport boundaries.
- logs are now the missing half of the debugging story.

### Verifier evidence surface

`src/vaultspec_a2a/cli/_verify.py`

- the verifier currently proves:
  - health,
  - thread create/state flow,
  - Jaeger traces for `vaultspec-a2a` and `vaultspec-worker`,
  - captured compose logs and Jaeger query results.
- but it currently lacks:
  - container inspect / health-state capture before teardown,
  - a normalized evidence manifest joining logs and traces by correlation id,
  - any ACP/runtime-specific debug capture beyond whatever falls into worker
    logs.

Conclusion:

- `#87` is real, but it should be solved under the debug-surface architecture
  chosen for `#88`, not as an isolated artifact-dumping patch.

### ACP runtime boundary

`src/vaultspec_a2a/providers/factory.py`
`src/vaultspec_a2a/providers/acp_chat_model.py`
`src/vaultspec_a2a/providers/_subprocess.py`

- provider command resolution is already authority-aware:
  - Claude local path: project-bundled `claude-agent-acp` entrypoint
  - Gemini Docker path: bundled `/usr/local/lib/node_modules/.../dist/index.js`
  - Gemini local path: local package if present, otherwise system `gemini`
- the ACP session layer owns:
  - env preparation,
  - subprocess spawn,
  - stderr read loop,
  - stdout JSON-RPC parse loop,
  - session lifecycle and termination.
- subprocess diagnostics are currently emitted as generic service logs:
  - malformed stdout lines,
  - `ACP STDERR: ...`,
  - background RPC failures,
  - auth/session/prompt failures as exceptions.

Conclusion:

- the ACP layer is already the authority for subprocess protocol truth.
- the repo lacks a formal statement of how that truth should be observed and
  correlated across:
  - local system runtime,
  - worker service runtime,
  - Docker-bundled runtime,
  - external provider failure.

---

## Architecture options

### Option A: structured logs + trace correlation only

Definition:

- keep Jaeger as the trace backend,
- keep logs as structured JSON/stdout or Rich-local console output,
- require automatic `trace_id` / `span_id` / sampled flag correlation on all
  service-owned log records,
- improve verifier artifacts and ACP diagnostics around those identifiers,
- do not add OTLP logs export yet.

Pros:

- matches the current repo shape with the smallest architectural jump,
- aligns with OTel guidance that logs and traces are separate signals but
  correlatable,
- avoids pretending Jaeger is a general log backend,
- keeps Docker and local runs debuggable even without a separate log platform,
- provides a direct path to fix `#87` by enriching logs and verifier artifacts.

Cons:

- durable multi-run log search remains external to the repo,
- operators still rely on container logs/filesystem artifacts rather than a
  true centralized log store.

### Option B: structured logs + trace correlation + OTLP logs pipeline now

Definition:

- add OTel logs SDK/export path immediately,
- route logs through OTLP to a log-capable backend in addition to traces.

Pros:

- stronger future production observability story,
- cleaner separation between operator UI and backend storage.

Cons:

- the repo does not currently ship a log-capable backend alongside Jaeger,
- adding OTLP log export without a real destination risks dead configuration
  drift,
- increases architecture scope before the basic debug authority is documented,
- does not remove the need for local/container structured logs anyway.

### Rejected option: route generic debug output into spans / Jaeger only

Rejected because:

- the OTel data model already treats logs as a distinct signal,
- Jaeger is trace-centric,
- ACP stderr, container startup diagnostics, and other free-form debug evidence
  are not well represented as spans.

---

## Recommended direction

Choose **Option A now**:

- Jaeger remains the authoritative trace backend.
- Structured logs remain the authoritative debug-log surface.
- Every service-owned log record should automatically carry:
  - `trace_id`
  - `span_id`
  - `trace_sampled` or equivalent trace-flags exposure
  - existing structured context like `thread_id`, `dispatch_id`, `worker_id`,
    `provider`, `session_id`, `client_id`, and container/service identity where
    applicable
- OTLP logs should stay an explicit future extension, not part of the immediate
  architecture, until the repo chooses a real log-capable backend and collector
  flow.

Why this is the right decision now:

- it is fully supported by the OTel logs data model,
- it respects Jaeger’s trace-centric role,
- it matches the repo’s current operational shape,
- it gives `#87` a credible path to closure without overdesign,
- it lets the repo formalize ACP observability boundaries without conflating
  provider protocol output with tracing backends.

---

## ACP local-vs-Docker authority analysis

### Grounded current authority model

The repo currently has four distinct runtime authorities:

1. **Local system runtime authority**
   - Used in non-Docker local execution.
   - Gemini may resolve to a system-installed `gemini` CLI.
   - Claude ultimately depends on the locally available Node + project package
     path and may also depend on a system `claude` executable for some flows.

2. **Project-bundled local runtime authority**
   - Used when provider entrypoints are present under project `node_modules`.
   - This is the preferred local reproducibility surface when available.

3. **Bundled Docker worker runtime authority**
   - Used in prod-like container verification.
   - The container image owns the exact Node/Gemini package runtime available to
     ACP-backed providers.

4. **ACP subprocess authority**
   - Regardless of where the executable came from, the subprocess is the final
     runtime authority for:
     - protocol handshake,
     - session lifecycle,
     - prompt execution,
     - stderr/stdout protocol diagnostics.

### What Docker does and does not replace

Dockerized provider runtime:

- **does replace** local host package resolution during container verification,
- **does not replace** the local ACP bridge architecture for non-Docker runs,
- **does not prove** provider account health or quota by itself,
- **does not make Jaeger or service logs authoritative for subprocess truth;
  those remain secondary evidence unless correlated back to ACP session facts**.

### Recommended authority statement

- For local non-Docker operation, the authoritative provider runtime is the
  resolved local runtime path chosen by `ProviderFactory`.
- For prod-like Docker verification, the authoritative provider runtime is the
  worker image’s bundled runtime and explicit provider-auth overlay.
- In both cases, the authoritative protocol truth for a provider invocation is
  the ACP subprocess session surface owned by `AcpChatModel`.
- Provider quota/auth/network failures must not be misclassified as bridge or
  container-runtime failures without ACP-session evidence.

---

## Observability boundary requirements

To make the above authority model operationally useful, the repo needs one
consistent evidence contract across boundaries.

### Service-level evidence

Gateway and worker logs should be able to answer:

- which request or dispatch this log belongs to,
- which trace/span it belongs to,
- which thread/provider/session/worker generated it,
- whether the log came from local runtime or Dockerized runtime.

### ACP subprocess evidence

ACP logs should distinguish at least:

- `provider`
- resolved command / runtime kind (`local-project`, `local-system`,
  `docker-bundled`, `binary-experimental`)
- `session_id` once known
- `thread_id` / `dispatch_id` when available
- stderr vs stdout protocol parse failures
- auth/session/prompt failure phase

### Verifier evidence

The prod-like verifier should capture, before teardown:

- compose ps output,
- container health/inspect state,
- per-service logs,
- Jaeger trace queries,
- a manifest linking trace-bearing services and key correlation ids,
- any ACP/provider probe outputs relevant to the failure.

The verifier should not claim one artifact type is sufficient on its own.

---

## Concrete follow-up slices

### Slice 1: ADRs before runtime mutation

- add an ADR for the authoritative debug evidence model:
  - Jaeger for traces
  - structured logs for debug authority
  - required correlation fields
  - OTLP logs deferred until a real backend exists
- add an ADR for ACP/runtime authority:
  - local vs Docker runtime authority
  - ACP subprocess truth boundary
  - required observability surfaces

### Slice 2: bounded implementation for `#88`

- add automatic OTel correlation fields to the structured logger
- define a stable logging schema for:
  - `thread_id`
  - `dispatch_id`
  - `worker_id`
  - `provider`
  - `session_id`
  - `trace_id`
  - `span_id`
  - `trace_sampled`
- keep Rich as an operator-facing local console formatter, not as an
  authoritative storage backend

### Slice 3: ACP observability hardening for `#89`

- normalize ACP stderr/stdout/session lifecycle logs around the same structured
  correlation fields
- explicitly log runtime resolution mode in provider startup paths
- classify failures by authority boundary:
  - runtime resolution/config
  - subprocess spawn
  - protocol initialize/session/new/session/prompt
  - provider auth/quota/network

### Slice 4: verifier hardening for `#87`

- capture container inspect / health data before teardown
- record correlation ids surfaced during the failing run
- emit a concise failure manifest that points operators from:
  - failed health
  - to relevant service logs
  - to relevant traces
  - to ACP/provider evidence where applicable

---

## Final recommendation

The next architecture pass should formalize:

1. **Jaeger is the authoritative trace backend, not the general debug backend.**
2. **Structured logs are the authoritative debug-log surface.**
3. **Trace/log correlation via `trace_id` and `span_id` is mandatory.**
4. **OTLP logs are deferred until the repo chooses a real log-capable backend.**
5. **Local ACP authority remains intact outside Docker; Dockerized provider
   runtime is an explicit verification/runtime mode, not a replacement for the
   local bridge architecture.**
6. **ACP subprocess sessions are the authoritative provider-protocol truth
   surface and must be observed as such.**

That is the minimum architecture needed to make future Docker/provider failures
diagnosable without conflating traces, logs, container health, and ACP protocol
state.

---

## Sources used for this grounding

- OpenTelemetry Python docs via Context7:
  `/websites/opentelemetry-python_readthedocs_io_en_stable`
- OpenTelemetry specification via Context7:
  `/open-telemetry/opentelemetry-specification`
- Jaeger docs via Context7:
  `/jaegertracing/jaeger`
- Repo code paths:
  - `src/vaultspec_a2a/utils/logging.py`
  - `src/vaultspec_a2a/telemetry/instrumentation.py`
  - `src/vaultspec_a2a/telemetry/middleware.py`
  - `src/vaultspec_a2a/api/websocket.py`
  - `src/vaultspec_a2a/cli/_verify.py`
  - `src/vaultspec_a2a/providers/factory.py`
  - `src/vaultspec_a2a/providers/acp_chat_model.py`
  - `src/vaultspec_a2a/providers/_subprocess.py`
  - `docker-compose.prod.yml`
  - `docker-compose.prod.postgres.yml`
  - `docker-compose.prod.providers.yml`
