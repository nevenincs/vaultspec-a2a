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
- REVIEW-018
- REVIEW-019
- REVIEW-020
- REVIEW-021
- REVIEW-022
- REVIEW-023

Resolved on `containment`:

- REVIEW-024

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

REVIEW-018 | MEDIUM | Corrupted durable permission rows could crash reconnect/thread-state projection
Audit `4` found that `_permission_data_from_model()` parsed `permission.allowed_options_json` with a raw `json.loads(...)` during durable snapshot enrichment. That made a malformed `permission_requests` row capable of aborting `build_thread_state()` and the public `/api/threads/{id}/state` surface before any checkpoint-backed replay logic could even run. The fix makes unreadable durable permission rows fail closed instead of raising: snapshot assembly now records `permission_projection_unreadable`, omits the unreadable permission from the projected state, and degrades readiness to `operator_intervention_required`. The new regressions prove both the direct thread-state assembly path and the public state endpoint stay alive under that corruption mode. Evidence anchors: `src/vaultspec_a2a/control/projection.py`, `src/vaultspec_a2a/api/tests/test_thread_state_service.py`, `src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-019 | MEDIUM | Unreadable plan-approval rows could still leak pending approval metadata into reconnect snapshots
Audit `4` found a mirrored-state leak after the corrupt-permission hardening: even when an unreadable durable plan-approval row was omitted from `pending_permissions`, `enrich_snapshot_from_durable_state()` could still derive `approval_status="pending"` and `approval_request_id` from raw durable state. That included stale approval metadata already present on the thread row itself, leaving the reconnect snapshot internally inconsistent with a pending approval surface but no readable permission backing it. The fix now derives approval metadata only from readable projected permissions and clears stale thread-row approval metadata when the unreadable row is a plan-approval pause. The new thread-state regressions prove unreadable plan-approval rows no longer seed or preserve a fake pending approval state. Evidence anchors: `src/vaultspec_a2a/control/projection.py`, `src/vaultspec_a2a/api/tests/test_thread_state_service.py`.

REVIEW-020 | MEDIUM | WebSocket follow-up rejection flattened missing-thread uncertainty to plain not-found
Audit `4` found that the websocket `send_message` adapter still mapped `FailureType.NOT_FOUND` straight to `THREAD_NOT_FOUND`, even after the repo had established checkpoint-aware missing-thread diagnostics elsewhere. That meant backend drift or checkpoint uncertainty could be hidden on websocket follow-up messages even though the underlying control path already knew how to distinguish `THREAD_STATE_UNVERIFIED`. The fix routes websocket follow-up `NOT_FOUND` outcomes through the same checkpoint-aware `_raise_missing_thread()` classification used by the REST diagnostics path, and the new app-level regression proves a closed `AsyncSqliteSaver` plus orphaned durable execution-state residue now yields `THREAD_STATE_UNVERIFIED` instead of flattening to `THREAD_NOT_FOUND`. Evidence anchors: `src/vaultspec_a2a/api/ws_dispatch.py`, `src/vaultspec_a2a/api/app.py`, `src/vaultspec_a2a/api/tests/test_app.py`.

REVIEW-021 | MEDIUM | Thread summaries could still expose stale pending approval metadata after corrupt plan-approval state was cleared elsewhere
Audit `4` found that the `/api/threads` listing lagged behind the stricter reconnect snapshot path. Even after corrupt plan-approval rows were prevented from seeding approval metadata in snapshots, `list_threads_service()` still echoed `approval_status` and `approval_request_id` directly from the thread row. That meant a thread summary could still advertise a pending approval that no readable plan-approval permission actually backed. The fix now clears those summary fields when the backing plan-approval permission row is unreadable, and the new endpoint regression proves `/api/threads` no longer exposes that stale approval surface. Evidence anchors: `src/vaultspec_a2a/control/thread_service.py`, `src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-021 | MEDIUM | Plan approval still trusted stale thread-row pointers ahead of live durable permission truth
Audit `4` found another mirrored-state defect around plan approval. The permission-response guard could still prefer `thread.approval_request_id` when determining the active request for a plan-approval response, so a stale thread-row pointer could reject the live pending approval as superseded. The reconnect snapshot path also allowed stale `approval_status="pending"` / `approval_request_id` values to survive on the thread row even when no projected plan-approval permission actually remained. The fix now prefers live pending plan-approval rows over stale thread-row pointers during response validation, and clears stale pending approval metadata when no projected plan approval backs it. The new endpoint and thread-state regressions prove both the response path and reconnect snapshot now stay aligned with live durable permission truth. Evidence anchors: `src/vaultspec_a2a/control/permission_service.py`, `src/vaultspec_a2a/control/projection.py`, `src/vaultspec_a2a/api/tests/test_endpoints.py`, `src/vaultspec_a2a/api/tests/test_thread_state_service.py`.

