# Backend Readiness Execution Plan — Refresh After Repair and Postgres Closeout

## Purpose

This is the refreshed active execution plan after the major repair-model,
live-recovery, and Postgres prod-like verification tracks were completed.

The old plan is now stale because the following are no longer open:

- repair-model closure (`#67`, `#68`, `#69`, `#70`, `#84`)
- live workflow recovery and reconnect verification (`#35`, `#36`, `#67`,
  `#76`, `#78`, `#79`, `#80`)
- most no-doubles cleanup (`#57`, `#58`, `#59`, `#60`, `#64`, `#66`, `#81`,
  `#82`, `#83`)
- Postgres runtime/readiness and prod-like verification (`#73`, `#74`)

This plan now tracks only the remaining backend-readiness work that still needs
execution.

---

## Grounding Inputs

- `docs/audits/2026-03-08-continuous-backend-readiness-audit.md`
- `docs/audits/2026-03-08-prod-readiness-consolidated-audit.md`
- `docs/audits/2026-03-08-test-suite-mock-violations-audit.md`
- `docs/research/2026-03-09-postgres-persistence-grounding.md`
- `docs/audits/2026-03-10-postgres-dual-backend-audit.md`
- `docs/adrs/011-frontend-backend-contract.md`
- `docs/adrs/031-worker-process-architecture.md`
- `docs/adrs/035-postgres-dual-backend.md`

---

## Locked Workflow Rules

Every slice must still follow the same repo/user mandate:

1. Ground the slice first.
   - Use Context7 or official docs when library/runtime behavior is involved.
   - For repo-planning slices, ground against the audit/research/ADR trail and
     the actual open queue.
2. Implement the slice.
3. Verify the slice.
4. Review the actual diff and classify findings.
5. Update the research log, continuous audit, and consolidated queue.

No code-written-only closure.

---

## Current Open Queue

### Still open

- `#71` AUDIT-LOOP-01: re-run review and sync findings after each slice — `Pending`

### Recently closed (2026-03-11)

- `#41` Docker restart/healthcheck/service dependency fixes — `FIXED`
  - dev.yml gateway `depends_on` upgraded from bare list item to `service_healthy`
  - integration.yml gateway→worker changed from `service_started` → `service_healthy`
- `#42` WS-G01 / APP-N03: phantom thread / missing 404 guard on WS dispatch — `FIXED`
  - `_dispatch_message` now raises `WebSocketCommandRejectedError` for terminal
    threads (`COMPLETED`, `FAILED`, `CANCELLED`, `ARCHIVED`) and `INPUT_REQUIRED`
    threads, mirroring the REST 409 guards exactly
  - `ThreadStatus` and `update_thread_status` promoted to top-level imports;
    lazy import inside error handler removed
- `#72` PG-ARCH-01: backend abstraction + SQLite fallback hardening — `FIXED`
  - `/health` endpoint now includes `production_certifying: bool` — `true` only
    when both `database_backend` and `checkpoint_backend` resolve to `"postgres"`
  - Operators can alert on `production_certifying == false` in production
- Reconciliation window gap — `FIXED` (grounded in LangGraph Context7 docs)
  - `Executor._pre_flight_checkpoint()` added: inspects `CheckpointTuple.pending_writes`
    before every ingest dispatch using LangGraph sentinel channels (`"__interrupt__"`,
    `"__error__"`)
  - Empty `pending_writes` → thread completed before crash → emit `completed`, skip re-run
  - `"__error__"` channel present → thread errored before crash → emit `failed`, skip re-run
  - `"__interrupt__"` channel present → thread paused at interrupt → skip ingest,
    await resume dispatch
  - `is_first_ingest` now grounded in checkpoint truth (`aget_tuple` returns None)
    instead of stale in-memory cache — prevents initial-state fields from overwriting
    accumulated checkpoint values on RECONCILING thread re-dispatch after restart
  - Timeout 5 s on `aget_tuple`; on failure falls back to in-memory heuristic with warning
- `PROD-053` Docker gateway double-spawns worker — `FIXED`
  - Added `VAULTSPEC_AUTO_SPAWN_WORKER: 'false'` to gateway env in all Docker
    compose files that run the worker as a separate service
- `PROD-038` CLI stop-worker graceful shutdown — `FIXED`
  - Added `POST /admin/shutdown` to `worker/app.py`; CLI now reaches the same
    graceful shutdown path as the gateway
- `PROD-050` DELETE allows deleting RUNNING threads — `FIXED`
  - `delete_thread_endpoint` now fetches the thread first; raises 409 if RUNNING
