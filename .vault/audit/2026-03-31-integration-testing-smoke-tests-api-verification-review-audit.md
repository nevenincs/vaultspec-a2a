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

Resolved on `audit5`:

- REVIEW-025
- REVIEW-026

Resolved on `audit5`:

- REVIEW-025
- REVIEW-026

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

REVIEW-025 | MEDIUM | Supervisor plan approvals were stream-visible without a guaranteed durable pending permission row
Audit `5` found a concrete relay defect at the repository boundary. The
supervisor path already emitted outward-facing `plan_approval_request` events,
and the streaming transformer already treated those as permission-like
interrupts, but the durable event classifier and permission-event handler still
created durable rows only for `permission_request`. That left a split-brain
failure mode where a supervisor approval pause could appear pending in streamed
or projected state while `/api/permissions/{id}/respond` had no durable pending
permission row to answer. LangGraph itself is not the source of this behavior:
its checkpoint-backed interrupt contract requires the pause to remain resumable
under the same `thread_id`, so the defect was in the repo-owned relay layer.
The minimal fix now treats `plan_approval_request` as a first-class durable
request-creation event, and the new regressions prove both the direct event
handler path and the real `/internal/events` -> `/api/permissions/{id}/respond`
HTTP boundary. Residual risk remains because plan-approval payload semantics
are still mirrored across supervisor, stream transform, projection, and
permission-response logic; that is the next explicit `Audit 5` service
certification target. Evidence anchors:
`src/vaultspec_a2a/thread/snapshots.py`,
`src/vaultspec_a2a/control/event_handlers.py`,
`src/vaultspec_a2a/control/tests/test_event_handlers.py`,
`src/vaultspec_a2a/api/tests/test_internal.py`.

REVIEW-026 | MEDIUM | Supervisor plan-approval service certification failed before the permission boundary was exercised
Audit `5` found a second supervisor-path defect in the real stack. The fast
durability fix from `REVIEW-025` was already in place, but the compose-backed
supervisor certification still completed early with `routing_error` and never
reached the first approval pause. LangGraph durability was not the issue: the
actual failures were repo-owned supervisor model resolution and provider stream
decoding. First, supervisor model resolution omitted the supervisor
`agent_config`, so the mock provider could not select the
`vaultspec-supervisor` VidaiMock tape. Second, the supervisor route returned
string-wrapped JSON SSE chunks, and `MockChatModel` dropped those chunks
instead of decoding them into route text. The fix now passes supervisor agent
identity through compiler model resolution, adds focused compiler coverage for
that seam, and hardens `MockChatModel` to decode nested JSON string chunks for
both route text and tool-call extraction. The compose-backed supervisor
certifier now passes end to end, including the supervisor plan approval pause,
worker permission pause, and final completion path. Evidence anchors:
`src/vaultspec_a2a/graph/compiler.py`,
`src/vaultspec_a2a/graph/tests/test_compiler.py`,
`src/vaultspec_a2a/providers/mock_chat_model.py`,
`src/vaultspec_a2a/providers/tests/test_mock_chat_model.py`,
`src/vaultspec_a2a/service_tests/harness.py`,
`src/vaultspec_a2a/service_tests/test_permissions_resume.py`,
`src/vaultspec_a2a/team/presets/mock/tapes/providers/vaultspec-supervisor.yaml`,
`src/vaultspec_a2a/team/presets/mock/tapes/templates/vaultspec-supervisor-chat.json.j2`,
`src/vaultspec_a2a/team/presets/teams/mock-supervisor-human-in-loop.toml`.

REVIEW-027 | LOW | Supervisor deterministic routing remains template-sensitive even after the service certifier went green
Audit `5` now certifies the full supervisor approval path successfully, but it
also made the residual contract clearer: the deterministic supervisor route is
still sensitive to VidaiMock template shape and terminal-branch behavior. The
current hardening narrows that risk substantially by probing both supervisor
and worker mock routes during readiness, preserving supervisor mock identity at
provider resolution, and decoding string-wrapped mock stream chunks in the
provider adapter. Even so, future drift in the supervisor tape's streamed
response shape or `FINISH` branch would weaken the certification signal before
core LangGraph logic itself regressed. Evidence anchors:
`src/vaultspec_a2a/graph/compiler.py`,
`src/vaultspec_a2a/providers/mock_chat_model.py`,
`src/vaultspec_a2a/service_tests/harness.py`,
`src/vaultspec_a2a/team/presets/mock/tapes/providers/vaultspec-supervisor.yaml`,
`src/vaultspec_a2a/team/presets/mock/tapes/templates/vaultspec-supervisor-chat.json.j2`.

