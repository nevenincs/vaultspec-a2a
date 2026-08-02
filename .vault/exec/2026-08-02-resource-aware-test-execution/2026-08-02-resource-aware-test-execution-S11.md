---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:8b087c4092678fd5e30ceae828f49a42497015445fef1146218c8c60bed8b413'
step_id: 'S11'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Centralize the production port-literal defaults into the strict config home

## Scope

- `src/vaultspec_a2a/control/config.py`

## Description

- Add `DEFAULT_MOCK_API_BASE` and `DEFAULT_OTLP_ENDPOINT` beside the canonical env-var names in `src/vaultspec_a2a/control/config.py`.
- Consume them from the mock provider (dropping its private local-base constant, precedence unchanged) and from the telemetry module's import-time OTLP env read.

## Outcome

Committed as 4491161a. The two production runtime literals outside the config home are eliminated; a post-change sweep shows every remaining production occurrence is the canonical home itself or docstring/help prose. Import-cycle probe clean; 43 targeted tests green.

## Notes

Docstring examples naming resident defaults (engine 8767, gateway 18000, worker 18001) are descriptive prose and deliberately kept.
