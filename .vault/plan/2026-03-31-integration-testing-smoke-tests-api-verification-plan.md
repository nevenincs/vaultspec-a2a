---
tags:
  - '#plan'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
related:
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-adr]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-research]]'
  - '[[2026-03-31-integration-testing-service-certification-research]]'
  - '[[2026-03-30-service-layer-research]]'
  - '[[2026-03-30-service-layer-rolling-audit]]'
  - '[[2026-03-20-service-lifecycle-architecture-adr]]'
  - '[[2026-03-31-decoupled-mockllm-adr]]'
---

# `integration-testing-smoke-tests-api-verification` implementation plan

Restore a small, trustworthy service-certification path for issue `#17`.
The goal is to prove the refactored architecture can run end-to-end against
the local stack without errors, remain controllable during execution, and
produce meaningful observable work that developers can trust. This plan keeps
the deterministic service gate separate from any live-provider compatibility
smoke.

## Mission Statement

This work is aimed at deterministic, stable, repeatable, controllable,
and predictable output from the real pipeline and its full stack, with
VidaiMock as the certification provider surface. The intent is not to
prove only that the code executes, but that the live system can be
driven through exact file contents, interactive workflows, cancellation,
resumption, steering, re-briefing, and hostile permission conditions
while continuing to behave in a meaningful and observable way.

The certification gate should prefer exact, repo-owned file inputs and
explicit operator actions over implicit behavior or magic fixtures. Its
success condition is that the stack remains runnable, observable,
interactable, and controllable throughout the scenario, and produces the
same expected outcomes when the tested conditions are held constant.

## Proposed Changes

Build a real-stack certification tier around the existing `service` marker.
The certifying path should use real gateway and worker processes, durable
persistence, deterministic provider replay, SSE verification, and trace
verification. It must reject the current `ASGITransport`-style boundary
collapse as insufficient for this issue.

The implementation should start with the smallest stack that can prove the
feature:

- gateway
- worker
- deterministic mock provider backend
- Jaeger
- SQLite persistence

Postgres and live provider compatibility smoke remain separate extensions, not
prerequisites for the first green certification gate.

## Tasks

- **Phase 1 — Restore the certifying local topology**
  1. Reintroduce an owned integration topology for the service suite so the
     gateway, worker, deterministic provider backend, and Jaeger can be
     started together from the repository.
  1. Define the service-test environment contract so the stack can force the
     deterministic provider path and use isolated persistence and checkpoint
     state per run.
  1. Keep the topology aligned with the current `service/` layout and
     document the exact stack shape used by the certification suite.
  1. Confirm the stack can start, become healthy, and remain addressable over
     real sockets before any scenario tests run.

- **Phase 2 — Build the service test harness**
  1. Add the `service`-scoped test harness entry point and session-scoped
     stack fixture that owns startup, readiness checks, teardown, and artifact
     capture.
  1. Make readiness fail hard if the gateway, worker, deterministic provider,
     or Jaeger cannot be reached.
  1. Capture logs, health payloads, and partial stream events on failure so a
     failed run is diagnosable without rerunning manually.
  1. Ensure trace export has a real flush path so the suite can verify that
     the distributed trace pipeline actually emitted data.
  1. Keep the harness explicit about runtime control: start, wait, interact,
     assert, and stop cleanly every run.

- **Phase 3 — Add certifying scenario tests**
  1. Add the full thread lifecycle scenario over public HTTP, including create,
     dispatch, polling, and terminal-state verification.
  1. Add an SSE scenario that consumes the real stream and asserts semantic
     milestone events through completion.
  1. Add the permission approval scenario that proves pause, user response, and
     resume are all controllable through the public API.
  1. Add the cancel scenario and verify the observable transition through the
     terminal cancellation path.
  1. Add the health and trace scenario so the suite proves both backend status
     reporting and at least one end-to-end exported trace.
  1. Add the MCP path only if the current product surface still requires it for
     issue `#17`; otherwise leave it as a follow-up track.
  1. Keep assertions outcome-oriented and resilient: test the workflow result
     and state transitions, not brittle implementation details or full payload
     snapshots.

- **Phase 4 — Add operator-facing commands and docs**
  1. Add a canonical command path for the service suite so developers can run
     the certification gate without ad hoc shell steps.
  1. Document the service stack, the deterministic provider requirement, the
     expected health endpoints, and the trace verification expectations.
  1. Document how to inspect failure artifacts and how to tell whether the
     stack remained controllable during a run.
  1. Call out the live-provider compatibility path as a separate opt-in smoke
     lane, not part of the deterministic certification gate.

- **Phase 5 — Verification and gating**
  1. Prove the new service suite passes as a standalone gate against the real
     stack.
  1. Verify the suite actually exercises sockets, persistence, streaming, and
     observability rather than collapsing back to in-process substitutes.
  1. Confirm the stack can be started, observed, controlled, and shut down
     cleanly throughout the scenario flow.
  1. Keep the existing non-service test tiers intact and ensure the new gate
     does not weaken them.

## Parallelization

Phase 1 and Phase 2 can be prepared together, but the harness must follow the
chosen stack shape. Phase 3 depends on Phase 2 because the scenario tests need
the fixture and diagnostics. Phase 4 can proceed once the stack and harness are
stable. Phase 5 is the final gate and should run after the earlier phases are
merged together in the same branch.

## Verification

