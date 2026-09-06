---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:a3d8cbd299f04dd711d1ebb4fc218a94c0117b0dca0e1b417dc156ed9ec80645'
step_id: 'S31'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Validate returned ACP version before session creation and reject malformed/incompatible initialization or absent required optional support

## Scope

- `src/vaultspec_a2a/providers/_acp_session.py`

## Changes

- `M` `src/vaultspec_a2a/providers/_acp_session.py`
- `M` `src/vaultspec_a2a/providers/tests/test_acp_model_selection.py`
- `verify:` `uv run python -m vaultspec_a2a.testing.runner --run-timeout 120 --exit-timeout 5 -- src/vaultspec_a2a/providers/tests/test_acp_model_selection.py -q` -> `pass`
