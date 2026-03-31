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