REVIEW-028 | MEDIUM | Stale durable execution-state lineage could leave reconnect state looking healthier than checkpoint truth
Audit `6` found that stale durable execution-state lineage was only being
tagged with `execution_state_projection_stale`, while reconnect snapshots and
`/api/threads/{id}/state` could still inherit `repair_status="healthy"` and
`execution_readiness="healthy"` from the thread row. That overstated certainty
at the repo boundary: LangGraph resume semantics are checkpoint-backed and
thread-scoped, so a readable-but-stale `thread_execution_state` row must not
outrank the active checkpoint lineage during reconnect classification. The fix
now fails closed to `needs_reconciliation` whenever the durable
execution-state row no longer matches the thread `recovery_epoch` or live
checkpoint id, while keeping `snapshot_complete=false` and
`execution_state_projection_stale` visible for operators. The new regressions
prove both the pure state-service path and the public `/state` endpoint no
longer advertise a healthy reconnect surface under stale execution-state
lineage. Evidence anchors:
`src/vaultspec_a2a/control/projection.py`,
`src/vaultspec_a2a/api/tests/test_thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-029 | MEDIUM | Thread summary surfaces could still echo healthy readiness under stale execution-state lineage
Audit `6` found a mirrored stale-lineage leak after `REVIEW-028`. The
reconnect snapshot and `/api/threads/{id}/state` now fail closed when the
durable execution-state row lags checkpoint truth, but `/api/threads` and the
MCP-backed list-thread surface were still echoing `repair_status` and
`execution_readiness` directly from the thread row. That left the summary
surfaces sounding healthier than the stricter reconnect path even when the
durable execution-state `recovery_epoch` was stale. The fix now degrades
summary readiness to `needs_reconciliation` when the latest durable
execution-state row carries older lineage than the thread row, and the new API
and MCP regressions prove the summary surfaces no longer overstate health
under stale execution-state lineage. Evidence anchors:
`src/vaultspec_a2a/control/thread_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-054 | MEDIUM | MCP `send_message` leaked raw backend conflicts after repair-state follow-up hardening
Audit `6` exposed another operator-surface lag after follow-up messaging was
correctly blocked for `repair_needed` and `reconciling` threads. The REST
backend now rejects those follow-ups with `409`, but
`src/vaultspec_a2a/protocols/mcp/tools/messaging.py` was still letting that
conflict escape as a raw HTTP failure instead of a usable `ToolError`. That
left the MCP control surface behind the stricter backend contract for
repair-state threads. The fix now maps backend message-side `409` conflicts
into `ToolError` with the backend detail so MCP operators see an explicit
follow-up eligibility failure rather than a transport-level error. Evidence
anchors: `src/vaultspec_a2a/protocols/mcp/tools/messaging.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-030 | HIGH | Durable pending approvals without `tool_call` could disappear during thread-state reconstruction
Review follow-up exposed a stricter gateway-side reconstruction bug at the
boundary between durable projection and checkpoint-state enrichment. Durable
`plan_approval_request` rows intentionally allow `tool_call = NULL`, and the
supervisor interrupt path emits exactly that shape. The projection layer now
normalizes those rows back to `plan_approval`, but thread-state assembly was
still vulnerable because checkpoint enrichment replaced
`snapshot.pending_permissions` with thinner checkpoint/aggregator state instead
of merging by durable `request_id`. That could leave `approval_status` and
`approval_request_id` set while the actual pending permission vanished from the
public state surface, making a still-pending approval look non-actionable. The
fix now preserves durable pending permissions during checkpoint enrichment and
normalizes nullable plan-approval `tool_call` values during durable
projection. The new regressions prove thread-state assembly and the public
`/api/threads/{id}/state` endpoint both preserve the pending approval surface
for a durable plan-approval row created without `tool_call`. Evidence anchors:
`src/vaultspec_a2a/control/projection.py`,
`src/vaultspec_a2a/control/snapshot.py`,
`src/vaultspec_a2a/api/tests/test_thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-031 | MEDIUM | Team status could hide durably paused threads after restart-like memory loss
Audit `6` also exposed an operator-surface drift in team status assembly. The
team-status view already loads durable pending permissions from the database,
but `active_threads` was still derived only from heartbeat threads and
in-memory aggregator state. After a restart-like loss of worker memory, that
allowed `/api/team/status` and the MCP-backed `get_team_status` /
`get_pending_permissions` surfaces to report a pending durable approval while
omitting the owning thread from the active-thread list. The fix now unions
durable pending-permission thread ids into `active_threads`, and the new
MCP-backed regression proves a durably paused thread remains visible even when
heartbeat and aggregator state are empty. Evidence anchors:
`src/vaultspec_a2a/control/team_service.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-032 | HIGH | Failed resume dispatch could restore pending permission while leaving the thread terminal
Audit `6` found a stricter retryability drift on the permission resume path.
When worker dispatch failed after a permission response was durably submitted,
the repository could reset the permission row away from
`answered_pending_apply`, but it still left the thread in terminal
`failed`. That made the durable permission look pending again while the public
surface rejected retry as non-actionable. The fix now rolls the durable
permission row back to `pending`, retires the failed control-action
idempotency key to a tombstone value instead of nulling or reusing it, and
keeps the thread in retryable `input_required` while readiness stays degraded.
That matches the LangGraph boundary: resume restarts from the node boundary,
and side effects before interrupt must be idempotent, so rollback belongs at
the durable write boundary rather than in downstream projection repair.
Evidence anchors: `src/vaultspec_a2a/control/permission_service.py`,
`src/vaultspec_a2a/database/permission_repository.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/control/repair_transitions.py`,
`src/vaultspec_a2a/thread/enums.py`.

REVIEW-033 | MEDIUM | Stale execution-state rows could still overstate public runtime truth
Audit `6` also closed a split-brain bug between reconnect/state surfaces and
summary surfaces. `/api/threads/{id}/state` was marking stale durable
execution-state lineage, but it still copied stale runtime fields such as
`next_nodes`, `task_count`, `pending_interrupt_count`, and `execution_tasks`
into the public snapshot before classifying the row as stale. `/api/threads`
summaries were also weaker than reconnect/state because they only degraded on
`recovery_epoch` drift and ignored checkpoint-id mismatch entirely. The fix
now fails closed before applying stale execution-state projection to `/state`,
keeps `snapshot_complete=false` with
`execution_state_projection_stale`, and routes the app checkpointer into
`list_threads_service` so summary readiness also degrades on checkpoint-id
drift. Evidence anchors: `src/vaultspec_a2a/control/projection.py`,
`src/vaultspec_a2a/control/thread_service.py`,
`src/vaultspec_a2a/api/routes/threads.py`,
`src/vaultspec_a2a/api/tests/test_thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-034 | MEDIUM | Team status could advertise ghost pending permissions from aggregator memory
Audit `6` also closed a persistence-versus-operator-surface mismatch in
`/api/team/status`. The route previously started from durable pending
permissions but then appended aggregator-only permission entries that had no
durable backing row, allowing operator and MCP surfaces to advertise
actionable pending work that persistence could not actually satisfy. The fix
now makes team status durable-first for pending permissions:
`build_team_status()` keeps pending permissions from
`get_pending_permission_requests()` only, while aggregator state remains
limited to `agents` and `active_threads`. That removes ghost permissions from
the public surface without weakening liveness visibility. Evidence anchors:
`src/vaultspec_a2a/control/team_service.py`,
`src/vaultspec_a2a/api/routes/teams.py`,
`src/vaultspec_a2a/api/schemas/rest.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-035 | HIGH | WebSocket dispatch failure could leave stale pending permissions after terminal failure
Audit `6` also closed a WebSocket-specific terminal-cleanup drift. The WS
dispatch-failure path was previously acting like a status-only transition:
it marked the thread failed and degraded repair state, but it did not reuse
the canonical terminal cleanup path that expires durable pending permission
rows and prunes aggregator pending-permission state. The fix now routes WS
failure through `mark_thread_failed(...)` with the live aggregator, and that
helper reuses the canonical terminal-event cleanup before re-applying repair
degradation. As a result, WS-marked terminal threads no longer leave stale
pending approvals in persistence or aggregator memory. Evidence anchors:
`src/vaultspec_a2a/api/ws_dispatch.py`,
`src/vaultspec_a2a/control/diagnostics.py`,
`src/vaultspec_a2a/control/event_handlers.py`,
`src/vaultspec_a2a/database/permission_repository.py`,
`src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py`.

REVIEW-036 | HIGH | Failed cancel dispatch could leave a ghost durable `cancel_pending` state
Audit `6` also closed a cancel-path persistence split. `cancel_thread()` in
`src/vaultspec_a2a/control/cancel_service.py` was marking durable repair state
as `cancel_pending` before worker dispatch, but on dispatch failure it returned
`accepted=False` / `cancelled=False` while leaving the durable repair row in the
pre-dispatch cancel state. That violated the deterministic durable-execution
contract: the public API said cancel was not accepted, while persistence still
advertised an in-flight cancel. The fix now captures the prior durable repair
state before `mark_cancel_requested()` and restores it on the failure path, so
repair status, readiness, and `last_requested_action` stay aligned with the 502
response. Evidence anchors:
`src/vaultspec_a2a/control/cancel_service.py`,
`src/vaultspec_a2a/control/repair_transitions.py`,
`src/vaultspec_a2a/api/routes/cancel.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-037 | HIGH | Startup reconciliation trusted `cancelling` without checkpoint truth
Audit `6` also exposed a restart-time persistence drift. The pure startup
reconciliation logic in `src/vaultspec_a2a/lifecycle/reconciliation.py` was
previously allowing `status="cancelling"` to produce `repair_status="cancel_pending"`
even when checkpoint probing had already failed. That overstated durable
execution truth after restart: a surviving thread status is only metadata, and
without checkpoint truth the system cannot safely claim cancellation is still
in flight. The fix now makes `checkpoint_available=False` win over the
`cancelling` branch, forcing `repair_needed` / `checkpoint_unavailable`
instead of `cancel_pending`. Evidence anchors:
`src/vaultspec_a2a/lifecycle/reconciliation.py`,
`src/vaultspec_a2a/database/reconciliation.py`,
`src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py`,
`src/vaultspec_a2a/database/tests/test_reconciliation.py`.

