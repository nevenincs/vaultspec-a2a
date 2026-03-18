# 2026-03-12 Debugging, Trace Consistency, and Test Framework Health Audit

## Scope

**Topic:** debugging, trace consistency, and test framework health

**Audit surface:** live-test dependencies, Jaeger/LangGraph telemetry assumptions, debug-log and trace collection surfaces, and the currently observed failures across telemetry, graph execution, migrations, and ACP auth handling

**Rewrite scope:** one persistent audit/cycle-log document with triage queue entries only

## Workflow Mandate

This repository operates under a rolling audit/research/implementation cycle. Implementation does not close a finding by itself. Each implementation pass must be followed by a review pass, severity/type classification, and queue updates for every newly discovered issue or contract drift. This audit document is therefore a live queue surface, not a one-time incident note.

Completion criteria for any follow-up implementation pass:

1. Implement the targeted fix set.
2. Review the actual landed behavior.
3. Classify each surfaced issue by severity and type.
4. Persist all findings into the audit queue.
5. Treat the pass as incomplete until implementation, review, and queue updates are all done.

---

## Explicit Answers

### 1. Is Jaeger a required dependency of the live tests?

**Answer:** Jaeger is a required dependency only for the test surfaces explicitly built around real trace export verification.

That includes:

- tests marked `requires_jaeger`
- multi-service integration fixtures that wire `OTEL_EXPORTER_OTLP_ENDPOINT` to a live Jaeger backend

It is **not** a blanket requirement for all live tests, and it is **not** a blanket requirement for all LangGraph-based tests.

### 2. Are LangGraph-based tests correctly requiring Jaeger to be present?

**Answer:** The inspected LangGraph graph-execution tests do **not** require Jaeger by default, and that appears correct for their current scope.

The relevant graph-execution suite is scoped to a live VidaiMock dependency, not to trace export verification. Those tests are enforcing a live mock-provider execution path, not an observability-certification path. Requiring Jaeger there by default would conflate graph behavior verification with telemetry backend verification.

### 3. Do we have a robust uniform facade for debug logs and Jaeger traces?

**Answer:** No.

The repository has partial evidence-capture mechanisms, but no unified live diagnostics facade that:

- tails process stdout/stderr continuously
- correlates those outputs with trace activity
- exposes a single live operator-facing surface
- subscribes to any Jaeger aggregate stream

The closest existing mechanism is the verification CLI, which is **artifact-oriented**, not a live unified console. It:

- polls Jaeger over HTTP
- snapshots Docker Compose logs
- writes manifests and artifacts

That is useful evidence capture, but it is not a real-time debugging facade.

---

## Findings

### CRIT-01 — Telemetry Jaeger fixture discovery is structurally broken
**Type:** test framework / fixture topology

**Finding:** The failing telemetry test requires `jaeger_otlp_endpoint` and `jaeger_query_url`, but those fixtures are defined in a sibling `conftest.py` tree rather than an ancestor conftest visible to `src/vaultspec_a2a/telemetry/tests/`.

**Observed effect:** Pytest aborts with `fixture 'jaeger_otlp_endpoint' not found` before the test can even exercise its live Jaeger dependency.

**Why this matters:** This is not an environment-only failure. The suite currently cannot express its intended contract because fixture visibility is broken at collection/runtime setup time.

**Consequence:** The `requires_jaeger` contract for telemetry tests is partially nonfunctional. Even with Jaeger running, this test surface is presently miswired.

---

### HIGH-01 — Jaeger health contract is drifted across marker docs, hooks, and task runner comments
**Type:** docs/config drift

**Finding:** The repository advertises inconsistent Jaeger readiness semantics.

Observed drift:

- marker text references `localhost:14269`
- the fail-fast hook actually probes `http://localhost:13133/status`
- `Justfile` commentary references `14269` / `204`
- the actual command checks `13133/status` / `200`

**Why this matters:** Operators and contributors are being told different readiness contracts depending on where they look. This creates false-negative setup attempts and audit noise when tracing tests fail.

**Consequence:** Debugging time is wasted on incorrect Jaeger expectations, and the repo’s own tracing contract is internally inconsistent.

