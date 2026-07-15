---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S08'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Prove the subscriber live against the loopback engine: approve and reject verdicts resume a parked run correctly across a gateway restart

## Scope

- `src/vaultspec_a2a/service_tests/`
- `src/vaultspec_a2a/control/tests/`

## Description

Added mock-free tests exercising the verdict subscriber against real infrastructure, split by what each layer can prove without the not-yet-built phase-gate topology.

- Added `control/tests/test_verdict_subscriber.py`: five integration tests over a real aiosqlite database and a real LangGraph `AsyncSqliteSaver` checkpointer. They seed an `INPUT_REQUIRED` thread whose checkpoint carries `authoring_proposal_ids` / `authoring_changeset_ids` and assert the subscriber correlates an inbound id to the parked thread by proposal id and by changeset id, ignores a `RUNNING` thread, returns nothing for unknown ids, and reads back the exact cursor a prior instance advanced (the gateway-restart survival case).
- Added `control/tests/test_verdict_subscriber_live.py`: two `service`-marked live tests against the loopback engine, resolved through the production `resolve_engine` discovery contract. They create a real session, replay its durable-outbox event over `GET /authoring/v1/events`, and assert the subscriber's SSE parser decodes it into a `LifecycleEvent` whose seq/event_kind/aggregate_id match the wire and correlate by id, and that a non-decision event yields no verdict.

## Outcome

Ran green against a live engine (workspace-local `--no-seat` serve on port 8767, resolved via `VAULTSPEC_ENGINE_SERVICE_JSON`): both `service` live tests pass, proving the SSE consumer decodes the real engine wire shape. The five integration tests pass over real aiosqlite + real checkpointer; the control default suite is green (12 passed, 2 service tests deselected). `ruff` and `ty` clean on both files.

## Notes

Original scope boundary (2026-07-14): the then-current engine build emitted only `session.created` to the `/events` outbox, so the verdict-to-resume hop was not provable live and the S08 live tests proved SSE-wire conformance on session events only.

### HIGH-2 addendum (2026-07-15): engine gap closed, full round-trip proven live

The engine now publishes the full review lifecycle to the durable outbox (dashboard commit `5173858`, "publish review lifecycle events to the durable outbox"). Re-verified against a freshly built binary served as a second workspace-local instance, attach-never-own, on an ephemeral port distinct from the owner's running engine.

- Build: `cargo build --manifest-path engine/Cargo.toml --release -p vaultspec-cli` in the dashboard worktree.
- Serve: `vaultspec serve --port 0 --no-seat` from a minimal throwaway workspace (its own `.vault/` + `.vaultspec/`), discovery at `<ws>/.vault/data/engine-data/service.json`, pointed at via `VAULTSPEC_ENGINE_SERVICE_JSON`. A serve from the full a2a worktree stalled the engine on repo indexing, hence the minimal workspace.

Added `test_live_verdict_round_trip_parks_and_resumes` and updated the module docstring (the session-only limitation is obsolete). The live round-trip drives three real proposals through submit plus a human decision (approve / reject / request-changes via `POST /v1/reviews/{approval_id}/decisions`, envelope command `approve`/`reject`/`edit_proposal`, payload decision `approve`/`reject`/`edit`), seeds one parked run per proposal on a real `AsyncSqliteSaver`, and feeds the real outbox frames through the subscriber. Verified verbatim from the live stream:

- `approval.requested` x3 - non-verdict, parks the run (`verdict_from_event` is `None`).
- `approval.resolved` `decision=approve` `comment=ship it` -> verdict `(approved, "ship it")`, correlated to `thread-appr`.
- `proposal.rejected` `decision=reject` `comment=not yet` -> verdict `(rejected, "not yet")`, correlated to `thread-rej`.
- `proposal.updated` `decision=request_changes` `comment=tighten it` -> verdict `(request_changes, "tighten it")`, correlated to `thread-edit` (request-changes rides `proposal.updated`, disambiguated by the decision field only; the decoder keys decision-first).

Each decision then ran the subscriber's real `_process_event` -> `safe_dispatch` resume path against an unreachable worker (genuine `WorkerUnreachableError` handling, no double), proving the subscriber reaches the resume with the correct verdict and no crash. The worker-side landing of the resumed graph belongs to the phase-gate topology and the service harness, not this subscriber unit. All three `service` live tests pass (43s); no test doubles anywhere; the live tests skip with a runbook pointer when no engine is reachable.