Mission success means the repository has a small, repeatable `service` suite
that certifies the real local architecture without errors or exceptions in the
happy path. The proof must include:

- real gateway and worker processes
- deterministic provider execution through the chosen replay backend
- real HTTP and SSE interaction
- observable permission, cancel, and completion flows
- health checks that reflect the actual backend state
- at least one exported trace proving the gateway-to-worker path ran
- clean startup, interaction, and teardown so the stack remains controllable
  and interactable throughout the run

The first pass should fail the PR if it still depends on in-process worker
fixtures, fake provider execution, or unverified trace behavior. Live Claude,
Gemini, OpenAI/Codex, or Zhipu compatibility can be added as a separate opt-in
smoke lane once the deterministic certification gate is stable.

## Follow-On Audit Roadmap

The remaining work should be divided into separate audits rather than
treated as one broad hardening effort. Each audit should have its own
acceptance criteria and its own deterministic service-level checks so
regressions can be isolated quickly and the certification signal remains
stable across future changes.

Progress note:
Audit `2b` is now complete. The human-loop VidaiMock provider no longer
branches on total message count or a fixed resumed-message index. The
repo now uses a file-backed VidaiMock response template that has been
proven against the real compose-backed service lane for approval, denial,
invalid-outcome handling, and readiness probing. This reduces the tape
contract to a simpler repo-owned assumption: the resumed tool result is
serialized as the last message in the provider request.

Progress note:
Audit `2c` is now complete. The worker now has fast LangGraph-native
coverage for the resumed second `ainvoke()` path in
`src/vaultspec_a2a/graph/tests/nodes/test_worker_integration.py`, proving
that approval leads to the expected second provider turn after LangGraph
re-enters the node from the start on resume.

Progress note:
Audit `2d` is now complete. The permission boundary already had fail-closed
coverage for malformed durable option rows, and it now also has explicit
replay coverage for malformed stored rejection payloads in
`src/vaultspec_a2a/api/tests/test_endpoints.py`. Corrupt replay metadata
therefore falls back to current durable permission state and preserves the
same deterministic conflict instead of weakening the control surface.

Progress note:
Audit `3` is now complete. The repository now enforces one active pending
permission request per thread across durable permission state, aggregator
memory, and the permission-response guard. Stale outward-facing request ids
therefore fail closed instead of remaining resumable after a newer interrupt
has taken over the thread.

Progress note:
Audit `4` is now grounded in a concrete replay/bookkeeping correction. The
successful permission-response path now verifies that `permission_response_submitted`
is recorded as both requested and applied after a resume dispatch succeeds,
and the repair transition helper now stamps the applied action correctly in
the durable thread row. That keeps restart and reconciliation logic aligned
with checkpoint truth.

Progress note:
Audit `4` also now covers degraded execution-state persistence after restart.
When the worker only emits a degraded heartbeat and no fresh checkpoint
payload, the repository keeps the last good execution-state snapshot but no
longer refreshes its `recovery_epoch`. That preserves the stale-projection
signal instead of letting an older checkpoint snapshot masquerade as current
after reconciliation has moved the thread into a newer recovery epoch.

Progress note:
Audit `4` now also treats startup reconciliation as checkpoint-first. If a
durable pending permission survives a restart but the checkpoint probe is
missing, the reconciler no longer marks the thread `paused_resumable`. It now
falls through to `repair_needed` / `checkpoint_unavailable`, and the new pure
plus database-backed tests prove that checkpoint truth must still win over a
surviving permission row at startup.

Progress note:
Audit `4` now also degrades dispatch failures through a shared repair
transition. When the worker cannot be reached, the control layer no longer
leaves `repair_status` and `execution_readiness` looking healthy on a failed
thread row. The new `mark_dispatch_failed()` helper stamps
`operator_intervention_required` across message, permission, thread, and
diagnostics failure paths, and the regression tests prove both service
dispatch failures and websocket `mark_thread_failed()` now surface the degraded
state durably.

Progress note:
Audit `4` now also fails closed when the durable execution-state row is
unreadable. LangGraph checkpoint truth still owns replay durability, so a
loaded checkpoint may remain `durable`, but the repo boundary no longer leaves
the snapshot looking healthy when the `thread_execution_state` row is corrupt.
Unreadable execution-state projection now degrades `repair_status` and
`execution_readiness` to `operator_intervention_required`, and both the pure
projection test and the real `AsyncSqliteSaver` thread-state assembly test are
green.

Progress note:
Audit `4` now also treats missing-thread websocket diagnostics as
checkpoint-first. If checkpoint truth cannot be verified, the gateway no
longer reports `THREAD_STATE_DRIFT` just because an orphaned execution-state
row still exists. The missing-thread classifier now returns
`THREAD_STATE_UNVERIFIED` for that condition so operators see backend
uncertainty rather than stale durable residue.

Progress note:
Audit `4` now also covers unreadable durable permission rows in the
reconnect/thread-state path. The state surface no longer crashes or silently
trusts corrupted permission options; it degrades the snapshot, skips the
unreadable permission, and preserves checkpoint-backed replay semantics when
checkpoint truth is available.

Progress note:
Audit `4` also closed a mirrored approval-state leak in that same path.
Unreadable plan-approval rows no longer seed `approval_status` or
`approval_request_id` from raw durable state once the permission itself has
been rejected as unreadable, and stale thread-row approval metadata is now
cleared under the same corruption condition.

Progress note:
Audit `4` now also aligns websocket follow-up rejection with the same
checkpoint-first missing-thread classification used by REST diagnostics.