---

### HIGH-02 — Diagnostics are fragmented; no unified live facade exists
**Type:** observability / debugging ergonomics

**Finding:** The repository lacks a robust uniform surface for correlating runtime logs with traces in real time.

Existing mechanisms are split:

- subprocess fixtures pipe stdout/stderr and surface limited stderr on startup failure
- integration fixtures add request/response logging through `httpx` hooks
- verification CLI snapshots Docker logs and Jaeger query output into artifacts
- telemetry code handles propagation/export, not cross-surface debugging correlation

**Why this matters:** The current failure set spans startup readiness, external dependency reachability, trace export, and auth-subprocess behavior. Those failures are expensive to reason about when logs and trace evidence live in separate, mostly post-hoc surfaces.

**Consequence:** Diagnosis remains manual, fragmented, and dependent on ad hoc operator correlation.

---

### HIGH-03 — Core graph execution tests have a hard VidaiMock dependency and currently fail at environment bootstrap
**Type:** live-test dependency / environment readiness

**Finding:** The graph execution suite is intentionally marked `requires_vidaimock` and hard-fails when VidaiMock is unreachable at `MOCK_API_BASE` or `http://localhost:8100`.

**Observed effect:** Current failures show all three graph-execution setup paths erroring out because VidaiMock is unreachable and the suite instructs the operator to start it with `just vidaimock-up`.

**Why this matters:** This suite is not flaky in the narrow sense shown here; it is enforcing an explicit external dependency. The operational issue is that the dependency is down or absent at run time.

**Consequence:** Graph pipeline validation is blocked until the live tape-replay service is started and healthy.

---

### HIGH-04 — Migration tests have a hard Postgres dependency and currently fail at environment bootstrap
**Type:** live-test dependency / environment readiness

**Finding:** The migration suite is hard-failing because Postgres is not reachable at the configured DSN.

**Observed effect:** Multiple migration tests error at setup with connection timeout and an explicit message instructing the operator to ensure Postgres is running and `VAULTSPEC_DATABASE_URL` is correct.

**Why this matters:** These tests are certifying real database behavior, not a fake backend. The failure indicates missing runtime infrastructure rather than a subtle assertion mismatch.

**Consequence:** Migration certification is blocked until a live Postgres instance is available at the expected connection target.

---

### HIGH-05 — ACP auth failure path contains a real call-signature defect
**Type:** implementation bug / error handling

**Finding:** The ACP auth failure path raises a `TypeError` because `_raise_auth_outcome_error()` is called with a positional argument that its signature does not accept.

**Observed effect:** The intended auth failure behavior is masked by an internal `TypeError` in the recovery path after subprocess exit.

**Why this matters:** This is a concrete implementation defect, not an environmental failure. It blocks correct surfacing of the browser auth URL and corrupts the operator-facing failure mode.

**Consequence:** Auth-subprocess exits produce the wrong error and break the contract asserted by the failing test.

---

### MED-01 — Telemetry test contract mixes two Jaeger models without a single clear ownership boundary
**Type:** test architecture / contract drift

**Finding:** The repo simultaneously uses:

- local Jaeger on localhost for `requires_jaeger` gating
- testcontainer-backed Jaeger fixtures for some real integration surfaces

The telemetry test claims a live Jaeger contract and uses fixtures defined elsewhere, but the visibility boundary is not aligned with the test package layout.

**Why this matters:** The repo currently has two legitimate Jaeger models, but the boundary between them is under-documented and easy to miswire.

**Consequence:** Trace tests can fail for topology reasons even when the conceptual test design is sound.

---

### LOW-01 — Pytest collection emits warning noise around Click objects named `test`
**Type:** test hygiene / warning noise

**Finding:** Pytest emits collection warnings because a Click `test` callable is being seen during discovery and is not a function test target.

**Why this matters:** This does not currently fail the suite, but it pollutes output and reduces signal quality during already noisy debugging passes.

**Consequence:** Triage output is less clean and can bury more important setup failures.

---

## Triage Queue

