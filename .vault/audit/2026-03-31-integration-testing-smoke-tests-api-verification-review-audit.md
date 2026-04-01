---
tags:
  - '#audit'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
related:
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-plan]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-adr]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-research]]'
  - '[[2026-03-31-integration-testing-service-certification-research]]'
---

# `integration-testing-smoke-tests-api-verification` Code Review

Resolved on `audit2a`:

- REVIEW-004
- REVIEW-005

Resolved on `audit2b`:

- REVIEW-001

Resolved on `audit2c`:

- REVIEW-002

Resolved on `audit2d`:

- REVIEW-006

Resolved on `audit3`:

- REVIEW-010

Resolved on `audit4`:

- REVIEW-011
- REVIEW-012
- REVIEW-013
- REVIEW-014
- REVIEW-015
- REVIEW-016
- REVIEW-017

REVIEW-009 | LOW | The VidaiMock human-loop tape still depends on the resumed tool result being serialized as the last message
Audit `2b` removed the brittle message-count and absolute-index contract from `mock-coder-human.yaml` and replaced it with a file-backed VidaiMock template that certifies approval, denial, invalid outcome handling, and readiness against the real compose-backed service lane. The residual contract is narrower but still real: resumed branch selection now assumes the worker-owned tool result remains the last serialized message in the provider request. If future worker prompt assembly appends additional post-tool messages before provider invocation, the tape could need another adjustment even though permission logic itself remains correct. Evidence anchors: `src/vaultspec_a2a/team/presets/mock/tapes/providers/mock-coder-human.yaml`, `src/vaultspec_a2a/team/presets/mock/tapes/templates/mock-coder-human-chat.json.j2`, `src/vaultspec_a2a/providers/mock_chat_model.py`, `src/vaultspec_a2a/graph/nodes/worker.py`.

REVIEW-003 | LOW | Completed-thread SSE replay is still locked down only by the service suite
The one-shot replay behavior in `thread_stream.py` is exercised end to end by the service certification scenario, but there is still no dedicated fast API-level test that asserts the replay payload and immediate close semantics in isolation. The current coverage is sufficient for the service gate but slower to localize if that contract regresses later.

REVIEW-007 | LOW | Stale `vaultspec-service-tests-*` Docker projects can accumulate silently after interrupted or incomplete sessions
Audit `2B1` found multiple still-running `vidaimock` and `jaeger` compose projects labeled `vaultspec-service-tests-*`, all created from this worktree and still removable with a manual `docker compose ... down -v --remove-orphans`. The service-test harness does call `stack.stop()` on normal fixture teardown and on `start()` exceptions, but `stop()` suppresses `docker compose down` failures with `check=False` and does not record whether teardown actually succeeded. That means aborted pytest runs, interrupted host sessions, or silent compose-down failures can leave infra-only projects behind without surfacing a test failure or an audit artifact. Evidence anchors: `src/vaultspec_a2a/service_tests/conftest.py`, `src/vaultspec_a2a/service_tests/harness.py`. Triaged as low-critical because it is resource hygiene rather than correctness drift, but it should be addressed before the service lane becomes a longer-lived developer gate.

REVIEW-008 | MEDIUM | `pending_permissions` can surface before the thread is durably resumable
The current service surface can expose a projected pending permission before the repository's separate durable permission row and freshness classification make the thread durably resumable. LangGraph is not the source of this gap: its interrupt state is checkpoint-backed, resumed via `Command(resume=...)`, and re-enters the node from the start after the last recorded checkpoint boundary. The risk is at the repo boundary, where projected pending permission is visible ahead of confirmed resume eligibility. `pending_permissions` therefore must not be treated as proof of safe resumability on its own. Evidence anchors: `src/vaultspec_a2a/service_tests/test_permissions_resume.py`, `src/vaultspec_a2a/service_tests/test_stream_followup.py`, `src/vaultspec_a2a/control/permission_service.py`, `src/vaultspec_a2a/control/thread_state_service.py`, `src/vaultspec_a2a/control/projection.py`, `src/vaultspec_a2a/thread/snapshots.py`, `src/vaultspec_a2a/api/routes/thread_state.py`.

REVIEW-011 | LOW | `mark_permission_response_applied` recorded the requested action instead of the applied action
Audit `4` found that the repair transition helper for a successful permission response was still stamping `last_requested_action` even though the durable resume path had already succeeded and the thread row should have reflected the applied transition. LangGraph replay semantics make this distinction important because the worker can re-enter from the checkpoint boundary, so the durable repair row is part of the restart truth, not just bookkeeping noise. The issue was confirmed by the real `/api/permissions/{request_id}/respond` success path and fixed by switching the applied transition to `last_applied_action`; compose-backed service verification for `src/vaultspec_a2a/service_tests/test_permissions_resume.py` passed after the patch. Evidence anchors: `src/vaultspec_a2a/control/repair_transitions.py`, `src/vaultspec_a2a/control/permission_service.py`, `src/vaultspec_a2a/database/reconciliation.py`, `src/vaultspec_a2a/service_tests/test_permissions_resume.py`.

REVIEW-012 | MEDIUM | Degraded execution-state heartbeats could mask stale checkpoint lineage by overwriting `recovery_epoch`
Audit `4` found that `record_thread_execution_state()` was preserving the last good checkpoint snapshot on degraded-only updates, but it was still refreshing the row's `recovery_epoch` to match the thread. After restart or reconciliation, that let an older execution-state snapshot look current even though no fresh checkpoint payload had been recorded for the new recovery epoch. The fix keeps the previous `recovery_epoch` when the update is degraded-only, and the projection layer now continues to surface `execution_state_projection_stale` until a real fresh execution-state payload arrives. Evidence anchors: `src/vaultspec_a2a/database/thread_repository.py`, `src/vaultspec_a2a/control/projection.py`, `src/vaultspec_a2a/api/tests/test_projection.py`.