REVIEW-022 | MEDIUM | `/api/threads` summaries could still expose corrupt pending plan-approval metadata
Audit `4` found that the list-thread summary surface lagged behind the stricter reconnect snapshot contract. Even after the snapshot path stopped exposing unreadable or stale plan-approval metadata, `/api/threads` could still echo `approval_status="pending"` and `approval_request_id` directly from the thread row when the backing plan-approval permission row was unreadable. The fix now clears those summary fields when the linked plan-approval permission payload cannot be parsed, and the new list-thread regression proves the summary surface no longer overstates pending approval state that the stricter snapshot path has already rejected. Evidence anchors: `src/vaultspec_a2a/control/thread_service.py`, `src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-023 | MEDIUM | `/api/threads` summaries still trusted stale pending plan-approval thread-row pointers after live approval truth had moved
Audit `4` found one more mirrored-state defect on the list-threads summary
surface. Even after the stricter permission and reconnect-state paths stopped
trusting stale plan-approval pointers, `/api/threads` summaries could still
echo `approval_status="pending"` and `approval_request_id` from the thread row
when the live durable plan-approval row was missing, superseded, or no longer
projected as active. That let the summary surface overstate resumable approval
state from stale mirrored metadata instead of the current durable approval
truth. The fix makes live projected durable plan approval win over the
thread-row pointer and clears summary approval metadata when no active durable
plan approval backs it. LangGraph checkpoint/persistence truth remains the
authoritative source, so mirrored repo state must fail closed when those
surfaces diverge. VidaiMock note: deterministic request-shape matching remains
a versioned contract, but that provider contract is adjacent here rather than
the source of the defect. Evidence anchors:
`src/vaultspec_a2a/control/thread_service.py`,
`src/vaultspec_a2a/control/projection.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-024 | HIGH | Test fixtures and offline regressions wrote durable scratch artifacts outside pytest-owned or repo-owned boundaries
The containment audit found multiple test surfaces writing SQLite files,
checkpoint files, and synthetic credential artifacts under developer-home
paths or ad hoc repo-root temp directories. That made the suite capable of
leaking state outside the test runner's owned boundary even when the
orchestration logic itself was correct. The fix moves those scratch writes
onto pytest-managed temp roots and removes the remaining ad hoc repo-root
workspace-rules path from the supervisor test. This keeps the test suite
disposable and makes runtime output ownership explicit: service certification
artifacts stay under `.vault/runtime/`, while non-service scratch data stays
under pytest-managed temp space. Evidence anchors:
`src/vaultspec_a2a/api/tests/conftest.py`,
`src/vaultspec_a2a/database/tests/conftest.py`,
`src/vaultspec_a2a/api/tests/test_app.py`,
`src/vaultspec_a2a/api/tests/test_projection.py`,
`src/vaultspec_a2a/api/tests/test_thread_state_service.py`,
`src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py`,
`src/vaultspec_a2a/control/tests/test_event_handlers.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`,
`src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`,
`src/vaultspec_a2a/providers/tests/test_gemini_auth.py`.

Residual note after `audit3`:
The active pending permission rule is now enforced consistently across durable
rows, aggregator memory, and the permission-response guard, but this class of
mirrored decision logic remains worth auditing explicitly. If any one of those
surfaces drifts from the others, stale outward-facing request ids can reappear
even while the underlying LangGraph thread-scoped interrupt semantics remain
correct.
