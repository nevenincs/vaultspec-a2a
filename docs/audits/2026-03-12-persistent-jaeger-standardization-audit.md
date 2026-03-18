# 2026-03-12 Persistent Jaeger Standardization Audit

## Scope

**Topic:** persistent Jaeger standardization for reviewable traces across tests and production-like workflows

**Audit surface:** Jaeger task-runner surfaces, marker contracts, telemetry trace tests, shared live-test fixtures, OTLP export defaults, verifier artifact capture, compose/runtime wiring, and operator-facing reviewability of traces and service monitoring

**Rewrite scope:** one new audit document defining the current topology split, standardization recommendation, rollout coverage, and multi-pass verification requirements

## Core Drift

The codebase currently exposes **persistent local Jaeger** as the operator-facing contract, and the active reviewable test paths are now aligned on that topology:

- `requires_jaeger` and `just jaeger-up` use the fixed local review surface on `localhost`
- telemetry trace verification now writes to `http://localhost:4317` and queries `http://localhost:16686`
- the shared `service_env` live gateway/worker stack now exports to persistent local Jaeger

The critical active runtime split has been closed for telemetry and the shared live stack. Residual drift remains because the dormant `isolated_jaeger_*` fixture family still exists in the shared fixture owner and can reintroduce transient Jaeger if reused directly.

---

## Standardization Recommendation

### Primary Recommendation

Standardize **reviewable `requires_jaeger` tests** on the **persistent local Jaeger** contract only.

That means:

- fail-fast health check remains against `http://localhost:13133/status`
- OTLP export target for reviewable Jaeger tests resolves to `http://localhost:4317`
- Jaeger query target for reviewable Jaeger tests resolves to `http://localhost:16686`
- service names and query windows remain tightly scoped so traces stay inspectable after test completion
- operator instructions, verifier behavior, and test runtime behavior all point to the same persistent review surface

This best matches the repository’s current operator-facing model and the requirement that traces from tests and production-like flows should remain reviewable in the same persistent service.

### Secondary Alternative

If true isolation must remain available for CI or targeted fixture-owned tests, split the contract explicitly:

- `requires_jaeger` or `requires_jaeger_local` for persistent local reviewable Jaeger
- a separate isolated marker/fixture family for transient testcontainer Jaeger

If this alternative is used, the two paths must not share ambiguous fixture names or a shared fail-fast story. The local-reviewable path must remain the default for tests whose stated purpose is human review of traces after execution.

### Non-Preferred Direction

Retaining the current dual topology without explicit separation is not acceptable.

It causes:

- fast-fail against one Jaeger instance
- actual trace export into another Jaeger instance
- disappearing traces after teardown
- inconsistent expectations between tests, verifier, and operators

---

## Findings

### CRIT-01 — Jaeger topology split on active runtime paths is closed, but regression risk remains
**Type:** observability contract drift

**Finding:** The shared `requires_jaeger` gate probes the persistent local Jaeger at `localhost:13133/status`, and the active reviewable runtime paths now align with that contract. Telemetry trace verification and the shared `service_env` live stack both export/query against persistent local Jaeger.

**Observed consequence:** The operator-facing mismatch on active runtime paths is closed, so traces from telemetry verification and the shared live stack are now reviewable in the persistent Jaeger UI on `http://localhost:16686`.

**Why this matters:** The main standardization defect is no longer active on the current runtime path, but the contract is not fully secure until the dormant isolated fixture family is removed or fenced off.

**Queue:** `JAEGER-STANDARD-001`
- Severity: Critical
- Type: observability contract drift
- Suggested next action: keep the active path on persistent local Jaeger and remove or fence off the remaining isolated fixture family so transient Jaeger cannot be reintroduced silently.

**2026-03-12 rollout update:** Telemetry tests and the shared `service_env` live stack have now been switched to persistent local Jaeger endpoints. Residual cleanup remains until the dormant isolated fixture family in `src/vaultspec_a2a/tests/conftest.py` is removed or fenced behind an explicit isolated-marker contract.

