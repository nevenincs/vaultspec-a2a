---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S07'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Build the engine lifecycle-event subscriber: SSE consumer with persisted cursor, recovery-snapshot fallback, proposal-id correlation, and Command resume dispatch to parked threads

## Scope

- `src/vaultspec_a2a/control/`
- `src/vaultspec_a2a/authoring/`
- `src/vaultspec_a2a/database/`

## Description

Built the run-external authoring-verdict subscriber across the control, authoring, and database packages so reviewer decisions on the engine review lane re-enter and resume parked runs.

- Added `AuthoringEventCursorModel` and a monotonic cursor repository (`get_authoring_cursor` / `set_authoring_cursor`) with Alembic migration `0007`, persisting the last durably-processed outbox sequence so a gateway restart resumes the stream instead of replaying from zero.
- Added `authoring/lifecycle.py`: typed decoding of the engine SSE frames (`lifecycle` / `gap` / `error`), correlation-id extraction, and verdict extraction mapping the engine `approve` / `reject` / `request_changes` decisions onto the pinned `approved` / `rejected` / `request_changes` vocabulary. Resume payload contract is `{"verdict": ..., "notes": ...}`.
- Added `authoring/discovery.py`: `resolve_engine` via the service.json attach-never-own contract (freshness window plus live `/health` probe), and streaming (`stream_lifecycle`) plus recovery (`recovery_snapshot`) methods on `AuthoringClient`.
- Added `control/verdict_subscriber.py`: a supervised polling loop that reads the cursor, opens the bounded SSE page, correlates each verdict to a parked `INPUT_REQUIRED` thread through its checkpointed `authoring_proposal_ids` / `authoring_changeset_ids`, and dispatches `Command(resume={"verdict", "notes"})` through the existing `safe_dispatch` worker path. Gap frames fall back to the recovery snapshot and jump the cursor to the high-water mark. Cancellation-safe; exponential back-off across engine restarts.
- Wired the subscriber into the gateway lifespan behind `VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED` (default off), with clean cancel-and-gather on shutdown.

## Outcome

Subscriber implemented and green on its owned surfaces: `ruff check`, `ruff format`, and `ty check` clean on all changed files; 20 new unit tests pass (lifecycle decoding, discovery skip behaviour, cursor repository including cross-session durability); the 8 migration tests pass with head advanced to `0007`; the authoring, database, and control suites pass (175). Live end-to-end proof against the loopback engine is deferred to the S08 Step per the plan.

## Notes

Full-tree `pytest` and `ty` were transiently red during execution because of concurrent in-progress edits by sibling executors outside this Step's scope: `graph/nodes/worker.py` raised a `BaseTool` `NameError` (P01.S02) that is transitively imported via `thread.enums`, and the new `team/presets` plus a mid-edit test conftest (P04.S09) failed two preset tests. None originate in this Step's files. The S07 commit stages only the control/authoring/database subscriber surface and its tests.
