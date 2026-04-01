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

REVIEW-009 | LOW | The VidaiMock human-loop tape still depends on the resumed tool result being serialized as the last message
Audit `2b` removed the brittle message-count and absolute-index contract from `mock-coder-human.yaml` and replaced it with a file-backed VidaiMock template that certifies approval, denial, invalid outcome handling, and readiness against the real compose-backed service lane. The residual contract is narrower but still real: resumed branch selection now assumes the worker-owned tool result remains the last serialized message in the provider request. If future worker prompt assembly appends additional post-tool messages before provider invocation, the tape could need another adjustment even though permission logic itself remains correct. Evidence anchors: `src/vaultspec_a2a/team/presets/mock/tapes/providers/mock-coder-human.yaml`, `src/vaultspec_a2a/team/presets/mock/tapes/templates/mock-coder-human-chat.json.j2`, `src/vaultspec_a2a/providers/mock_chat_model.py`, `src/vaultspec_a2a/graph/nodes/worker.py`.

REVIEW-002 | MEDIUM | The worker-side mock permission gate lacks a focused fast test
The new worker helper tests prove fail-closed resume payload validation, but the resumed second provider turn in `worker.py` is still covered only through the compose-backed service scenarios. A small fast test for the mock permission gate would make regressions in the resume-message construction or second `ainvoke()` path easier to localize than the current slowest-tier coverage.

REVIEW-003 | LOW | Completed-thread SSE replay is still locked down only by the service suite
The one-shot replay behavior in `thread_stream.py` is exercised end to end by the service certification scenario, but there is still no dedicated fast API-level test that asserts the replay payload and immediate close semantics in isolation. The current coverage is sufficient for the service gate but slower to localize if that contract regresses later.

REVIEW-006 | LOW | `test_endpoints.py` does not cover malformed durable permission JSON yet
The new unit test labeled "malformed durable permission row" seeds `allowed_options=[]`, which only exercises the empty-list branch of `_allowed_option_ids()`. The malformed JSON/non-list path still has no regression coverage, so a corrupted durable row could regress without a direct test failure. Add one unit test that seeds a bad `allowed_options_json` payload and asserts the same fail-closed 409.

REVIEW-007 | LOW | Stale `vaultspec-service-tests-*` Docker projects can accumulate silently after interrupted or incomplete sessions
Audit `2B1` found multiple still-running `vidaimock` and `jaeger` compose projects labeled `vaultspec-service-tests-*`, all created from this worktree and still removable with a manual `docker compose ... down -v --remove-orphans`. The service-test harness does call `stack.stop()` on normal fixture teardown and on `start()` exceptions, but `stop()` suppresses `docker compose down` failures with `check=False` and does not record whether teardown actually succeeded. That means aborted pytest runs, interrupted host sessions, or silent compose-down failures can leave infra-only projects behind without surfacing a test failure or an audit artifact. Evidence anchors: `src/vaultspec_a2a/service_tests/conftest.py`, `src/vaultspec_a2a/service_tests/harness.py`. Triaged as low-critical because it is resource hygiene rather than correctness drift, but it should be addressed before the service lane becomes a longer-lived developer gate.

REVIEW-008 | MEDIUM | `pending_permissions` can surface before the thread is durably resumable
The current service surface can expose a projected pending permission before the repository's separate durable permission row and freshness classification make the thread durably resumable. LangGraph is not the source of this gap: its interrupt state is checkpoint-backed, resumed via `Command(resume=...)`, and re-enters the node from the start after the last recorded checkpoint boundary. The risk is at the repo boundary, where projected pending permission is visible ahead of confirmed resume eligibility. `pending_permissions` therefore must not be treated as proof of safe resumability on its own. Evidence anchors: `src/vaultspec_a2a/service_tests/test_permissions_resume.py`, `src/vaultspec_a2a/service_tests/test_stream_followup.py`, `src/vaultspec_a2a/control/permission_service.py`, `src/vaultspec_a2a/control/thread_state_service.py`, `src/vaultspec_a2a/control/projection.py`, `src/vaultspec_a2a/thread/snapshots.py`, `src/vaultspec_a2a/api/routes/thread_state.py`.
