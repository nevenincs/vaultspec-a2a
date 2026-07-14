---
tags:
  - '#exec'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
modified: '2026-03-31'
related:
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-plan]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-audit2a-step-exec]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-review-audit]]'
---

# `integration-testing-smoke-tests-api-verification` `audit2a` summary

Audit 2a completed the worker-side fail-closed resume validation slice for the deterministic certification lane.

- Modified: `src/vaultspec_a2a/graph/nodes/worker.py`
- Modified: `src/vaultspec_a2a/graph/tests/nodes/test_worker.py`
- Modified: `src/vaultspec_a2a/service_tests/test_permissions_resume.py`
- Modified: `src/vaultspec_a2a/team/presets/mock/tapes/providers/mock-coder-human.yaml`

## Description

The worker no longer coerces malformed LangGraph resume payloads into an allowed permission option. Instead, it validates resumed option ids explicitly and fails closed on unsupported payload types, missing option ids, and unknown option ids. The compose-backed permission suite now certifies both hostile invalid-option recovery and the real denial branch, while the VidaiMock human tape returns stable approval and denial outputs under the same service topology.

## Tests

The focused worker tests, the focused permission service tests, and the full `service` suite all passed after the hardening changes:

- `uv run pytest src/vaultspec_a2a/graph/tests/nodes/test_worker.py -q`
- `uv run pytest src/vaultspec_a2a/service_tests/test_permissions_resume.py -q -m service`
- `uv run pytest -m service src/vaultspec_a2a/service_tests -q`

Review completed with the remaining unresolved risks narrowed to tape brittleness, missing fast coverage for the mock permission second-turn path, and malformed durable permission JSON coverage.
