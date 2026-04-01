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

Residual note after `audit3`:
The active pending permission rule is now enforced consistently across durable
rows, aggregator memory, and the permission-response guard, but this class of
mirrored decision logic remains worth auditing explicitly. If any one of those
surfaces drifts from the others, stale outward-facing request ids can reappear
even while the underlying LangGraph thread-scoped interrupt semantics remain
correct.