REVIEW-038 | MEDIUM | `/api/threads/{id}/state` leaked aggregator-only pending permissions
Audit `6` also exposed a durable/public-state drift in the reconnect snapshot
path. `build_thread_state()` in `src/vaultspec_a2a/control/thread_state_service.py`
was letting `src/vaultspec_a2a/control/snapshot.py` append pending permissions
from in-memory aggregator state even when no durable permission row existed.
That made `/api/threads/{id}/state` advertise actionable pending permissions
that persistence could not actually satisfy, which is the same class of drift
already closed on `/api/team/status`. The fix removes aggregator-only
permission projection from the checkpoint snapshot path so pending permissions
on thread-state snapshots remain durable-backed only. Evidence anchors:
`src/vaultspec_a2a/control/snapshot.py`,
`src/vaultspec_a2a/control/thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-039 | MEDIUM | `/api/health` reported checkpoint readiness from handle presence alone
Audit `6` also exposed an operator-surface drift in gateway readiness. The
`/api/health` path in `src/vaultspec_a2a/control/health.py` was previously
treating a non-null checkpointer handle as equivalent to a healthy durable
checkpoint backend, even when the saver itself was unusable. That overstated
LangGraph durable readiness: interrupts and resume require a working
checkpointer backend, not just an attached object. The fix now probes the
actual checkpointer with `aget_tuple(...)` and degrades the checkpoint health
check to `error` when the probe times out or raises. Evidence anchors:
`src/vaultspec_a2a/control/health.py`,
`src/vaultspec_a2a/api/routes/health.py`,
`src/vaultspec_a2a/api/tests/test_app.py`.

REVIEW-040 | MEDIUM | `/api/threads` summaries stayed healthy when checkpoint probing was unverified
Audit `6` also exposed an operator-surface drift in thread summaries. The
summary path in `src/vaultspec_a2a/control/thread_service.py` could keep
`repair_status` and `execution_readiness` healthy when checkpoint probing
timed out or raised, even though the gateway could no longer verify checkpoint
truth. That overstated durable readiness at the list-threads boundary. The fix
now makes `/api/threads` fail closed to `checkpoint_unavailable` when
checkpoint probing is unverified, and the MCP-backed route coverage proves the
same behavior through the protocol surface. Evidence anchors:
`src/vaultspec_a2a/control/thread_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-041 | MEDIUM | `/api/threads/{id}/state` could advertise checkpoint-only pending permissions
Audit `6` exposed another durable-versus-public-state split in the reconnect
snapshot surface. `build_thread_state()` in
`src/vaultspec_a2a/control/thread_state_service.py` correctly merged durable
pending permissions first, but it then applied checkpoint projection and
re-surfaced interrupt-derived permissions that had no durable pending row.
That meant `/api/threads/{id}/state` could advertise a pending permission from
checkpoint `__interrupt__` even though the actual respond path in
`src/vaultspec_a2a/control/permission_service.py` would fail closed with
`Permission request is not durably pending`. The fix now reconciles checkpoint
interrupts against the durable pending permission ids after checkpoint merge,
drops checkpoint-only permission entries, clears stale mirrored approval
pointers when needed, and degrades the snapshot with
`checkpoint_permission_without_durable_row` instead of overstating actionability.
Evidence anchors: `src/vaultspec_a2a/control/projection.py`,
`src/vaultspec_a2a/control/thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-042 | MEDIUM | Team-status and MCP discovery could advertise malformed durable permission rows
Audit `6` exposed a remaining operator-surface drift in team-status discovery.
`build_team_status()` in `src/vaultspec_a2a/control/team_service.py` was using
all durable pending permission rows as public pending truth, even when a row's
`allowed_options_json` was malformed or contained no usable option ids. That
meant `/api/team/status` and MCP `get_pending_permissions()` could still
advertise a request id that the respond path would reject as
`Permission request has no valid options`. The fix now keeps active-thread
visibility for those paused threads but excludes malformed or optionless
durable rows from public pending-permission discovery. Evidence anchors:
`src/vaultspec_a2a/control/team_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-043 | MEDIUM | Team-status discovery could keep advertising pending permissions on terminal threads
Audit `6` exposed one more operator-surface drift in team-status discovery.
`build_team_status()` in `src/vaultspec_a2a/control/team_service.py` was still
trusting non-expired durable permission rows without reconciling them against
the owning thread lifecycle. That meant `/api/team/status` could continue to
list a permission as pending, and keep its thread in `active_threads`, even
after the durable thread status had already reached a terminal state where the
respond path would reject further action. The fix now excludes terminal-thread
permission residue from public pending discovery and from active-thread
promotion while preserving non-terminal paused-thread visibility, including the
malformed-row case already covered by `REVIEW-042`. Evidence anchors:
`src/vaultspec_a2a/control/team_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

Residual note after `audit3`:
The active pending permission rule is now enforced consistently across durable
rows, aggregator memory, and the permission-response guard, but this class of
mirrored decision logic remains worth auditing explicitly. If any one of those
surfaces drifts from the others, stale outward-facing request ids can reappear
even while the underlying LangGraph thread-scoped interrupt semantics remain
correct.

REVIEW-044 | MEDIUM | `/api/threads` summaries could keep stale plan approval metadata actionable
Audit `6` exposed another summary-surface drift in list-thread discovery.
`list_threads_service()` in `src/vaultspec_a2a/control/thread_service.py` was
still trusting mirrored thread-row approval metadata too broadly. Two cases
remained unsafe: optionless durable plan-approval rows could still validate as
pending because the summary path only checked JSON shape, and terminal threads
could continue to expose `approval_status="pending"` even though the control
layer would reject further approval responses. The fix now reuses a shared
durable option-id validator, clears summary approval metadata for terminal
threads before pending-plan reconstruction, and keeps `/api/threads` and MCP
list-thread discovery aligned with the actual permission-response contract.
Evidence anchors:
`src/vaultspec_a2a/control/permission_options.py`,
`src/vaultspec_a2a/control/thread_service.py`,
`src/vaultspec_a2a/control/permission_service.py`,
`src/vaultspec_a2a/control/team_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-045 | MEDIUM | `/api/threads/{id}/state` could keep terminal-thread pending permissions actionable
Audit `6` exposed the same public-state drift in the reconnect snapshot
surface. `enrich_snapshot_from_durable_state()` in
`src/vaultspec_a2a/control/projection.py` was still projecting durable pending
permission rows and mirrored plan-approval metadata even when the owning thread
had already reached a terminal lifecycle state. That meant
`/api/threads/{id}/state` could continue to advertise `pending_permissions` and
`approval_status="pending"` even though the permission-response path would
reject further action, and MCP `get_thread_status` would inherit the same stale
actionability because it formats `pending_permissions` from that payload. The
fix now fails closed at durable projection time: terminal-thread permission
residue is dropped from the public snapshot, mirrored approval pointers are
cleared, and the snapshot is degraded with
`terminal_thread_pending_permission_residue` instead of silently overstating
resumability. Evidence anchors:
`src/vaultspec_a2a/control/projection.py`,
`src/vaultspec_a2a/control/thread_state_service.py`,
`src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`,
`src/vaultspec_a2a/api/tests/test_thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-046 | MEDIUM | Public permission reads could misclassify answered-not-applied rows as pending
Audit `6` exposed a remaining public-state split in permission handling.
`get_pending_permission_requests()` in
`src/vaultspec_a2a/database/permission_repository.py` still surfaced
`answered_pending_apply` rows to the same read paths that power
`/api/team/status`, `/api/threads/{id}/state`, `/api/threads`, and the MCP
mirrors. That is correct for internal apply bookkeeping, but it is too broad
for public/actionable reads because a permission that has already been answered
is no longer user-actionable even if apply is still in flight. The fix now
splits that read boundary: public surfaces consume only true `pending` rows,
while internal apply flows can continue to see answered-not-applied rows.
Evidence anchors: `src/vaultspec_a2a/database/permission_repository.py`,
`src/vaultspec_a2a/control/projection.py`,
`src/vaultspec_a2a/control/team_service.py`,
`src/vaultspec_a2a/control/thread_service.py`,
`src/vaultspec_a2a/control/thread_state_service.py`,
`src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`,
`src/vaultspec_a2a/api/tests/test_thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-047 | MEDIUM | Startup reconciliation must not treat answered-not-applied permissions as resumable pending state
Audit `6` still had one restart-surface drift after `REVIEW-046`.
`reconcile_threads_on_startup()` in
`src/vaultspec_a2a/database/reconciliation.py` was still building
`pending_map` from `get_pending_permission_requests(...)` without separating
user-actionable `pending` rows from `answered_pending_apply` rows. That meant
a permission that had already been answered, but was still waiting on internal
apply bookkeeping, could be classified as `paused_resumable` and push the
thread back to `input_required` on restart even though the public/operator
surfaces no longer considered it actionable. The fix keeps restart
reconciliation aligned with deterministic public state: only true pending
permissions drive resumable startup repair, while answered-not-applied rows
remain internal apply-in-flight state. Evidence anchors:
`src/vaultspec_a2a/database/permission_repository.py`,
`src/vaultspec_a2a/database/reconciliation.py`,
`src/vaultspec_a2a/lifecycle/reconciliation.py`,
`src/vaultspec_a2a/database/tests/test_reconciliation.py`,
`src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py`.