---

### HIGH-01 — Marker and docs drift still describe inconsistent Jaeger health semantics
**Type:** docs/config drift

**Finding:** The live code path probes `13133/status`, but marker/help text and historical comments still contain stale `14269` references.

**Observed consequence:** The repository communicates conflicting readiness contracts depending on whether the operator reads marker text, task runner comments, or live fixture code.

**Why this matters:** Standardization cannot succeed while health semantics remain inconsistent. Health contract drift already caused confusion in this audit pass.

**Queue:** `JAEGER-CONTRACT-001`
- Severity: High
- Type: docs/config drift
- Suggested next action: normalize all Jaeger health references to the actual v2 contract and remove stale `14269` assumptions from the active code/documentation surface.

---

### HIGH-02 — Tactical telemetry bridge `conftest.py` repaired fixture visibility but is not final standardization
**Type:** test infrastructure stopgap

**Finding:** The telemetry package now uses a local bridge `conftest.py` to re-export shared Jaeger fixtures and the `requires_jaeger` setup hook. This repaired pytest fixture visibility, but it does not resolve the underlying topology split.

**Observed consequence:** The telemetry test package now behaves correctly at collection/setup time, but it still inherits the split between local fail-fast gating and transient trace destination.

**Why this matters:** The bridge is an implementation patch, not a final ownership model for shared Jaeger fixtures.

**Queue:** `JAEGER-FIXTURE-001`
- Severity: High
- Type: test infrastructure standardization
- Suggested next action: treat the bridge as transitional; redesign fixture ownership and endpoint semantics once the standard Jaeger topology is chosen.

---

### HIGH-03 — Diagnostics are split between persistent verifier artifacts and ad hoc test-local traces/logs
**Type:** diagnostics architecture gap

**Finding:** The verifier persists query results and logs against persistent local Jaeger and stable artifact roots, while tests still rely on a mixture of startup stderr capture, HTTP event-hook logging, and transient fixture-owned Jaeger queries.

**Observed consequence:** Logs and traces are not consistently preserved into a single operator-facing evidence surface after test runs.

**Why this matters:** Even when traces exist, there is no fully standardized route from test execution to persistent operator review. This undermines debugging and post-run analysis.

**Queue:** `JAEGER-DIAG-001`
- Severity: High
- Type: diagnostics architecture gap
- Suggested next action: align test diagnostics with the persistent Jaeger + artifact model already used by the verifier, and emit stable service names / trace identifiers into retained evidence.

---

### HIGH-04 — Persistent Jaeger currently lacks the metrics backend required for Service Performance Monitoring
**Type:** observability capability gap

**Finding:** The operator observed that the persistent Jaeger UI reports: Service Performance Monitoring requires a Prometheus-compatible time series database. Current local task-runner and compose surfaces expose Jaeger for trace collection/query, but no Prometheus-compatible metrics backend is wired into that local persistent deployment.

**Observed consequence:** The persistent local Jaeger can show traces, but it does not provide full Service Performance Monitoring capability.

**Why this matters:** “Persistent traces visible” and “persistent observability service fully usable” are currently different capability levels. If the repo intends persistent Jaeger to be the review surface for both tests and production-like workflows, the missing metrics backend is a real operational gap.

**Queue:** `JAEGER-SPM-001`
- Severity: High
- Type: observability platform gap
- Suggested next action: define whether SPM is in scope for local persistent observability. If yes, add a Prometheus-compatible metrics backend and document the required wiring. If not, document that local persistent Jaeger supports trace review only, not service-performance monitoring.

---

### MED-01 — Shared live fixture stack couples Jaeger, Postgres, and gateway/worker runtime semantics
**Type:** rollout complexity

**Finding:** The shared live fixture surface in `src/vaultspec_a2a/tests/conftest.py` couples Jaeger, Postgres, and gateway/worker runtime environment construction in one place.

