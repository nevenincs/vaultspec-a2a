# Backend Readiness Execution Plan — 2026-03-09

## Purpose

This plan replaces the stale sprint framing around backend production
readiness. It is the execution document for the next audit/research/
implementation cycle after the durable orchestration pass.

The operating rule is:

1. implement a slice
2. review the actual implementation
3. add new findings to the audit queue
4. re-plan from the updated audit truth

This document therefore focuses on the remaining gaps that are still open after
the recent durability work, plus the phased Postgres production path that has
been repeatedly referenced but not yet owned as an execution track.

---

## Inputs

- `docs/audits/2026-03-08-continuous-backend-readiness-audit.md`
- `docs/audits/2026-03-08-prod-readiness-consolidated-audit.md`
- `docs/audits/2026-03-08-test-suite-mock-violations-audit.md`
- `docs/plans/2026-03-08-integration-testing-plan.md`
- 2026-03-09 orchestration durability implementation review

---

## Current State

### Closed or materially improved

- Durable workflow lifecycle now represents paused, cancelling, and repair
  states.
- Durable control-action and permission-request journals exist.
- Snapshot degradation is explicit instead of silently returning false-empty
  state.
- Startup reconciliation exists and persists repair outcomes.

### Still open

- Live recovery tests still prove process recovery more than workflow repair.
- Checkpoint projection is still `channel_values`-centric.
- The orphaned `created` lifecycle value still exists.
- Plan approval still uses the lossy `plan_approved` boolean.
- Partial/skipped test-cleanup work has not been re-promoted consistently.
- Docker/prod-like and Postgres production tracks remain incomplete.

---

## Execution Tracks

## Track 1: Audit Loop Discipline

### Goal

Make the audit/research/implementation cycle explicit in the repo workflow.

### Tasks

- `#71` Re-run code review after each implementation slice.
- Sync new findings into the continuous audit and consolidated task queue.
- Stop treating partial implementation as equivalent to closure.

### Deliverables

- Audit docs updated in the same pass as code changes.
- Queue refresh after every implementation slice.

---

## Track 2: Repair Semantics Closure

### Goal

Close the remaining restart-repair correctness gaps that were only partially
addressed by the durability pass.

### Tasks

- `#69` Remove or formally redefine `created`.
- `#68` Expand checkpoint projection into a repair-aware model.
- `#70` Replace `plan_approved` boolean with durable approval-state linkage.

### Required outcomes

- No orphaned runtime lifecycle values remain in the durable state machine.
- Gateway can distinguish business state from interrupt/control/repair state.
- Human approval is represented as a durable blocked-state record, not as a
  single lifetime boolean.

### Notes

- This track should not wait on Postgres. It applies to SQLite and Postgres
  equally.

---

## Track 3: Live Workflow Recovery Verification

### Goal

Prove repair behavior against real gateway+worker processes, not just unit/API
tests.

### Tasks

- `#67` Add live restart/recovery tests for pre-existing threads.
- `#35` Complete IPC + heartbeat integration coverage.
- `#36` Complete MCP end-to-end coverage against the live stack.

### Required live scenarios

- restart with a pre-existing `input_required` thread
- restart with a pre-existing `running` thread
- restart with a pre-existing `cancelling` thread
- duplicate permission response after restart
- cancel vs resume race across restart boundary
- degraded snapshot surfaced explicitly on checkpoint-read failure

### Gate expectation

- These suites become part of the required backend readiness path once stable.

---

## Track 4: Existing Partial / Skipped Test Work

### Goal

Finish the cleanup work that was left partial, skipped, or implicitly deferred.

### Tasks

- `#56` Finish the mock-removal mandate for API-side testing.
- `#57` Remove MCP server test mocks.
- `#58` Remove `unittest.mock` usage from `core/tests/test_graph.py`.
- `#59` Remove worker `MockTransport` usage.
- `#60` Replace remaining skip-based policy drift with hard-fail semantics.
- `#64` Remove executor test stubs.
- `#66` Remove `MemorySaver` usage from supervisor tests.

### Required outcomes

- Test policy matches the repo mandate: no hidden skips for critical paths.
- Backend verification path exercises real components where orchestration
  guarantees are claimed.

---

## Track 5: Docker and Operational Robustness

### Goal

Close the known operational gaps that still block a credible prod-like stack.

### Tasks

- `#41` Docker restart/healthcheck/service dependency fixes.
- Existing consolidated audit Phase 2 items:
  - worker 429 handling
  - circuit-breaker exemptions for cancel/resume
  - prod compose environment hardening
  - CLI endpoint alignment
  - internal WS environment-aware auth

### Required outcomes

- Gateway readiness reflects real dependency readiness.
- Cancel/resume remain available during worker distress where policy allows.
- Compose files stop depending on accidental development defaults.

---

## Track 6: Phased Postgres Production Path

### Goal

Turn Postgres from a recurring research assumption into an executable delivery
program.

## Phase PG-A: SQLite Hardening and Abstraction

### Tasks

- `#72` Introduce backend selection seams for:
  - app database engine/session factory
  - checkpointer factory
- Keep SQLite as the local default.
- Make SQLite operational limits explicit in health/readiness and docs.

### Required outcomes

- No flag day migration.
- Local development keeps the current low-friction path.

## Phase PG-B: Postgres App DB and Checkpoint Path

### Tasks

- `#73` Add config and factories for:
  - `VAULTSPEC_DATABASE_BACKEND=sqlite|postgres`
  - `VAULTSPEC_CHECKPOINT_BACKEND=sqlite|postgres`
- Add Postgres-backed app DB session setup.
- Add Postgres-backed LangGraph checkpoint factory.
- Add startup fail-fast behavior when Postgres is required but unavailable.

### Required outcomes

- Production can run on a supported multi-container persistence backend.
- Health/readiness surfaces explicit dependency failures.

## Phase PG-C: Prod-like Verification

### Tasks

- `#74` Add staged Docker/Postgres verification.
- Cover:
  - migrations
  - readiness
  - gateway + worker + persistence startup
  - create / pause / resume / cancel / reconnect path

### Required outcomes

- SQLite remains the local/dev default.
- Postgres becomes the explicit production path once validated.

---

## Recommended Order

1. Track 1: keep the audit loop honest while work resumes.
2. Track 2: finish the open repair-model gaps.
3. Track 3: add live workflow recovery verification.
4. Track 4: finish partial/skipped test cleanup so the verification surface is
   credible.
5. Track 5: close Docker and operational robustness gaps.
6. Track 6: execute the phased Postgres program.

---

## Exit Criteria For This Plan

- Open repair-model findings from the current continuous audit are either fixed
  or explicitly re-scoped with fresh findings.
- The active queue includes all partial/skipped work that still matters.
- A phased Postgres path exists in code, config, Docker, and verification, not
  just in research or architecture prose.
- Every implementation slice is followed by code review and audit queue sync.
