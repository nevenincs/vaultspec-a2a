---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-15'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# `adr-authoring-orchestration` `P03` summary

P03 built and partially verified the run-external verdict subscriber that closes the outer human loop: an SSE consumer with persisted cursor (S07) proven over real infrastructure including a live loopback engine (S08). The full verdict-to-resume round trip is not yet provable end to end because the engine build under test emits only `session.created` to the outbox — proposal and approval lifecycle events are not yet published — and the phase-gate topology that parks a run at a proposal lands in P02.S05.

- Created: `src/vaultspec_a2a/authoring/discovery.py`
- Created: `src/vaultspec_a2a/authoring/lifecycle.py`
- Modified: `src/vaultspec_a2a/authoring/client.py`
- Modified: `src/vaultspec_a2a/authoring/__init__.py`
- Created: `src/vaultspec_a2a/control/config.py`
- Created: `src/vaultspec_a2a/control/verdict_subscriber.py`
- Modified: `src/vaultspec_a2a/control/__init__.py`
- Created: `src/vaultspec_a2a/database/authoring_cursor_repository.py`
- Modified: `src/vaultspec_a2a/database/models.py`
- Modified: `src/vaultspec_a2a/database/__init__.py`
- Created: `src/vaultspec_a2a/database/migrations/versions/0007_authoring_event_cursor.py`
- Modified: `src/vaultspec_a2a/api/app.py`
- Created: `src/vaultspec_a2a/authoring/tests/test_discovery_unit.py`
- Created: `src/vaultspec_a2a/authoring/tests/test_lifecycle_unit.py`
- Created: `src/vaultspec_a2a/database/tests/test_authoring_cursor_repository.py`
- Created: `src/vaultspec_a2a/control/tests/test_verdict_subscriber.py`
- Created: `src/vaultspec_a2a/control/tests/test_verdict_subscriber_live.py`

## Description

S07 built the full subscriber stack. `authoring/lifecycle.py` decodes the engine's SSE frame vocabulary (`lifecycle`, `gap`, `error`) into typed structs, extracts proposal and changeset correlation ids, and maps the engine's three decision codes onto the pinned verdict vocabulary (`approved`, `rejected`, `request_changes`). `authoring/discovery.py` resolves the engine endpoint through the service.json attach-never-own contract and adds `stream_lifecycle` and `recovery_snapshot` methods to `AuthoringClient`. `control/verdict_subscriber.py` is the supervised polling loop: it reads the durable cursor, opens a bounded SSE page, correlates each verdict event to a parked `INPUT_REQUIRED` thread via its checkpointed `authoring_proposal_ids` / `authoring_changeset_ids`, and dispatches `Command(resume={"verdict", "notes"})` through the existing `safe_dispatch` path. Gap frames fall back to the recovery snapshot and jump the cursor to the high-water mark. The cursor itself is persisted in a new `AuthoringEventCursorModel` table (Alembic migration `0007`), so a gateway restart resumes the stream at the last durably processed sequence rather than replaying from zero. The subscriber is wired into the gateway lifespan behind the `VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED` environment flag (default off). Twenty unit tests covering lifecycle decoding, discovery skip behaviour, and cursor durability pass; the authoring, database, and control suites (175) are green.

S08 added mock-free integration and live tests for the subscriber. Five integration tests run over a real aiosqlite database and a real `AsyncSqliteSaver` checkpointer, exercising proposal-id correlation, changeset-id correlation, non-`INPUT_REQUIRED` thread exclusion, unknown-id no-ops, and cursor survival across a simulated gateway restart. Two `service`-marked live tests run against the loopback engine resolved through the production `resolve_engine` contract, proving the SSE consumer decodes the real engine wire shape for a `session.created` event.

Honest scope boundary: verified live on 2026-07-14 against the workspace-local engine (`--no-seat` on port 8767), the durable outbox emits only `session.created`. Creating and submitting a proposal advanced the outbox by exactly one event and emitted no `proposal.*` or `approval.*` frames. The reviewer-verdict events (`approval.resolved`, `proposal.rejected`) that the subscriber resumes on are therefore not observable on this engine build. The full verdict-to-resume hop across a real parked run is not proven live; it requires (a) the engine publishing proposal and approval lifecycle events to the outbox, and (b) the phase-gate topology from P02.S05 that parks a run at a proposal. The subscriber's own decoding, correlation, cursor persistence, and gap handling are proven over real infrastructure without test doubles.