REVIEW-013 | MEDIUM | Startup reconciliation treated pending permissions as resumable even when checkpoint truth was missing
Audit `4` found that the pure startup reconciliation policy still classified a thread as `paused_resumable` whenever a durable pending permission survived restart, even if the checkpoint probe had already failed. That inverted LangGraph's checkpoint-backed resume contract at the repo boundary: the permission row survived, but there was no authoritative checkpoint state proving the thread could actually resume. The fix makes checkpoint availability a prerequisite for `paused_resumable`, and adds both a pure lifecycle regression and a database-backed startup test to prove `reconcile_threads_on_startup()` falls through to `repair_needed` / `checkpoint_unavailable` when checkpoint truth is absent. Evidence anchors: `src/vaultspec_a2a/lifecycle/reconciliation.py`, `src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py`, `src/vaultspec_a2a/database/tests/test_reconciliation.py`.

REVIEW-014 | LOW | Message-followup bookkeeping reused the requested enum for the applied transition
Audit `4` found a smaller mirrored-state drift in the follow-up message path: `mark_message_followup_applied()` still stamped `MESSAGE_FOLLOWUP_REQUESTED`, and the pure repair-policy map keyed the applied phase off the requested enum as well. That left the durable repair row and policy lookup slightly out of sync with the actual post-dispatch state even though the follow-up request had already been applied successfully. The fix separates the requested and applied enums, and the new API and pure-policy regressions prove the durable row records `message_followup_requested` and `message_followup_applied` distinctly after a successful follow-up dispatch. Evidence anchors: `src/vaultspec_a2a/control/repair_transitions.py`, `src/vaultspec_a2a/thread/repair_policy.py`, `src/vaultspec_a2a/api/tests/test_endpoints.py`, `src/vaultspec_a2a/thread/tests/test_repair_policy.py`.

REVIEW-015 | LOW | Dispatch failures left repair/readiness metadata stale after the worker became unreachable
Audit `4` found that several dispatch-failure branches were already marking the thread row `FAILED`, but the durable repair and readiness fields could still look healthy after a worker-unreachable failure. That projected the wrong operator state at the repo boundary: the thread was terminally failed, but the row still suggested it was healthy enough for normal execution. The fix adds a shared dispatch-failure transition that stamps `operator_intervention_required` across message, permission, thread, and diagnostics failure paths, and the new direct regressions prove both service dispatch failure and websocket `mark_thread_failed()` now degrade the durable row consistently. Evidence anchors: `src/vaultspec_a2a/control/repair_transitions.py`, `src/vaultspec_a2a/control/message_service.py`, `src/vaultspec_a2a/control/permission_service.py`, `src/vaultspec_a2a/control/thread_service.py`, `src/vaultspec_a2a/control/diagnostics.py`, `src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py`.

REVIEW-016 | MEDIUM | Unreadable durable execution-state rows could leave reconnect snapshots looking healthy despite state corruption
Audit `4` found that `enrich_snapshot_from_execution_state()` already marked the snapshot incomplete when `project_execution_state_model()` could not deserialize the durable `thread_execution_state` row, but it still inherited the thread row's existing readiness values. If checkpoint loading succeeded, the final snapshot could therefore look checkpoint-durable while still presenting `repair_status="healthy"` and `execution_readiness="healthy"` even though the durable execution-state row was corrupted. The fix keeps LangGraph's checkpoint authority intact for replay status while failing the corruption path closed at the repo boundary: unreadable execution-state projection now stamps both readiness fields `operator_intervention_required`, and the new pure projection plus real `AsyncSqliteSaver` thread-state regressions prove the degraded state is surfaced consistently. Evidence anchors: `src/vaultspec_a2a/control/projection.py`, `src/vaultspec_a2a/api/tests/test_projection.py`, `src/vaultspec_a2a/api/tests/test_thread_state_service.py`.

REVIEW-017 | MEDIUM | Missing-thread websocket diagnostics overstated drift when checkpoint truth was unverified
Audit `4` found that `classify_missing_ws_thread()` returned `THREAD_STATE_DRIFT` as soon as any durable residue existed, even if checkpoint verification had already timed out or failed. That inverted the checkpoint-first contract already used elsewhere in the repo: a stale execution-state row could make the gateway sound more certain than the backend truth allowed. The fix makes checkpoint uncertainty win over drift for this path, so missing-thread websocket commands now return `THREAD_STATE_UNVERIFIED` whenever checkpoint truth cannot be verified, even if orphaned execution-state residue is still present. The new app-level regression proves that behavior with a real closed `AsyncSqliteSaver` plus a durable execution-state row. Evidence anchors: `src/vaultspec_a2a/control/diagnostics.py`, `src/vaultspec_a2a/api/tests/test_app.py`.

Residual note after `audit3`:
The active pending permission rule is now enforced consistently across durable
rows, aggregator memory, and the permission-response guard, but this class of
mirrored decision logic remains worth auditing explicitly. If any one of those
surfaces drifts from the others, stale outward-facing request ids can reappear
even while the underlying LangGraph thread-scoped interrupt semantics remain
correct.