**Observed consequence:** Changing only Jaeger endpoint semantics may have collateral effects on subprocess integration suites and their service environment assumptions.

**Why this matters:** Standardization cannot be treated as telemetry-test-only work. The shared live fixture owner must be audited as a multi-service surface.

**Queue:** `JAEGER-ROLL-001`
- Severity: Medium
- Type: rollout dependency
- Suggested next action: stage rollout through fixture ownership first, then integration env wiring, then telemetry tests, then verifier/doc updates.

**2026-03-12 rollout update:** The shared live stack wiring now targets the
persistent local Jaeger instance. Current consumers under
`src/vaultspec_a2a/tests/test_smoke.py` do not perform trace assertions, so the
expected impact is an observability destination change rather than a behavioral
API change. The remaining migration risk sits with any future test that assumes
`service_env` owns an isolated trace backend.

### MED-02 — Dormant isolated Jaeger fixture family can reintroduce transient topology
**Type:** observability contract regression risk

**Finding:** `isolated_jaeger_container`, `isolated_jaeger_otlp_endpoint`, and
`isolated_jaeger_query_url` still exist in the shared fixture owner even though
the active `requires_jaeger` and `service_env` paths now converge on persistent
local Jaeger.

**Observed consequence:** A future suite could accidentally reintroduce transient
Jaeger usage by importing the isolated fixtures directly, without declaring a
separate isolated-marker contract or documenting why traces are intentionally
non-persistent.

**Why this matters:** The rollout is now correct for active paths, but the old
topology can still re-enter the codebase unless the isolated fixture family is
either removed or fenced behind an explicit isolated contract.

**Queue:** `JAEGER-ISOLATED-001`
- Severity: Medium
- Type: residual rollout risk
- Suggested next action: either delete the isolated fixture family or move it
  behind an explicit isolated marker/owner so future tests cannot silently
  bypass the persistent review contract.

---

## Rollout Coverage

### Workstream 1 — Contract normalization
Files:
- `pyproject.toml`
- `Justfile`
- `src/vaultspec_a2a/telemetry/tests/test_telemetry.py`
- `src/vaultspec_a2a/tests/conftest.py`
- `src/vaultspec_a2a/telemetry/tests/conftest.py`

Order:
1. Normalize health endpoint/status contract and active wording.
2. Define the authoritative meaning of `requires_jaeger`.
3. Decide whether the persistent local Jaeger path is the default reviewable contract.

### Workstream 2 — Fixture ownership and endpoint semantics
Files:
- `src/vaultspec_a2a/tests/conftest.py`
- `src/vaultspec_a2a/telemetry/tests/conftest.py`
- `src/vaultspec_a2a/telemetry/tests/test_telemetry.py`

Order:
1. Separate persistent-local Jaeger semantics from transient testcontainer semantics.
2. Rework fixture names or marker families to remove ambiguity.
3. Remove or deprecate transitional bridge assumptions once the final fixture owner is in place.

Rollout state:
- telemetry Jaeger verification and the shared `service_env` path are already migrated to persistent local Jaeger
- remaining fixture work is removal or fencing of the dormant isolated Jaeger family, not active-path rewiring

### Workstream 3 — Runtime export-path convergence
Files:
- `src/vaultspec_a2a/telemetry/instrumentation.py`
- `src/vaultspec_a2a/api/app.py`
- `src/vaultspec_a2a/worker/app.py`
- `src/vaultspec_a2a/api/websocket.py`
- `docker-compose.prod.yml`
- `docker-compose.prod.postgres.yml`
- `docker-compose.integration.yml`

Order:
1. Verify OTLP defaults and compose/runtime wiring match the chosen persistent-local contract.
2. Verify service names remain distinct and reviewable.
3. Verify no test/runtime path silently overrides the intended persistent Jaeger destination.