Progress note:
Audit `4` now also covers stale plan-approval pointers on the `/api/threads`
summary route. The list surface must no longer trust mirrored
`thread.approval_request_id` / `approval_status="pending"` metadata when the
live durable plan-approval row is missing, superseded, or no longer projected
as active. Thread summaries now fail closed and clear stale approval metadata
unless a live projected plan approval still backs that state.

Grounding note:
LangGraph checkpoint and persistence truth remain the authoritative source, so
mirrored repo summary state must not outrank live durable approval state when
those surfaces diverge.

VidaiMock note:
Deterministic request-shape matching remains a versioned provider contract;
this audit slice changes approval-summary projection only, not the certified
request-shape assumptions used by the deterministic service lane.

Progress note:
The containment follow-up is now active as a bounded hygiene slice. Test
fixtures and regressions that previously wrote SQLite/checkpoint scratch data
under developer-home paths or ad hoc repo-root temp directories are being
moved onto pytest-managed scratch roots so the suite stays disposable,
uniform, and bounded by the test runner itself.
Missing-thread send-message rejections no longer flatten to `THREAD_NOT_FOUND`
when checkpoint truth is unavailable; they preserve `THREAD_STATE_UNVERIFIED`
through the websocket adapter too.

Progress note:
Audit `4` now also aligns the `/api/threads` summary surface with the stricter
snapshot contract for corrupt plan-approval state. Thread summaries no longer
echo stale pending approval metadata when the backing plan-approval permission
row is unreadable.

Progress note:
Audit `4` now also fails closed on unreadable durable permission rows during
reconnect snapshot assembly. Corrupted `permission_requests.allowed_options_json`
no longer gets to crash `build_thread_state()` or `/api/threads/{id}/state`.
The unreadable permission is omitted, the snapshot is marked degraded, and
readiness is set to `operator_intervention_required` while checkpoint-backed
replay semantics remain intact.

- Audit 2B1: service-test Docker cleanup hygiene.
  Identify why stale `vaultspec-service-tests-*` compose projects can
  remain running after interrupted or otherwise incomplete sessions,
  classify whether the leak is fixture teardown, startup-failure
  cleanup, or silent `docker compose down` failure, and make the cleanup
  outcome observable in the audit trail before remediation is chosen.
- Audit 2b: VidaiMock tape hardening and template-semantics audit.
  Completed. Keep the certified contract explicit: use VidaiMock-compatible
  file-backed templates, avoid unproven inline branching tricks, and
  require direct provider verification before any future tape change is
  accepted into the deterministic gate.
- Audit 2c: fast worker resumed-second-`ainvoke()` audit.
  Completed. Keep a narrow LangGraph-native test below the service tier so
  regressions in resumed follow-up execution are localized before they reach
  the compose-backed certification lane.
- Audit 2d: malformed durable rejection replay audit.
  Completed. Keep malformed durable option-state coverage and malformed stored
  rejection-payload replay coverage together so the permission API stays
  fail-closed under both corruption modes.
- Audit 1: interrupt, permission, and resume correctness.
  Cover stale approvals, wrong-thread resume, denied approvals,
  malformed approval payloads, repeated resume idempotency, and resume
  eligibility at the repo boundary. Distinguish projected pending
  permission from durably resumable state, and require the public state
  and permission-response path to agree before a thread is treated as
  safely resumable.
- Audit 3: active-interrupt binding.
  Completed. Keep binding of permission responses to the correct currently active
  interrupt for the thread, prevention of stale request replay across newer
  pauses, and proof that the gateway/control boundary applies responses only
  to the live interrupt contract rather than to a projected or superseded
  request surface. Treat mirrored active-request logic across durable state,
  aggregator memory, and reconnect projection as an explicit regression risk.
- Audit 4: persistence, corruption, and restart resumability.
  Cover checkpoint replay, restart after interruption, degraded
  snapshots, and corruption surfacing instead of silent repair. The
  applied repair transition for a successful permission response is now
  recorded correctly, and degraded-only execution-state updates now keep
  stale recovery epochs visible instead of masking them. Startup
  reconciliation now remains checkpoint-first when a pending permission
  row survives a restart, so the restart lineage stays aligned with the
  durable resume outcome.
  The same audit also covers mirrored follow-up bookkeeping drift: the
  follow-up success path now distinguishes `message_followup_requested`
  from `message_followup_applied`, and the pure repair-policy mapping now
  keys the applied phase off the applied enum.
  It also now covers unreadable durable execution-state rows: checkpoint
  replay remains authoritative, but corrupted execution-state projection
  must still degrade public readiness to `operator_intervention_required`
  instead of inheriting a healthy durable row.
  The same checkpoint-first rule now also applies to missing-thread websocket
  diagnostics: when checkpoint truth cannot be verified, orphaned execution
  state must not be surfaced as drift with stronger certainty than the
  backend can actually provide.
  The audit also now covers unreadable durable permission rows: malformed
  permission option payloads in the DB must degrade the reconnect snapshot to
  `operator_intervention_required` rather than crashing state assembly or
  leaving the thread looking healthy.
  It also now covers mirrored approval metadata: unreadable plan-approval
  rows must not create a pending approval surface when the corresponding
  permission could not be projected safely.
  The same checkpoint-first rule now also applies to websocket follow-up
  rejection: protocol translation must preserve `THREAD_STATE_UNVERIFIED`
  rather than collapsing missing-thread uncertainty to a generic not-found
  error.
  The audit also now covers summary-surface consistency: `/api/threads` must
  not expose pending approval metadata that the reconnect snapshot has already
  rejected as unreadable or corrupt.
  The same corruption handling now also applies to unreadable durable
  permission rows used only for public state projection: malformed option JSON
  must degrade and fail closed, not take down the reconnect/state surface.
  The same anti-mirroring rule now also applies to plan approval pointers:
  live pending plan-approval rows must outrank stale `thread.approval_request_id`,
  and stale pending approval metadata must clear when no projected plan
  approval remains.
