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

Honest scope boundary, verified live 2026-07-14: on the engine build under test, only `session.created` reaches the `/events` durable outbox - creating and submitting a proposal advanced the outbox by a single `session.created` event and emitted no `proposal.*` / `approval.*` frames, so the reviewer-verdict events the subscriber resumes on (`approval.resolved` / `proposal.rejected`) are NOT observable on this engine yet. Consequently the full end-to-end verdict-to-resume hop across a real parked run is NOT proven live; that depends on (a) the engine emitting proposal/approval lifecycle events to the outbox, and (b) the phase-gate topology that actually parks a run at a proposal, which lands in P02.S05. The subscriber's own verdict decoding, id correlation, cursor persistence, and gap handling are proven over real infrastructure in the unit and integration suites. No test doubles were used; the live tests skip with a runbook pointer when no engine is reachable rather than simulating one.