REVIEW-048 | MEDIUM | `/api/threads/{id}/state` could keep `pause_cause` populated after public permission/actionability is cleared
Audit `6` exposed a final projection drift in the thread-state surface.
`enrich_snapshot_from_durable_state()` in
`src/vaultspec_a2a/control/projection.py` was already clearing
`pending_permissions`, `approval_status`, and `approval_request_id` for
answered-not-applied, checkpoint-only, and terminal-thread residue cases, but
it could still leave `pause_cause` populated. That made
`/api/threads/{id}/state` look paused even when no user-actionable permission
remained. The fix now clears stale pause metadata once the snapshot no longer
contains actionable permission state, so the public state fails closed instead
of implying a resumable pause that is no longer there. Evidence anchors:
`src/vaultspec_a2a/control/projection.py`,
`src/vaultspec_a2a/control/thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-049 | MEDIUM | `/api/threads/{id}/state` could advertise pending approvals even when checkpoint truth was missing or unavailable
Audit `6` exposed another checkpoint-boundary drift in reconnect snapshots.
`build_thread_state()` in
`src/vaultspec_a2a/control/thread_state_service.py` loaded durable pending
permission state before probing the LangGraph checkpoint, but its
checkpoint-missing and checkpoint-unavailable paths only degraded
`repair_status` and `execution_readiness`. That meant
`/api/threads/{id}/state` could still return `pending_permissions`,
`approval_status="pending"`, `approval_request_id`, and `pause_cause` even
while the snapshot itself declared checkpoint truth unavailable. LangGraph
interrupt semantics do not support that optimistic contract: resumability is
anchored in the persisted checkpoint for the same `thread_id`, so durable
permission residue alone is not enough to advertise a still-actionable human
pause. The fix now fails closed on that boundary by clearing public
permission/approval state when checkpoint truth is missing or unavailable,
using a shared cleanup helper in `src/vaultspec_a2a/control/projection.py`.
Evidence anchors:
`src/vaultspec_a2a/control/thread_state_service.py`,
`src/vaultspec_a2a/control/projection.py`,
`src/vaultspec_a2a/api/tests/test_thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-050 | HIGH | Hard delete eligibility still allowed destructive deletion of `input_required` paused/resumable threads
Audit `6` exposed a destructive lifecycle-guard drift. The delete predicate in
`src/vaultspec_a2a/thread/lifecycle_guards.py` only blocked `running`, so the
REST delete path could still hard-delete an `input_required` thread even when
that state represented real durable paused work with checkpoint-backed
resumability and a live pending permission row. This repo already treats that
state as operator-actionable durable work in restart reconciliation and the
service permission lanes, so allowing hard delete there was an outright
contract breach rather than a documentation mismatch. The fix now fails closed:
hard delete is restricted to terminal or archived states, and paused/resumable
work must be resolved, cancelled, or repaired before it can be destroyed.
Evidence anchors:
`src/vaultspec_a2a/thread/lifecycle_guards.py`,
`src/vaultspec_a2a/api/routes/threads.py`,
`src/vaultspec_a2a/thread/tests/test_lifecycle_guards.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-051 | HIGH | Follow-up messaging still bypassed `repair_needed` and `reconciling` recovery gates
Audit `6` exposed another operator-action drift at the message boundary.
`POST /api/threads/{id}/messages` was still allowed for `repair_needed` and
`reconciling` threads because `can_send_followup()` only blocked
`input_required` and terminal/archive states. That let new user work race or
overwrite explicit repair/recovery states whose whole purpose is to prevent
normal interaction until checkpoint truth and execution state are trustworthy
again. In this repo, `repair_needed` is the durable fail-closed state for
checkpoint loss or untrusted recovery, and `reconciling` already has a
dedicated redispatch path; neither is a safe target for ordinary follow-up
ingest. The fix now rejects both states at the pure message-policy boundary,
which keeps the REST message endpoint aligned with the stricter repair
contract. Evidence anchors:
`src/vaultspec_a2a/thread/message_policy.py`,
`src/vaultspec_a2a/control/message_service.py`,
`src/vaultspec_a2a/thread/tests/test_message_policy.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-052 | MEDIUM | MCP `delete_thread` leaked raw backend 409 conflicts after non-terminal delete hardening
Audit `6` exposed a surface-alignment gap after the stricter delete contract
landed. REST `DELETE /api/threads/{id}` now correctly fails closed for
non-terminal threads, but the MCP `delete_thread` tool still surfaced that
backend `409 Conflict` as a raw HTTP failure instead of a usable `ToolError`.
That left the MCP operator surface behind the backend lifecycle contract and
obscured the real reason the delete was rejected. The fix now maps backend
`409` responses into `ToolError`, preserves the backend detail when available,
and updates the tool docs so non-terminal rejection is explicit at the MCP
boundary. Evidence anchors:
`src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-052 | MEDIUM | MCP `delete_thread` still leaked raw backend conflicts after delete hardening
Audit `6` exposed a tool-surface drift immediately after the stricter delete
contract landed. The REST delete path now rejects non-terminal threads with
`409`, but `src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py` was
still letting that backend conflict escape as a raw HTTP failure instead of a
usable `ToolError`. That left the MCP surface lagging behind the backend
contract it fronts. The fix now maps delete-side `409` conflicts into a clear
`ToolError` carrying the backend detail, and the MCP tool docs now describe
non-terminal rejection rather than implying only active/running work is
blocked. Evidence anchors:
`src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-053 | MEDIUM | `/api/threads` summaries could advertise pending approvals when checkpoint probing was unverified
Audit `6` still had a checkpoint-authority drift on the thread-summary
surface. `/api/threads/{id}/state` was already failing closed when checkpoint
truth was missing or unavailable, but `list_threads_service()` in
`src/vaultspec_a2a/control/thread_service.py` still preserved
`approval_status="pending"` and `approval_request_id` from durable rows even
when the checkpointer probe itself timed out or raised. Under LangGraph
interrupt and durable-execution semantics, resumability is checkpoint-backed
for the same `thread_id`; a durable permission row alone is not enough to
advertise a still-actionable human approval when checkpoint truth is
unverified. The fix keeps the summary surface aligned with the stricter
thread-state contract by degrading readiness to `checkpoint_unavailable` and
clearing public approval metadata on that boundary. Evidence anchors:
`src/vaultspec_a2a/control/thread_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-054 | MEDIUM | MCP `send_message` leaked raw backend 409 conflicts for repair-state threads
Audit `6` still had an operator-surface drift at the MCP messaging boundary.
The backend follow-up path already rejects `repair_needed` and `reconciling`
threads with `409 Conflict`, but `send_message()` in
`src/vaultspec_a2a/protocols/mcp/tools/messaging.py` was still letting that
conflict escape as a generic HTTP error. That made the MCP surface lag behind
the stricter repair-state contract and obscured the real reason the follow-up
was rejected. The fix now maps backend `409` responses into `ToolError`,
preserves the backend detail when available, and keeps MCP messaging aligned
with the fail-closed repair contract already enforced by the REST endpoint.
Evidence anchors:
`src/vaultspec_a2a/protocols/mcp/tools/messaging.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-055 | MEDIUM | MCP `respond_to_permission` leaked stale permission conflicts as raw HTTP failures
Audit `6` still had a permission-control surface lag at the MCP boundary.
The backend permission-response path already rejects stale or superseded
permission requests with `409 Conflict`, but `respond_to_permission()` in
`src/vaultspec_a2a/protocols/mcp/tools/discovery.py` was still relying on the
generic request helper and leaking that conflict as a raw HTTP failure. That
left the MCP permission surface behind the stricter backend contract and hid
the real operator-facing reason the response was rejected. The fix now maps
backend `409` responses into `ToolError`, preserves backend detail when
available, and keeps MCP permission response handling aligned with the
existing stale-request protection already enforced by the REST endpoint.
Evidence anchors:
`src/vaultspec_a2a/protocols/mcp/tools/discovery.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-056 | MEDIUM | `/api/team/status` could surface non-actionable durable permission residue as live work
Audit `6` still had a persistence-residue leak on the team-status surface.
`build_team_status()` in `src/vaultspec_a2a/control/team_service.py` already
filtered terminal threads, but it still treated all other durable permission
rows as public pending work. That left two non-actionable cases leaking
through: orphaned rows whose owning `ThreadModel` no longer existed, and rows
owned by threads already degraded to `checkpoint_unavailable`, where this
repo already treats pending approvals as non-actionable until checkpoint truth
is restored. The fix now requires a live non-terminal owner row and hides
public pending permissions for checkpoint-unavailable threads, keeping
persistence residue and checkpoint-unverified pauses from masquerading as
actionable work on the REST and MCP discovery surfaces.
Evidence anchors:
`src/vaultspec_a2a/control/team_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-057 | MEDIUM | MCP `get_thread_status` hid checkpoint-authority degradation behind raw thread status
Audit `6` still had a public/operator-state drift on the MCP thread-query
surface. `get_thread_status()` in
`src/vaultspec_a2a/protocols/mcp/tools/thread_query.py` rendered only the raw
thread `status`, so a degraded thread could still look like an ordinary
`input_required` pause even when the API had already classified it as
`checkpoint_unavailable` and therefore non-actionable. The fix now renders
`repair_status` and `execution_readiness` directly in the MCP tool output so
operators can distinguish resumable pauses from checkpoint-unverified repair
states without guessing from the absence of pending permissions.
Evidence anchors:
`src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

REVIEW-058 | MEDIUM | Submitted thread-state snapshots could leak stale approval residue before any checkpoint existed
Audit `6` still had a boundary hole on `/api/threads/{id}/state`. The
snapshot builder already failed closed when checkpoint truth was missing for
non-submitted threads, but it exempted `submitted` threads unconditionally.
That allowed a corrupted or stale durable `approval_status` and permission row
to surface on a never-started thread even though no checkpoint-backed pause had
ever been created. The fix now keeps the `submitted` exemption only for clean
threads; if a submitted thread carries pending-permission or approval residue
without checkpoint truth, the snapshot clears that state and marks the
degraded reason instead of advertising a non-existent actionable pause.
Evidence anchors:
`src/vaultspec_a2a/control/thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_thread_state_service.py`,
`src/vaultspec_a2a/api/tests/test_endpoints.py`.

REVIEW-059 | LOW | MCP guidance still implied `input_required` always meant an actionable approval
Audit `6` reached the operator-guidance edge after the underlying state
surfaces were hardened. The MCP server instructions and permission-discovery
help text still implied that `status == input_required` alone meant a live
permission response was available, even though this audit now distinguishes
checkpoint-backed resumable pauses from checkpoint-unavailable repair states.
The guidance is now aligned with the actual contract: operators are told to
inspect repair/readiness first and to treat `get_pending_permissions()` as the
source of currently actionable approvals rather than assuming every
`input_required` thread can be resumed immediately.
Evidence anchors:
`src/vaultspec_a2a/protocols/mcp/server.py`,
`src/vaultspec_a2a/protocols/mcp/tools/discovery.py`.

REVIEW-060 | MEDIUM | MCP `list_threads` still hid checkpoint-authority degradation behind raw status
Audit `6` still had an operator-state drift on the MCP discovery surface.
`list_threads()` in `src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`
was rendering only raw thread `status`, which could make a degraded thread
look like an ordinary resumable pause even when the underlying REST summary
had already classified it as `checkpoint_unavailable` or
`needs_reconciliation`. The fix now surfaces `repair_status` and
`execution_readiness` in the MCP listing so operators can distinguish
checkpoint-backed resumability from degraded repair states before they try to
interact with the thread.
Evidence anchors:
`src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`,
`src/vaultspec_a2a/protocols/mcp/tests/test_server.py`.

Audit 6 closeout
After `REVIEW-060`, no stronger persistence/public-state or operator-surface
drift is obvious. Audit `6` has been burned down to the point where the
remaining surfaces are aligned with the checkpoint-first contract: durable
residue no longer masquerades as actionable work, and MCP discovery now
exposes checkpoint-authority degradation instead of hiding it behind raw
status. The next active fronts are Audit `5` supervisor plan-approval
certification and Audit `7` multi-agent cooperation and re-briefing.

Audit 5 slice 1
The first supervisor-certification slice hardens the existing real-stack
service scenario instead of introducing a new synthetic path. The service test
now proves that the first pause is supervisor-owned plan approval with the
expected pause cause, approval metadata, tool call, and option set, and that
the later worker-owned permission pause is distinct and still controllable.
This keeps Audit `5` focused on certifying the supervisor boundary itself
rather than merely observing eventual completion after two generic pauses.

REVIEW-061 | MEDIUM | Supervisor plan-approval service certification still treated the first pause like a generic permission
Audit `5` now starts with a service-certification tightening pass rather than a
new harness. The real-stack supervisor approval scenario was already proving
that the thread could eventually complete after two pauses, but it was not yet
asserting the first pause as a supervisor-owned `plan_approval_request`
boundary. The service test now validates the first pause directly via
`pause_cause`, `approval_status`, `approval_request_id`, `tool_call`, and the
expected approve/reject option set, then asserts the later worker-owned
permission pause separately so the supervisor boundary is not conflated with
generic worker permission handling.
Evidence anchors:
`src/vaultspec_a2a/service_tests/test_permissions_resume.py`,
`src/vaultspec_a2a/graph/nodes/supervisor.py`,
`src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`.

AUDIT-6 CLOSEOUT | Persistence/public-state burn-down is functionally complete
After `REVIEW-060`, no stronger persistence/public-state or operator-surface
drift remained obvious in the audited REST, MCP, team-status, thread-state,
summary, health, and lifecycle surfaces. The remaining work is no longer about
hidden checkpoint-authority leaks on public state; the next active fronts move
up a layer to supervisor plan-approval certification and then multi-agent
cooperation/re-briefing behavior.

AUDIT-6-CLOSEOUT | NOTE | No stronger persistence/public-state defect remained after REVIEW-060
The final Audit `6` closeout scan did not expose a stronger remaining defect
across the audited public/operator surfaces: REST thread state, REST thread
summaries, team status, MCP thread queries, MCP discovery, readiness health,
and lifecycle public gates. The remaining material risks have shifted to the
next roadmap domains rather than checkpoint-authority drift: supervisor
plan-approval certification, multi-agent cooperation and re-briefing, sandbox
and artifact behavior, and streaming/trace lineage.