### Workstream 4 — Operator diagnostics and retained evidence
Files:
- `src/vaultspec_a2a/cli/_verify.py`
- `src/vaultspec_a2a/cli/tests/test_verify.py`
- `.vault/runtime/verify-prodlike-docker/*` artifact contract
- relevant test fixture logging surfaces

Order:
1. Align verifier assumptions with the standardized Jaeger topology.
2. Ensure trace IDs, service names, and query URLs are retained in artifacts.
3. Ensure test logs and persistent traces are reviewable after execution without transient container discovery.

### Workstream 5 — Persistent observability capability uplift
Files:
- `Justfile`
- local/persistent Jaeger deployment wiring
- compose/runtime docs
- any future metrics backend configuration surface

Order:
1. Decide whether local persistent Jaeger is trace-only or trace-plus-SPM.
2. If SPM is required, add Prometheus-compatible metrics backend wiring.
3. Update docs and operator expectations accordingly.

---

## Multi-Pass Verification Plan

### Pass 1 — Contract surface verification
Verify all active `requires_jaeger` text and helper comments point to the same persistent local Jaeger contract.
Surface:
- `pyproject.toml`
- `Justfile`
- telemetry test docstrings
- shared fixture docstrings

### Pass 2 — Fixture topology verification
Verify every Jaeger fixture consumed by reviewable tests resolves to the intended persistent-local endpoint family.
Surface:
- `src/vaultspec_a2a/tests/conftest.py`
- `src/vaultspec_a2a/telemetry/tests/conftest.py`
- telemetry Jaeger tests

### Pass 3 — Runtime export-path verification
Verify that reviewable Jaeger tests, gateway/worker subprocesses, and OTLP defaults all export to the same persistent destination under the chosen contract.
Surface:
- telemetry instrumentation
- service env fixture wiring
- compose/runtime OTLP configuration

### Pass 4 — Operator reviewability verification
Verify a human can:
1. start persistent Jaeger
2. run the relevant test
3. open `http://localhost:16686`
4. see the expected service
5. inspect the resulting trace after the run

This pass is mandatory because the current defect is fundamentally about operator reviewability, not just test pass/fail.

Immediate verification ask for this slice:
1. rerun `src/vaultspec_a2a/telemetry/tests/test_telemetry.py::test_worker_middleware_extracts_incoming_traceparent`
2. rerun one shared live-stack suite, preferably `src/vaultspec_a2a/tests/test_smoke.py`

### Pass 5 — Diagnostics retention verification
Verify that stdout/stderr evidence, trace queries, trace IDs, and service names are retained in a stable evidence surface rather than depending on transient mapped ports.

### Pass 6 — Cross-module regression verification
Audit all modules that set, default, or assume Jaeger OTLP/query paths so no remaining path silently targets a different topology.
Surface:
- `telemetry/instrumentation.py`
- `tests/conftest.py`
- verifier
- compose files
- docs/audits/research trail

### Pass 7 — Persistent observability capability verification
If SPM is declared in scope, verify that the persistent Jaeger deployment includes the Prometheus-compatible metrics backend required for service-performance views. If not in scope, verify the limitation is documented clearly.

### Pass 8 — User-run validation cycles
Require at least two explicit user-run validation cycles:
1. Jaeger absent: confirm hard fail-fast remains clear and correct
2. Jaeger present: confirm traces are persisted into the intended local review surface and remain inspectable after test completion

Current slice:
1. mandatory: telemetry Jaeger verification against persistent local Jaeger
2. mandatory: one shared live-stack consumer against persistent local Jaeger
3. optional: broader live durability validation if trace review is desired there

---

## Evidence Anchors

### Persistent local Jaeger contract
- `Justfile:85-100`
- `src/vaultspec_a2a/cli/_verify.py:32`
- `src/vaultspec_a2a/telemetry/instrumentation.py:22`
- `src/vaultspec_a2a/telemetry/instrumentation.py:61`
- `docker-compose.prod.yml`
- `docker-compose.prod.postgres.yml`
- `docker-compose.integration.yml`

