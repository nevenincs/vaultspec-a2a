---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:0af689196f0ee635e117083e4e6ce046c5e4d62bd37518633b634f5c4f875e25'
step_id: 'S08'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Replace the hardcoded gateway default with registry resolution in the pw7 harness

## Scope

- `src/vaultspec_a2a/service_tests/test_pw7_acceptance.py`

## Description

- Remove the hardcoded gateway default from the pw7 harness; `_reachable_stack` now resolves the gateway through the registry resolver and returns it in a four-tuple; `AcceptanceHarness.gateway_url` is a required field.
- Update every consumer (`test_tool_cores_floor_live.py`, `test_s20_solo_coder_bridge_live.py`, `test_claude_web_grounding_live.py`) to thread the resolved URL, and declare `loopback-stack` (plus `claude-cli-lane` where apt) on the live tests.

## Outcome

Committed as 18819cc5 and c5260f02. No `18100` fallback remains in the live harness; whole-tree ty clean after the consumer updates.

## Notes

The service token deliberately stays out-of-band per the audited separation; only discovery moved to the registry.
