## Purpose

This is the implementation plan that follows the 2026-03-11 observability
architecture decision.

Its job is to turn ADR-036 and ADR-037 into a robust, production-ready trace
and debug framework without overreaching into premature backend expansion.

This plan assumes the current architectural decisions stay in force:

- Jaeger is the authoritative trace backend
- structured logs are the authoritative debug-log surface
- log/trace correlation is mandatory
- OTLP logs are deferred until a real log-capable backend is chosen
- local-native ACP and Docker-bundled ACP are separate environment-scoped
  runtime authorities

---

## Success Criteria

The implementation is good enough when all of the following are true:

1. A single request or verifier run can be followed across gateway, worker,
   ACP subprocess, and Jaeger using stable identifiers.
2. A failed `vaultspec test prodlike-docker` run yields enough pre-teardown
   evidence to classify the failure without immediate rerun.
3. Local ACP failures and Docker-bundled runtime failures are visibly
   distinguishable by evidence, not just by operator guesswork.
4. A future developer review client can consume logs and traces without
   becoming the source of truth.

---

## Non-Goals For The First Implementation Wave

- no attempt to turn Jaeger into a general-purpose log backend
- no OTLP logs pipeline in the first wave
- no custom historical observability UI as the primary authority
- no large tracing rewrite

---

## Implementation Order

### Phase 1: Structured Log Correlation Baseline

Goal:

- make structured logs useful enough to join with traces

Changes:

- add automatic OTel context injection to first-party structured logs
- expose at least:
  - `trace_id`
  - `span_id`
  - `trace_sampled` or trace-flags equivalent
  - `service_name`
- preserve existing fields and allow caller-provided extras to continue working
- keep Rich as a presentation layer only

Likely files:

- `src/vaultspec_a2a/utils/logging.py`
- `src/vaultspec_a2a/telemetry/instrumentation.py`
- related tests under `src/vaultspec_a2a/telemetry/tests/`

Verification:

- real traced request logs contain correlation ids
- no regression in JSON log output shape when no trace is active

Exit criteria:

- logs can be pivoted into Jaeger by `trace_id`

### Phase 2: Standard Correlation Schema On Service Paths

Goal:

- make correlation fields consistent on high-value runtime paths

Changes:

- standardize additional fields where applicable:
  - `thread_id`
  - `dispatch_id`
  - `worker_id`
  - `client_id`
  - `provider`
  - `runtime_mode`
  - `session_id`
- prioritize:
  - gateway dispatch paths
  - worker ingest/execution paths
  - websocket command/relay paths
  - internal event relay paths

Likely files:

- `src/vaultspec_a2a/api/app.py`
- `src/vaultspec_a2a/api/endpoints.py`
- `src/vaultspec_a2a/api/internal.py`
- `src/vaultspec_a2a/api/websocket.py`
- `src/vaultspec_a2a/worker/ipc.py`
- `src/vaultspec_a2a/worker/executor.py`

Verification:

- real request + worker execution path yields logs with both OTel ids and
  runtime correlation ids

Exit criteria:

- the main gateway-to-worker execution path is correlation-complete enough for
  practical debugging

### Phase 3: ACP Runtime And Subprocess Evidence

Goal:

- make ACP failures classifiable by runtime authority and protocol phase

Changes:

- log resolved command/runtime source at provider startup
- log subprocess lifecycle with structured fields:
  - provider
  - runtime mode
  - command source
  - pid
  - workspace root
  - session id when available
- normalize ACP stderr and malformed stdout into structured records
- classify failures by phase:
  - runtime resolution
  - spawn
  - initialize
  - session/new
  - session/prompt
  - provider auth/quota/network

Likely files:

- `src/vaultspec_a2a/providers/factory.py`
- `src/vaultspec_a2a/providers/acp_chat_model.py`
- `src/vaultspec_a2a/providers/_subprocess.py`
- `src/vaultspec_a2a/providers/probes/claude.py`
- `src/vaultspec_a2a/providers/probes/gemini.py`

Verification:

- real local probes and provider runtime paths emit structured phase-aware
  evidence

Exit criteria:

- local ACP and Docker-bundled runtime failures are no longer diagnostically
  ambiguous

### Phase 4: Verifier Evidence Capture For `#87`

Goal:

- make the prod-like verifier an evidence collector instead of a timeout
  wrapper

Changes:

- capture pre-teardown:
  - `docker compose ps`
  - `docker inspect` for key containers
  - health-state snapshots
  - repeated readiness probe results
  - effective compose config
- add a correlation manifest linking:
  - run timestamp
  - services/containers
  - thread id if created
  - trace ids discovered from Jaeger
  - artifact files with related logs
- persist provider probe stdout/stderr artifacts for
  `prodlike-provider <claude|gemini>`

Likely files:

- `src/vaultspec_a2a/cli/_verify.py`
- `src/vaultspec_a2a/cli/tests/test_test.py`
- any verifier-specific tests

Verification:

- a failing run produces enough artifacts to classify whether the fault was:
  - gateway readiness
  - worker readiness
  - Postgres dependency
  - Jaeger/export path
  - Dockerized ACP/provider runtime

Exit criteria:

- `#87` is no longer blocked by too-thin diagnostics

### Phase 5: Optional Developer Review Client

Goal:

- provide a developer-facing review surface without making it the source of
  truth

Allowed shape:

- CLI/TUI/report client that reads:
  - structured logs
  - verifier manifests
  - Jaeger traces
- client may summarize, filter, and correlate evidence for developer review

Required constraint:

- the client must remain downstream of the authoritative evidence surfaces
- it must not become the only place where evidence is preserved

Candidates:

- extend the existing Typer/Rich CLI
- add a dedicated review/report command over saved verifier artifacts

Exit criteria:

- helpful operator/developer review exists without changing the evidence model

---

## Anti-Pattern Guidance

### Forwarding general debug logs into traces for Jaeger

Default answer: yes, that is an anti-pattern.

Why:

- spans are not a replacement for logs
- Jaeger is trace-centric, not a general log backend
- free-form startup/subprocess/debug output becomes harder to search and reason
  about when forced into span events or synthetic spans

Exception:

- small, high-value span events can still be useful for critical milestones,
  but they should complement logs, not replace them

### Building a client that reads traces and logs for developer review

No, that is not an anti-pattern.

It becomes an anti-pattern only if:

- the client becomes the only place where evidence exists
- it requires inventing a second authority model
- it hides raw structured evidence behind lossy summaries

The correct pattern is:

- authoritative evidence first
- review client second

---

## Recommended Immediate Next Slice

Start with Phase 1 only.

That yields the highest leverage with the lowest blast radius:

- minimal files
- immediate value for `#87`
- no backend expansion
- no conflict with the ADR decisions

After Phase 1:

1. review the actual diff
2. update audits/queue
3. then proceed to Phase 3 or Phase 4 depending on what the real logs reveal

The likely best next implementation pass is:

- automatic correlation fields in `utils/logging.py`
- focused tests proving correlation fields appear when spans are active and do
  not break non-traced emission
