---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S07'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Unit and live-probe tests for the Z.ai env-injection path, readiness branch, and factory dispatch

## Scope

- `src/vaultspec_a2a/providers/tests/test_factory.py`
- `src/vaultspec_a2a/providers/tests/test_model_profiles.py`

## Description

- Add env-injection unit tests for `_build_zai_env`: full base-URL-plus-token injection, empty result without a token, blank-token rejection, and blank-base-URL omission with a valid token.
- Add factory-dispatch tests: Z.ai constructs an `AcpChatModel` on the same `claude-agent-acp` node command as Claude, with the correct provider value, backend, `use_exec`, and `auth_mode`; and injects both gateway vars when a token is configured. Both guard the ACP-entry-point-absent case with the real `ConfigError` contract rather than skipping.
- Add a `classify_provider_command` test asserting Z.ai returns the ACP wrapper metadata.
- Add a readiness test asserting the credential-gated safe reason and that no token value leaks into the reason.
- Update the `Provider` membership test to include `zai` (and `codex`, present from P02).

## Outcome

The Z.ai env-injection path, readiness branch, and factory dispatch are covered by real unit tests (no mocks). Full P1 suite is green: 134 tests across `test_factory.py`, `test_model_profiles.py`, `test_workspace.py`, and `test_enums.py`; graph/team/evidence suites (136 tests) show no regressions; `ruff` and `ty` are clean on all modified files.

## Notes

The live-probe half of this step's original scope is tracked under S06 (blocked-on-credentials). The unit half is complete here. The membership-test edit is a shared test file that also reflects `Provider.CODEX`.