- Audit 5: supervisor plan-approval service certification.
  Cover the full supervisor approval path: streamed `plan_approval_request`,
  durable pending permission creation, reconnect-safe response acceptance, and
  proof that approved supervisor work resumes exactly once after interruption.
  The first fast slice is now in place: `plan_approval_request` is treated as a
  durable request-creation event, and HTTP coverage now proves
  `/internal/events` can relay a real supervisor approval request that
  `/api/permissions/{id}/respond` accepts successfully.
  The compose-backed service certifier is now also in place and green. It
  exercises the real supervisor plan approval pause, the worker-owned
  permission pause, and the final completion path against the deterministic
  VidaiMock-backed stack. The supporting fixes preserve supervisor mock
  identity during provider resolution, decode VidaiMock string-wrapped stream
  chunks correctly, probe both supervisor and worker mock routes during stack
  readiness, and keep the supervisor tape on a terminating `FINISH` branch
  once the approved worker output indicates completion.
  The compose-backed certification follow-up is now also in place: supervisor
  model resolution passes the supervisor `agent_config`, restoring selection of
  the `vaultspec-supervisor` mock tape, and `MockChatModel` now decodes the
  string-wrapped JSON stream chunks emitted on the supervisor route instead of
  dropping them. Verification passed in targeted compiler coverage, targeted
  mock provider parsing coverage, and `uv run pytest -m service
  src/vaultspec_a2a/service_tests -q`, which now passes with 10 service tests.
- Audit 6: persistence and state-corruption audit.
  Cover checkpoint replay, restart after interruption, degraded snapshots,
  corrupt durable rows, stale durable lineage, and operator-visible
  degradation instead of silent repair.
  The first stale-lineage slice is now in place: reconnect snapshots and
  `/api/threads/{id}/state` no longer inherit a healthy surface from a
  readable-but-stale `thread_execution_state` row. When durable
  execution-state lineage no longer matches the active `recovery_epoch` or
  checkpoint id, the repository now fails closed to `needs_reconciliation`
  and keeps `execution_state_projection_stale` visible instead of preserving
  `healthy` readiness.
  The next stale-lineage summary slice is now also in place: `/api/threads`
  and the MCP-backed list-thread surface no longer echo healthy readiness from
  the thread row when the durable execution-state row carries an older
  `recovery_epoch`. Summary `repair_status` and `execution_readiness` now stay
  aligned with the stricter reconnect contract and fail closed to
  `needs_reconciliation` under stale durable lineage.
- Audit 6.1: durable-versus-checkpoint pending-permission overwrite audit.
  Cover the boundary where durable pending permission rows and checkpoint or
  aggregator-derived reconnect state are merged. Durable supervisor plan
  approvals are allowed to persist with `tool_call = NULL`, and the supervisor
  interrupt path emits exactly that shape, so thread-state reconstruction must
  not key plan-approval identity on `tool_call` or let checkpoint enrichment
  erase already-durable pending permissions.
  Review-driven follow-up is now also in place on the permission boundary:
  durable supervisor plan approvals created without `tool_call` remain
  actionable during thread-state reconstruction, and checkpoint enrichment no
  longer overwrites durable pending permissions with thinner checkpoint-only
  state. The reconnect/state surface now preserves those pending approvals by
  durable `request_id` until an explicit durable resolution event supersedes
  them.
  The next operator-surface slice is now also in place: `/api/team/status` and
  the MCP-backed team-status tools no longer hide a durably paused thread just
  because heartbeat and aggregator memory are empty after a restart-like gap.
  Team status now treats durable pending-permission thread ids as active so
  the operator view stays aligned with persisted approval truth.
  The next retryability slice is now also in place: failed resume dispatch no
  longer leaves the permission boundary in a contradictory state where the
  durable row looks pending again but the thread itself stays terminal
  `failed`. The repository now restores the durable permission row to
  `pending`, retires the failed control-action idempotency key to a tombstone
  value, and keeps the thread in retryable `input_required` while repair
  readiness remains degraded for operators.
- Audit 7: multi-agent cooperation and re-briefing audit.
  Cover supervisor routing, stale-context prevention, re-brief on state
  change, and no-double-route guarantees during collaborative work.
- Audit 8: sandbox, artifact, and hostile-environment audit.
  Cover non-permitted actions, approval refusal paths, bounded file access,
  destructive-action gating, artifact persistence/removal, and sandbox-owned
  output boundaries.
- Audit 9: streaming, replay, and trace-lineage audit.
  Cover SSE reconnect, ordered event replay, terminal replay, tool-call chunk
  continuity, and gateway-to-worker-to-persistence trace lineage across replay
  and completion.

Verification note:
Audit `3` has focused fast coverage and the compose-backed permission/resume
service lane is green again in the current session. Audit `4` should keep using
that service lane as a guardrail while the broader restart and persistence
cases are added.