### Shared testcontainer Jaeger fixtures and local fail-fast gate
- `src/vaultspec_a2a/tests/conftest.py:88-197`
- `src/vaultspec_a2a/tests/conftest.py:305-345`
- `src/vaultspec_a2a/tests/conftest.py:353-376`
- `src/vaultspec_a2a/tests/conftest.py:663`

### Telemetry-specific split and tactical bridge
- `src/vaultspec_a2a/telemetry/tests/test_telemetry.py:1-10`
- `src/vaultspec_a2a/telemetry/tests/test_telemetry.py:443-549`
- `src/vaultspec_a2a/telemetry/tests/conftest.py:1-21`

### Operator-facing diagnostics persistence
- `src/vaultspec_a2a/cli/_verify.py:259-303`
- `src/vaultspec_a2a/cli/_verify.py:331-458`
- `src/vaultspec_a2a/cli/_verify.py:481-539`
- `src/vaultspec_a2a/cli/_verify.py:572-808`
- `src/vaultspec_a2a/cli/tests/test_verify.py:249-330`

### Existing audit/research trail
- `docs/audits/2026-03-12-debugging-trace-consistency-audit.md`
- `docs/audits/2026-03-08-continuous-backend-readiness-audit.md:1197-1202`
- `docs/audits/2026-03-07-justfile-cli-audit.md:118`
- `docs/research/2026-03-08-integration-testing-stack.md`
- `docs/research/2026-03-11-observability-debug-correlation-grounding.md`
- `docs/adrs/017-containerization-strategy.md`
- `docs/adrs/016-task-runner-dev-bootstrap.md`

### Operator-observed new issue
- Local persistent Jaeger UI reports that Service Performance Monitoring requires a Prometheus-compatible time series database
- Current local task-runner and compose surfaces presented in this audit show Jaeger trace wiring, but no Prometheus-compatible metrics backend wiring in the active persistent-local operator path

---

## Recommended Queue

- `JAEGER-STANDARD-001` — Converge reviewable Jaeger tests onto persistent local Jaeger or explicitly split local vs isolated marker families.
- `JAEGER-CONTRACT-001` — Normalize health endpoint/status semantics across markers, task runner, and fixture documentation.
- `JAEGER-FIXTURE-001` — Replace the tactical telemetry bridge with final standardized fixture ownership.
- `JAEGER-DIAG-001` — Unify persistent trace review and retained diagnostics between tests and verifier artifacts.
- `JAEGER-SPM-001` — Decide whether local persistent Jaeger must support Service Performance Monitoring; if yes, add Prometheus-compatible metrics backend wiring.
- `JAEGER-ISOLATED-001` — Remove or fence off the dormant isolated Jaeger fixture family so transient Jaeger cannot be reintroduced accidentally.
- `JAEGER-ROLL-001` — Execute rollout in ordered stages across fixture ownership, runtime wiring, verifier alignment, and docs.
- `JAEGER-VERIFY-001` — Require multi-pass user-run validation for absent/present Jaeger states and post-run UI reviewability.

## Status

Open. This audit should remain active until the repository satisfies all of the following at the same time:

- `requires_jaeger` means one unambiguous persistent review contract
- traces from reviewable Jaeger tests remain visible in the persistent local Jaeger after the run
- verifier and tests point to the same review surface
- health/docs wording is normalized
- any declared SPM requirement is either implemented with a Prometheus-compatible backend or explicitly documented as out of scope

Current rollout state:

- telemetry trace verification writes to persistent local Jaeger
- the shared `service_env` live gateway/worker stack writes to persistent local Jaeger
- the isolated Jaeger fixture family is no longer on the active path, but still
  exists as cleanup debt
- `requires_jaeger` continues to hard-fail at `http://localhost:13133/status`
- the local SPM backend decision remains open
