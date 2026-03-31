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

REVIEW-001 | MEDIUM | The mock human-loop tape still depends on total message count
`mock-coder-human.yaml` still chooses between permission-request and completion output using the total number of serialized messages. The worker now adds an explicit approval-context message before the resumed provider call to make that deterministic in the current stack, but unrelated prompt-shape growth could still bypass the intended permission path later if the mock tape is reused without care.

REVIEW-002 | MEDIUM | The worker-side mock permission gate lacks a focused fast test
The resumed second provider turn in `worker.py` is currently covered only through the compose-backed service scenarios. A small fast test for the mock permission gate would make regressions in the resume-message construction or second `ainvoke()` path easier to localize than the current slowest-tier coverage.

REVIEW-003 | LOW | Completed-thread SSE replay is still locked down only by the service suite
The one-shot replay behavior in `thread_stream.py` is exercised end to end by the service certification scenario, but there is still no dedicated fast API-level test that asserts the replay payload and immediate close semantics in isolation. The current coverage is sufficient for the service gate but slower to localize if that contract regresses later.

REVIEW-004 | MEDIUM | `service_tests/harness.py` does not verify VidaiMock readiness before certifying the stack
`ServiceStack.wait_for_ready()` checks gateway, worker, and Jaeger readiness, but it never probes the deterministic provider behind `MOCK_API_BASE`. The stack can therefore report "ready" even when VidaiMock is down or misconfigured, and the first model call will fail later instead of failing the service gate up front. Add an explicit provider readiness probe to the harness startup check.

REVIEW-005 | MEDIUM | `test_permissions_resume.py` still misses the deny-path regression for human approval
The new real-stack permission suite proves approve, hostile-option rejection, and stale-response idempotency, but it never exercises the deny option from the `mock-human-in-loop` tape. That leaves the negative human-approval branch of the resume path untested in the only deterministic service slice for audit 1. Add a service-level denial test so regressions in `respond_to_permission()` and the worker resume flow cannot slip through.

REVIEW-006 | LOW | `test_endpoints.py` does not cover malformed durable permission JSON yet
The new unit test labeled "malformed durable permission row" seeds `allowed_options=[]`, which only exercises the empty-list branch of `_allowed_option_ids()`. The malformed JSON/non-list path still has no regression coverage, so a corrupted durable row could regress without a direct test failure. Add one unit test that seeds a bad `allowed_options_json` payload and asserts the same fail-closed 409.