### Critical
- `TRACE-TEST-001` — Fix Jaeger fixture visibility for telemetry tests.
  - Severity: Critical
  - Type: test framework / fixture topology
  - Suggested next action: move shared Jaeger fixtures to an ancestor `conftest.py`, or explicitly load them via pytest plugin/re-export so `src/vaultspec_a2a/telemetry/tests/` can resolve them.

### High
- `TRACE-CONTRACT-001` — Normalize Jaeger health endpoint/status contract across marker text, hooks, and Just targets.
  - Severity: High
  - Type: docs/config drift
  - Suggested next action: choose one authoritative readiness contract and update `pyproject.toml`, `Justfile`, and related comments/hooks to match.

- `OBS-DEBUG-001` — Design a unified diagnostics facade for live debugging.
  - Severity: High
  - Type: observability / tooling gap
  - Suggested next action: define a single operator-facing surface that can tail process stdout/stderr and correlate/poll Jaeger traces with timestamps and service identity.

- `GRAPH-LIVE-001` — Operationalize VidaiMock readiness for graph execution certification.
  - Severity: High
  - Type: live-test dependency / environment readiness
  - Suggested next action: standardize startup/readiness instructions and evidence capture for VidaiMock before graph test execution.

- `DB-LIVE-001` — Operationalize Postgres readiness for migration certification.
  - Severity: High
  - Type: live-test dependency / environment readiness
  - Suggested next action: standardize the expected Postgres startup path and DSN verification before migration test execution.

- `ACP-ERR-001` — Repair ACP auth failure-path call signature.
  - Severity: High
  - Type: implementation bug / error handling
  - Suggested next action: align `_authenticate_rpc()` failure handling with `_raise_auth_outcome_error()` signature and preserve the intended browser URL surfacing contract.

### Medium
- `TRACE-ARCH-001` — Clarify ownership boundary between localhost Jaeger gating and testcontainer Jaeger fixtures.
  - Severity: Medium
  - Type: test architecture / contract clarity
  - Suggested next action: document when each model is authoritative and prevent cross-surface fixture leakage/misassumption.

### Low
- `PYTEST-HYGIENE-001` — Eliminate Click-related collection warning noise.
  - Severity: Low
  - Type: test hygiene
  - Suggested next action: adjust discovery exposure or object naming so pytest no longer attempts to collect non-test Click callables.

---

## Current Failure Intake

### Environment/setup failures
- VidaiMock unreachable at `http://localhost:8100` for graph execution tests
- Postgres unreachable at `postgresql://postgres:postgres@127.0.0.1:5432/vaultspec` for migration tests
- telemetry test blocked on missing Jaeger fixture before live trace verification begins

### Implementation failures
- ACP auth failure path raises `TypeError` instead of the intended `AcpAuthError` path with browser URL context

### Output-quality failures
- Click collection warnings add noise during pytest output review

---

## Evidence Anchors

- Marker definitions: `pyproject.toml:86-90`
- Jaeger test targets: `Justfile:85-100`
- Shared Jaeger fixtures and fail-fast hook: `src/vaultspec_a2a/tests/conftest.py:131-197`, `src/vaultspec_a2a/tests/conftest.py:353-376`
- Telemetry test contract and missing fixtures: `src/vaultspec_a2a/telemetry/tests/test_telemetry.py:1-10`, `src/vaultspec_a2a/telemetry/tests/test_telemetry.py:443-549`
- VidaiMock gate: `src/vaultspec_a2a/core/tests/conftest.py:29-46`
- LangGraph execution suite scope: `src/vaultspec_a2a/core/tests/test_graph_execution.py`
- Verification CLI log/trace artifact capture: `src/vaultspec_a2a/cli/_verify.py:274-303`, `src/vaultspec_a2a/cli/_verify.py:331-458`, `src/vaultspec_a2a/cli/_verify.py:481-539`
- ACP auth failure implementation path: `src/vaultspec_a2a/providers/acp_chat_model.py:1428-1478`, `src/vaultspec_a2a/providers/tests/test_acp_chat_model.py:375-383`

## Status

Open. This document should be extended on each review/implementation pass with:

- new findings
- severity reclassification where warranted
- resolved items with evidence
- follow-up queue entries created by the fixes themselves
