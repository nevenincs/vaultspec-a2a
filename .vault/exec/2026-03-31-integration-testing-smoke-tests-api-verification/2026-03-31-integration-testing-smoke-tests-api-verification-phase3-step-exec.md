---
tags:
  - '#exec'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
modified: '2026-03-31'
related:
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-plan]]'
---

# `integration-testing-smoke-tests-api-verification` phase-3 scenarios

Added the certifying real-stack scenarios for lifecycle, permission, SSE replay, cancel, health, and traces.

- Created: `src/vaultspec_a2a/service_tests/test_lifecycle.py`
- Created: `src/vaultspec_a2a/service_tests/test_permissions_resume.py`
- Created: `src/vaultspec_a2a/service_tests/test_stream_followup.py`
- Created: `src/vaultspec_a2a/service_tests/test_cancel_health_trace.py`
- Created: `src/vaultspec_a2a/api/routes/thread_stream.py`
- Created: `src/vaultspec_a2a/ipc/tests/test_serializers.py`

## Description

Phase 3 established the public certification scenarios over real HTTP and SSE. The suite now proves lifecycle completion, pause and approval control, terminal replay semantics for completed threads, cancellation, backend health, and trace export. The permission path was strengthened so the resumed worker performs a real deterministic second provider turn instead of emitting a fabricated completion message, which lets the suite assert meaningful post-approval output.

## Tests

Scenario coverage was verified with `uv run pytest -m service src/vaultspec_a2a/service_tests -q` and `uv run pytest src/vaultspec_a2a/ipc/tests/test_serializers.py -q`. The permission flow was additionally checked against the live stack to confirm the final assistant message carries deterministic completion text from the provider path.
