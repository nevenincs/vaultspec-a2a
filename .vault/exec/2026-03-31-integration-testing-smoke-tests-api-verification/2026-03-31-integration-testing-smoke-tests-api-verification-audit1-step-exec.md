---
tags:
  - '#exec'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
related:
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-plan]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-adr]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-research]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-review-audit]]'
---

# `integration-testing-smoke-tests-api-verification` `audit1` `step`

Completed the first follow-on audit slice for permission, interrupt, and resume hardening.

- Modified: `src/vaultspec_a2a/control/permission_service.py`
- Modified: `src/vaultspec_a2a/api/tests/test_endpoints.py`
- Modified: `src/vaultspec_a2a/service_tests/harness.py`
- Modified: `src/vaultspec_a2a/service_tests/test_permissions_resume.py`

## Description

This slice hardened the durable permission boundary so hostile or malformed resume payloads now fail closed before any resume dispatch reaches the worker. The service now rejects:

- unknown `option_id` values not present in the durable permission request
- durable permission rows that contain no valid options
- stale non-idempotent second responses after the request has already moved out of the pending state
- idempotent replays of previously rejected invalid responses, preserving the same conflict semantics instead of replaying as a false success

The service-suite coverage was extended to prove that the real stack remains controllable after hostile inputs. The service tests now verify that invalid permission responses keep the thread paused, that stale second responses are rejected after a successful resume, and that recovery via a later valid approval still produces the deterministic VidaiMock-backed completion output.

LangGraph grounding for this step came from the official interrupts and durable execution documentation, which reinforces that interrupt/resume correctness depends on persistence-backed state, explicit resume payloads, and idempotent control boundaries. Context7 remained unavailable in this environment because the configured API key was invalid, so the implementation was grounded with the LangGraph/LangChain docs MCP and direct repo inspection instead.

## Tests

Focused verification completed successfully:

- `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py -q`
- `uv run pytest -m service src/vaultspec_a2a/service_tests/test_permissions_resume.py -q`
- `uv run pytest -m service src/vaultspec_a2a/service_tests -q`

Mandatory review completed against the current plan, ADR, research, and existing rolling audit. No new unresolved findings were identified beyond the previously logged tape-brittleness and fast-test gaps already captured in the rolling review audit.