- `PROD-066` Circuit breaker blocks cancel — `FIXED`
  - Removed `circuit_breaker.pre_dispatch()` from both REST and WS cancel paths;
    CB still participates through `record_success`/`record_failure` on the result
- `PROD-067` Worker 429 swallowed on create-thread — `FIXED`
  - Captures response; 429 → mark thread FAILED, raise 503; no CB state change
- `PROD-068` Worker 429 swallowed on send-message (REST + WS) — `FIXED`
  - REST: 503 on 429. WS: `WebSocketCommandRejectedError(recoverable=True,
    code="WORKER_AT_CAPACITY")`

### Still relevant deferred findings

- `PROV-O01`: Docker worker still lacks full Node/ACP runtime support for the
  broader provider matrix
- `WRK-K06`: closed. Worker `/dispatch` now enforces internal bearer auth and
  the gateway-owned worker client sends the token by default.
- `WRK-K01`: closed. The empty `worker/health.py` placeholder was removed.
- `CLI-I06`: closed. CLI MCP discovery now derives from `mcp.list_tools()`.

---

## Track 1: Audit Loop Discipline

### Goal

Keep the rolling audit/research/implementation loop explicit and enforced.

### Active task

- `#71`

### Required outcome

- every subsequent slice must close with:
  - verification
  - review
  - research/audit updates
  - queue refresh where needed

### Note

This is not a one-time code change. It stays active until the broader
backend-readiness program is complete.

---

## Track 2: Completed Test-Mandate Closeout

### Status

Closed.

- `#56` is fixed.
- The API-side harness now uses real file-backed SQLite, `AsyncSqliteSaver`,
  app-state injection, and the in-process ASGI worker path without
  `dependency_overrides` or `:memory:` DBs.

---

## Track 3: Remaining Operational Robustness

### Goal

Close the remaining operational/runtime defects that still sit outside the
completed Postgres and repair tracks.

### Active tasks

No open tasks remain in this track.

### Exit criteria

- queue no longer contains unresolved operational defects in the gateway/worker
  runtime path
- health/readiness and WebSocket control behavior remain consistent with the
  public contract

---

## Track 4: SQLite Fallback Hardening

### Status

Closed.

- `#72` is fixed.
- `/health` and `/api/health` now expose explicit `sqlite_fallback`
  diagnostics when SQLite is in use.
- SQLite remains supported but non-authoritative, with real WAL visibility
  exposed to operators.

---

## Track 5: Postgres Production Path Follow-through

### Goal

Treat the Postgres production path as established, then tighten the remaining
follow-through items rather than reopening already-closed runtime work.

### Open items

- keep `#74` closed unless CI behavior proves otherwise
- fold any future CI/matrix expansion into normal workflow maintenance, not a
  re-opened architecture track
- preserve the shared verifier authority:
  - `uv run vaultspec test prodlike-docker`
  - `just verify-prodlike-docker`
  - `just verify-claude-docker`
  - `just verify-gemini-docker`
  - `.github/workflows/prodlike-docker.yml`

### Note

This track is now mainly maintenance and drift prevention. The core runtime and
verification path is already in place.

### Remaining known limitation

- `PROV-O01` remains partial in narrowed form:
  - the Docker worker now includes Node.js plus `claude-agent-acp`
  - the Docker worker now also includes a pinned official Gemini CLI runtime
  - the stack is not yet certifying for the full Claude/Gemini ACP provider
    matrix
  - remaining work is provider-specific Docker certification, not generic ACP
    runtime installation
  - concrete remaining sub-gaps:
    - `#86` explicit supported Docker auth-material path for Claude/Gemini,
      plus a live credential-backed verifier run in the target environment

---

## Recommended Order

1. keep `#71` active across every pass

## Pivot Note (2026-03-11)

Execution is intentionally paused here for an observability/authority pivot.

Before resuming normal backend-readiness implementation, the next pass should
pick up:

- `#88` formal log/trace correlation architecture
- `#89` ADR-backed local ACP vs Docker runtime authority
- `#87` prod-like verifier startup diagnostics
- `#86` live credential-backed Docker provider certification

Continuation instructions are preserved in:

- `docs/plans/2026-03-11-observability-pivot-handoff.md`

---

## Exit Criteria For This Refreshed Plan

- no remaining partial backend-readiness tasks except deliberate maintenance
  items
- no stale plan language that still treats already-closed repair/Postgres work
  as active
- the queue, research log, and execution plan all agree on what is actually
  still open
- every remaining slice continues to close with review and audit sync
