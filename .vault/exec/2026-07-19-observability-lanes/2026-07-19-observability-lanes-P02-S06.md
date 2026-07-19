---
tags:
  - '#exec'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S06'
related:
  - "[[2026-07-19-observability-lanes-plan]]"
---

# Enumerate the suppressed entity ids in both dedup ladders' batch-end summaries (dispatch: stuck thread ids per category at the reconcile summary

## Scope

- `websocket: failing client ids at the recovery or periodic summary) so storm dedup keeps per-entity diagnosability`
- `and scope the websocket recovered message so it cannot claim global recovery while other clients still fail. Live tests asserting ids appear in summaries while gapped occurrences stay unlogged`
- `src/vaultspec_a2a/control/dispatch.py`
- `src/vaultspec_a2a/api/websocket.py`
- `src/vaultspec_a2a/control/tests/`
- `src/vaultspec_a2a/api/tests/`

## Description

- `control/dispatch.py`: `_log_redispatch_failure_ladder` now takes and records the `thread_id` of every occurrence (not just the ones logged in full) into a per-category `failure_thread_ids` dict; the batch-end summary line now names every stuck thread for that category alongside its occurrence count, so a gapped/suppressed occurrence's thread id is still surfaced once the batch finishes.
- `api/websocket.py`: added `_failing_client_ids: set[str]` to `ConnectionManager`. `_log_heartbeat_failure` adds the failing client to the set and, on the lines it still logs (1st + every Nth - the gate itself is unchanged), names every currently-failing client, not just the one that triggered the line. `_record_heartbeat_success` now takes `client_id`, discards only that client from the failing set, and fires the "delivery recovered" INFO line only once the failing set is empty - a single client's success can no longer claim recovery while another client is still mid-failure, closing the review's scoping finding.
- Live tests (real logger, real production methods, no mocks): `control/tests/test_redispatch_failure_ladder.py` extends the existing 12-thread batch test with explicit thread ids and asserts every one appears in the batch-end summary. `api/tests/test_websocket.py::TestHeartbeatFailureLadder` adds a test proving a suppressed occurrence's client id still surfaces on the next line that does print, and two tests proving the scoped-recovery fix: one client succeeding while another still fails emits no "recovered" claim, and "recovered" only fires (naming "all clients") once every failing client has succeeded.
- Confirmed the ladder gate cadence itself (1st + every Nth occurrence) is unchanged in both places - only the message content and the recovery-scoping condition changed, per the review's explicit "no cadence change" constraint.

## Outcome

Both dedup ladders now name the specific entities behind a suppressed storm (stuck thread ids, failing client ids) instead of only a count, restoring per-entity diagnosability that the S04 dedup traded away. The websocket "recovered" claim is now truthfully scoped to when every failing client has actually recovered. Ruff and ty are clean; all touched/new tests pass (24 in the combined websocket + dispatch suites for this area).

## Notes

Ran ruff via `uvx ruff check` (isolated, no venv mutation) per the team-lead's environment-hazard guidance; `uv run --no-sync pytest`/`ty` were both available in the shared venv at the time of this step (verified before use) and used directly for tests and type-checking. No incidents. Committed with an explicit file pathspec (`git commit -o <files>`) per the new team-wide discipline, on whatever branch the shared checkout was on at commit time (per the team-lead's reconcile-via-temp-worktree pattern - did not touch the checkout's branch or reset anything).
