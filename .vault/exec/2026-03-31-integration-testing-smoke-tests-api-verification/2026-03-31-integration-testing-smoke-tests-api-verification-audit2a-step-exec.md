---
tags:
  - '#exec'
  - '#integration-testing-smoke-tests-api-verification'
date: '2026-03-31'
modified: '2026-03-31'
related:
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-plan]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-adr]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-research]]'
  - '[[2026-03-31-integration-testing-smoke-tests-api-verification-review-audit]]'
---

# `integration-testing-smoke-tests-api-verification` `audit2a` `step`

Completed the second follow-on audit slice for worker resume validation and deterministic deny-path certification.

- Modified: `src/vaultspec_a2a/graph/nodes/worker.py`
- Modified: `src/vaultspec_a2a/graph/tests/nodes/test_worker.py`
- Modified: `src/vaultspec_a2a/service_tests/test_permissions_resume.py`
- Modified: `src/vaultspec_a2a/team/presets/mock/tapes/providers/mock-coder-human.yaml`

## Description

This slice hardened the LangGraph resume boundary inside the worker so malformed or unknown interrupt resume payloads now fail closed instead of coercing to an allowed option. The worker now:

- derives the valid permission option ids explicitly from ACP permission options
- resolves resumed payloads from either string or dict forms
- rejects empty, malformed, or unknown option ids with a clear runtime error that keeps the failure localized to the interrupt boundary

The deterministic human-loop tape was also extended so the VidaiMock-backed provider can complete both approval and denial branches with stable output. The real-stack permission service suite now proves two recovery properties that were previously missing:

- a hostile invalid permission response leaves the thread paused and recoverable
- a real deny response completes the thread with the deterministic denial message instead of drifting into the approval path

LangGraph grounding for this step stayed aligned with the official interrupt and durable execution guidance: resumed payloads must be treated as explicit persisted input, validated against the allowed options, and failed closed when malformed. The remaining LangGraph-specific concern for later audits is replay safety for any side effect that happens before `interrupt()`.

## Tests

Focused verification completed successfully:

- `uv run pytest src/vaultspec_a2a/graph/tests/nodes/test_worker.py -q`
- `uv run pytest src/vaultspec_a2a/service_tests/test_permissions_resume.py -q -m service`
- `uv run pytest -m service src/vaultspec_a2a/service_tests -q`

Mandatory review completed against the current plan, ADR, research, and rolling audit. This slice resolves the previously logged VidaiMock readiness and deny-path coverage gaps; the remaining residual findings are captured in the updated rolling review audit.