Audit `5` now has both its fast and compose-backed guardrails. Supervisor-
originated `plan_approval_request` events are durably persisted and respondable
through the real `/internal/events` -> `/api/permissions/{id}/respond`
boundary, and the deterministic local stack now certifies the full supervisor
approval -> worker approval -> completion path.

## Resume Eligibility Clarification

LangGraph guarantees checkpoint-backed interrupt state, resumed through
`Command(resume=...)`, and replays from the start of the interrupted node
rather than the same source line. This repository adds a second
requirement at the service boundary: a thread is not durably resumable
until the durable permission row, freshness classification, and projected
public state all agree on resume eligibility.

Implementation and verification work for the permission/resume slice
should therefore:

1. Distinguish projected pending permission from durably resumable state.
1. Refuse to treat `pending_permissions` alone as proof that resume is
   safe to submit.
1. Add deterministic service coverage that exercises the projection versus
   durability race and proves the thread is only treated as resumable once
   those boundaries converge.

## REVIEW-032: failed resume-dispatch rollback drift

Keep a bounded Audit `6` slice for failed resume-dispatch retryability. The
implementation must leave the durable permission row re-actionable after an
unreachable worker response, retire the failed control-action idempotency key
without reusing it, and avoid leaving the thread in a terminal state that
blocks retry. The intended retry state is `input_required`, while the restored
durable permission state is `pending`.

Scope and evidence:

- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/database/permission_repository.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "failed_resume_dispatch_restores_permission_to_pending or rejects_permission_request_when_thread_terminal or stale_permission_request_when_newer_interrupt_exists"`
- `uv run pytest src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py -q`
- `uv run pytest src/vaultspec_a2a/service_tests/test_permissions_resume.py -q -m service`
- `uv run ruff check src/vaultspec_a2a/database/permission_repository.py src/vaultspec_a2a/database/__init__.py src/vaultspec_a2a/control/permission_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-033: stale execution-state public-surface drift

Keep a bounded Audit `6` slice for stale execution-state public-surface drift.
The implementation must ensure that `/api/threads/{id}/state` fails closed
before stale execution-state fields are merged, and that `/api/threads`
summaries consult checkpoint truth as well as `recovery_epoch`. The intended
stale-lineage outcome is `needs_reconciliation` with `snapshot_complete=false`
and `execution_state_projection_stale` visible to operators.

Scope and evidence:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/api/routes/threads.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k stale_execution_state_degrades_snapshot_readiness`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_degrades_stale_execution_state_lineage or list_threads_degrades_stale_execution_state_lineage or list_threads_degrades_checkpoint_mismatched_execution_state"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "list_threads_degrades_stale_execution_state_summary or list_threads_degrades_checkpoint_mismatched_summary"`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/control/thread_service.py src/vaultspec_a2a/api/routes/threads.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-034: team-status ghost pending-permission drift

Keep a bounded Audit `6` slice for team-status ghost pending-permission drift.
The implementation must ensure that `/api/team/status` is durable-first for
pending permissions, with `build_team_status()` sourcing pending entries only
from DB-backed `get_pending_permission_requests()`. Aggregator state may
continue to supply `agents` and `active_threads`, but it must not invent
permission truth. The intended outcome is durable-backed pending permissions
only, with ghost permissions excluded from the public surface.

Scope and evidence:

- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/api/routes/teams.py`
- `src/vaultspec_a2a/api/schemas/rest.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "TestTeamStatus"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "team_status_lists_durable_pending_permission_thread_as_active or team_status_excludes_aggregator_only_pending_permission or get_pending_permissions_empty"`
- `uv run ruff check src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-035: websocket failure terminal-cleanup drift

Keep a bounded Audit `6` slice for WS failure terminal-cleanup drift. The
implementation must ensure that WebSocket dispatch failure reuses the
canonical terminal cleanup path, expiring durable pending permissions and
pruning aggregator pending-permission state before the thread remains terminal
`FAILED` with `operator_intervention_required` readiness.

Scope and evidence:

- `src/vaultspec_a2a/api/ws_dispatch.py`
- `src/vaultspec_a2a/control/diagnostics.py`
- `src/vaultspec_a2a/control/event_handlers.py`
- `src/vaultspec_a2a/database/permission_repository.py`

Verification:

- `uv run pytest src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py -q`
- `uv run ruff check src/vaultspec_a2a/control/diagnostics.py src/vaultspec_a2a/api/ws_dispatch.py src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py`

## REVIEW-036: failed cancel dispatch durable-state rollback

Keep a bounded Audit `6` slice for cancel-path durable-state rollback. The
implementation must ensure that a failed worker cancel dispatch does not leave
the thread row advertising `cancel_pending` when the API returned 502 /
`accepted=False`. The durable repair row must restore the pre-cancel repair
state, including `repair_status`, `execution_readiness`, `repair_reason`, and
`last_requested_action`, so persistence stays consistent with the caller-facing
cancel outcome.

Scope and evidence:

- `src/vaultspec_a2a/control/cancel_service.py`
- `src/vaultspec_a2a/control/repair_transitions.py`
- `src/vaultspec_a2a/api/routes/cancel.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "failed_cancel_dispatch_restores_repair_state"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "cancel_thread_cancels_running_thread or cancel_thread_repeat_request_stays_accepting_until_terminal_event"`
- `uv run ruff check src/vaultspec_a2a/control/cancel_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-037: startup reconciliation must fail closed on missing checkpoint truth

Keep this as a bounded Audit `6` guardrail. Restart reconciliation must not
preserve `cancel_pending` when checkpoint probing failed. The implementation
requirement is explicit ordering: `checkpoint_available=False` must beat a
surviving `status="cancelling"` so restart state degrades to `repair_needed` /
`checkpoint_unavailable`.

Scope and evidence:

- `src/vaultspec_a2a/lifecycle/reconciliation.py`
- `src/vaultspec_a2a/database/reconciliation.py`
- `src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py`
- `src/vaultspec_a2a/database/tests/test_reconciliation.py`

Verification:

- `uv run pytest src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py -q -k "cancelling"`
- `uv run pytest src/vaultspec_a2a/database/tests/test_reconciliation.py -q -k "cancelling_without_checkpoint"`
- `uv run ruff check src/vaultspec_a2a/lifecycle/reconciliation.py src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py src/vaultspec_a2a/database/tests/test_reconciliation.py`

## REVIEW-038: thread-state snapshots must not expose aggregator-only pending permissions

Keep this as a bounded Audit `6` guardrail. `/api/threads/{id}/state` must not
surface pending permissions unless a durable permission row exists. The
implementation requirement is simple: aggregator state may still inform agents,
tool calls, and liveness, but pending permission truth for reconnect snapshots
must remain durable-backed only.

Scope and evidence:

- `src/vaultspec_a2a/control/snapshot.py`
- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "aggregator_only_pending_permission_does_not_surface_in_thread_state or plan_approval_without_tool_call_preserves_pending_approval"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_excludes_aggregator_only_pending_permission or state_preserves_plan_approval_without_tool_call"`
- `uv run ruff check src/vaultspec_a2a/control/snapshot.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-039: `/api/health` must probe real checkpoint usability

Keep this as a bounded Audit `6` guardrail. Gateway readiness must not certify
the checkpoint subsystem from handle presence alone. The implementation
requirement is fail-closed health: if the checkpointer backend cannot answer a
lightweight probe, `/api/health` must report checkpoint `error` and overall
status `degraded`.

Scope and evidence:

- `src/vaultspec_a2a/control/health.py`
- `src/vaultspec_a2a/api/routes/health.py`
- `src/vaultspec_a2a/api/tests/test_app.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_app.py -q -k "api_health_degrades_when_checkpointer_backend_is_unusable or api_health_reports_sqlite_fallback_diagnostics"`
- `uv run ruff check src/vaultspec_a2a/control/health.py src/vaultspec_a2a/api/tests/test_app.py`

## REVIEW-040: `/api/threads` summaries must fail closed when checkpoint probing is unverified

Keep this as a bounded Audit `6` guardrail. Thread summaries must not certify
healthy execution readiness if checkpoint probing timed out or raised. The
implementation requirement is fail-closed summaries: when checkpoint usability
is unverified, `/api/threads` must degrade `repair_status` and
`execution_readiness` to `checkpoint_unavailable`.

Scope and evidence:

- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "list_threads_degrades_when_checkpoint_probe_is_unverified"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "list_threads_degrades_when_checkpoint_probe_is_unverified"`
- `uv run ruff check src/vaultspec_a2a/control/thread_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-041: `/api/threads/{id}/state` must not expose checkpoint-only pending permissions as actionable

Keep this as a bounded Audit `6` guardrail. Thread-state snapshots may surface
checkpoint pause truth, but they must not advertise pending permissions unless
the request id is durably pending in the gateway-owned permission table. The
implementation requirement is a post-checkpoint reconciliation step:
checkpoint-projected permissions without a matching durable pending row must be
removed from `pending_permissions`, stale mirrored approval pointers must be
cleared if they depended on the dropped permission, and the snapshot must
degrade with `checkpoint_permission_without_durable_row` rather than silently
overstating actionability.

Scope and evidence:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "checkpoint_only_pending_permission_does_not_surface_in_thread_state or aggregator_only_pending_permission_does_not_surface_in_thread_state or plan_approval_without_tool_call_preserves_pending_approval"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_excludes_checkpoint_only_pending_permission or state_excludes_aggregator_only_pending_permission or state_preserves_plan_approval_without_tool_call"`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/control/thread_state_service.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-042: team-status discovery must hide malformed durable permission rows

Keep this as a bounded Audit `6` guardrail. Team-status and MCP pending
permission discovery must not advertise a request as actionable unless the
durable pending row still exposes at least one usable option id. The
implementation requirement is narrow: retain paused-thread visibility in
`active_threads`, but exclude malformed or optionless durable rows from public
`pending_permissions`.

Scope and evidence:

- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "TestTeamStatus"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "team_status_hides_malformed_durable_pending_permission or team_status_excludes_aggregator_only_pending_permission or team_status_lists_durable_pending_permission_thread_as_active or get_pending_permissions_empty"`
- `uv run ruff check src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-043: team-status discovery must fail closed on terminal-thread permission residue

Keep this as a separate bounded Audit `6` guardrail. Team-status and MCP
discovery must not advertise a pending permission, or promote a thread into
`active_threads`, when the owning durable thread has already reached a terminal
state. The implementation requirement is narrow: reconcile durable pending
permission rows against terminal thread lifecycle before building public
pending-permission discovery, while preserving non-terminal paused-thread
visibility.

Scope and evidence:

- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/thread/enums.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "pending_permissions_exclude_terminal_thread_rows or pending_permissions_hide_malformed_durable_rows"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "get_pending_permissions_excludes_terminal_thread_rows or team_status_excludes_aggregator_only_pending_permission or team_status_hides_malformed_durable_pending_permission"`
- `uv run ruff check src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-044: `/api/threads` summaries must fail closed on optionless or terminal plan approvals

Keep this as a separate bounded Audit `6` guardrail. List-thread summaries must
not expose plan-approval metadata as actionable unless the durable pending row
still has at least one usable option id and the owning thread is non-terminal.
The implementation requirement is narrow: centralize durable option-id
extraction, reuse it in the list-thread summary path, and clear mirrored
approval metadata before reconstruction when the thread has already reached a
terminal lifecycle state.

Scope and evidence:

- `src/vaultspec_a2a/control/permission_options.py`
- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/control/permission_service.py`
- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "list_threads_hides_optionless_plan_approval_metadata or list_threads_clears_terminal_thread_pending_approval"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "list_threads_hides_optionless_plan_approval_summary or list_threads_clears_terminal_pending_approval_summary"`
- `uv run ruff check src/vaultspec_a2a/control/permission_options.py src/vaultspec_a2a/control/permission_service.py src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/control/thread_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-045: terminal-thread state surfaces must fail closed on stale pending permissions

Keep this as a separate bounded Audit `6` guardrail. Thread-state snapshots and
their MCP consumer surfaces must not advertise pending permissions as
actionable once the durable thread lifecycle is already terminal.

Scope and evidence:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "terminal_thread_excludes_durable_pending_permission_from_thread_state or plan_approval_without_tool_call_preserves_pending_approval"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_excludes_terminal_thread_pending_permission_residue or state_preserves_plan_approval_without_tool_call"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "get_thread_state_excludes_terminal_pending_permission_residue"`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-046: public permission reads must not treat answered-not-applied rows as actionable pending state

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic public state: user-facing pending/actionable views must reflect
actionable truth, not internal apply-in-flight residue.

Scope and evidence:

- `src/vaultspec_a2a/database/permission_repository.py`
- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "answered_pending_apply_permission_does_not_surface_in_thread_state"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "list_threads_hides_answered_pending_apply_plan_approval or state_excludes_answered_pending_apply_permission or team_status_excludes_answered_pending_apply_permission"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "list_threads_hides_answered_pending_apply_summary or get_pending_permissions_excludes_answered_pending_apply"`
- `uv run ruff check src/vaultspec_a2a/database/permission_repository.py src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/control/thread_service.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-047: startup reconciliation must not treat answered-not-applied permissions as resumable pending state

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic public/operator state after restart: startup reconciliation must
not relabel internal answered-not-applied apply state as a user-resumable
pending pause.

Scope and evidence:

- `src/vaultspec_a2a/database/permission_repository.py`
- `src/vaultspec_a2a/database/reconciliation.py`
- `src/vaultspec_a2a/lifecycle/reconciliation.py`
- `src/vaultspec_a2a/database/tests/test_reconciliation.py`
- `src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py`

Verification:

- `uv run pytest src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py -q -k "answered_not_applied_does_not_count_as_resumable_pending or pending_permission_transitions_to_input_required"`
- `uv run pytest src/vaultspec_a2a/database/tests/test_reconciliation.py -q -k "answered_pending_apply_with_checkpoint_is_not_marked_resumable or pending_permission_without_checkpoint_is_not_marked_resumable"`
- `uv run ruff check src/vaultspec_a2a/database/reconciliation.py src/vaultspec_a2a/lifecycle/tests/test_reconciliation.py src/vaultspec_a2a/database/tests/test_reconciliation.py`

## REVIEW-048: thread-state snapshots must clear stale pause_cause after actionability is removed

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic public state after projection: once actionable permission
metadata has been cleared, reconnect snapshots must not continue to imply a
paused workflow through stale `pause_cause`.

Scope and evidence:

- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "answered_pending_apply_permission_does_not_surface_in_thread_state or checkpoint_only_pending_permission_does_not_surface_in_thread_state"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_excludes_answered_pending_apply_permission or state_excludes_checkpoint_only_pending_permission"`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-049: thread-state snapshots must not advertise pending approvals without checkpoint truth

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic public/operator state: reconnect snapshots may show degraded
recovery, but they must not present a human pause as actionable when the
LangGraph checkpoint needed for resume is missing or unavailable.

Scope and evidence:

- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/control/projection.py`
- `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_thread_state_service.py -q -k "missing_checkpoint_hides_durable_pending_permission_state"`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "state_hides_pending_approval_when_checkpoint_is_unavailable"`
- `uv run ruff check src/vaultspec_a2a/control/projection.py src/vaultspec_a2a/control/thread_state_service.py src/vaultspec_a2a/api/tests/test_thread_state_service.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-050: hard delete eligibility must fail closed for paused/resumable work

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic, controllable workflow state: hard delete must never erase
`input_required` paused/resumable work before the operator has resolved,
cancelled, or repaired it.

Scope and evidence:

- `src/vaultspec_a2a/thread/lifecycle_guards.py`
- `src/vaultspec_a2a/api/routes/threads.py`
- `src/vaultspec_a2a/thread/tests/test_lifecycle_guards.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/thread/tests/test_lifecycle_guards.py -q`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "rejects_input_required_thread_with_pending_permission"`
- `uv run ruff check src/vaultspec_a2a/thread/lifecycle_guards.py src/vaultspec_a2a/thread/tests/test_lifecycle_guards.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-051: follow-up messaging must fail closed for repair-state threads

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic operator truth: a thread in `repair_needed` or `reconciling`
must not accept ordinary follow-up messages until checkpoint truth and
execution state are trustworthy again.

Scope and evidence:

- `src/vaultspec_a2a/thread/message_policy.py`
- `src/vaultspec_a2a/control/message_service.py`
- `src/vaultspec_a2a/thread/tests/test_message_policy.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`

Verification:

- `uv run pytest src/vaultspec_a2a/thread/tests/test_message_policy.py -q`
- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "test_rejects_followup_while_thread_requires_repair or test_rejects_followup_while_thread_is_reconciling"`
- `uv run ruff check src/vaultspec_a2a/thread/message_policy.py src/vaultspec_a2a/thread/tests/test_message_policy.py src/vaultspec_a2a/api/tests/test_endpoints.py`

## REVIEW-052: MCP delete must fail closed on non-terminal backend conflicts

Keep this as a separate bounded Audit `6` guardrail. The mission is
consistent operator control across surfaces: once the backend delete contract
rejects non-terminal threads, the MCP delete tool must surface that rejection
as a clear tool-level failure rather than leaking a raw HTTP conflict.

Scope and evidence:

- `src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "delete_thread_raises_tool_error_for_nonterminal_thread or archive_thread_raises_tool_error_when_server_unavailable or delete_thread_raises_tool_error_when_server_unavailable"`
- `uv run ruff check src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-053: `/api/threads` summaries must hide approvals when checkpoint probing is unverified

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic public/operator state across layers: if checkpoint probing is
unverified, the summary surface may degrade readiness, but it must not still
advertise a resumable pending approval.

Scope and evidence:

- `src/vaultspec_a2a/control/thread_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "list_threads_hides_pending_approval_when_checkpoint_probe_is_unverified or list_threads_degrades_when_checkpoint_probe_is_unverified"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "list_threads_hides_pending_approval_when_checkpoint_probe_is_unverified or list_threads_degrades_when_checkpoint_probe_is_unverified"`
- `uv run ruff check src/vaultspec_a2a/control/thread_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-054: MCP `send_message` must fail closed on repair-state follow-up conflicts

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic operator tooling: when the backend rejects follow-up messaging
for repair-state threads, the MCP `send_message` surface must return a clear
`ToolError` instead of leaking a raw HTTP conflict.

Scope and evidence:

- `src/vaultspec_a2a/protocols/mcp/tools/messaging.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "send_message_raises_tool_error_for_repair_needed_thread"`
- `uv run ruff check src/vaultspec_a2a/protocols/mcp/tools/messaging.py`

## REVIEW-055: MCP `respond_to_permission` must fail closed on stale-request conflicts

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic operator tooling: once the backend permission-response path
rejects a stale request, the MCP permission surface must return a clear
`ToolError` instead of leaking a raw HTTP conflict.

Scope and evidence:

- `src/vaultspec_a2a/protocols/mcp/tools/discovery.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "respond_to_permission_raises_tool_error_for_stale_request or respond_to_permission_dispatches_for_existing_thread or respond_to_permission_raises_when_server_unavailable"`
- `uv run ruff check src/vaultspec_a2a/protocols/mcp/tools/discovery.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-056: team status must fail closed on non-actionable durable permission rows

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic public/operator state: durable permission residue must not
surface as active work unless a live non-terminal thread row still owns it and
the owning thread remains checkpoint-actionable.

Scope and evidence:

- `src/vaultspec_a2a/control/team_service.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q -k "team_status_excludes_orphaned_durable_permission_rows or team_status_hides_pending_permissions_without_checkpoint_truth or pending_permissions_hide_malformed_durable_rows or pending_permissions_do_not_surface_from_aggregator_without_durable_row"`
- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "team_status_excludes_orphaned_durable_permission_rows or team_status_hides_checkpoint_unavailable_pending_permission or team_status_hides_malformed_durable_pending_permission or team_status_excludes_aggregator_only_pending_permission"`
- `uv run ruff check src/vaultspec_a2a/control/team_service.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-057: MCP thread status must expose repair/readiness, not only raw status

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic operator state: MCP tools must not hide checkpoint-authority
degradation behind a raw `status` field that still looks resumable.

Scope and evidence:

- `src/vaultspec_a2a/protocols/mcp/tools/thread_query.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "get_thread_status_reports_repair_and_readiness or get_thread_status_raises_when_server_unavailable"`
- `uv run ruff check src/vaultspec_a2a/protocols/mcp/tools/thread_query.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

## REVIEW-052: MCP delete must fail closed with a usable tool error on non-terminal threads

Keep this as a separate bounded Audit `6` guardrail. The mission is
deterministic operator tooling: when the backend rejects hard delete for a
non-terminal thread, the MCP surface must return a clear `ToolError` instead
of leaking a lower-level HTTP failure.

Scope and evidence:

- `src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`

Verification:

- `uv run pytest src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q -k "delete_thread_raises_tool_error_for_nonterminal_thread or archive_thread_raises_tool_error_when_server_unavailable or delete_thread_raises_tool_error_when_server_unavailable"`
- `uv run ruff check src/vaultspec_a2a/protocols/mcp/tools/thread_lifecycle.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`
