---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S06'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Live-probe the real Z.ai endpoint for Anthropic Messages API fidelity (tool-calling schema, streaming chunk shape) through claude-agent-acp before marking any profile eligible

## Scope

- `this closes the ADR's flagged Z.ai-fidelity unknown`
- `src/vaultspec_a2a/providers/tests/`
- `src/vaultspec_a2a/service_tests/`

## Description

- Author a real, re-armable live fidelity probe as two `service`-marked tests in `src/vaultspec_a2a/providers/tests/test_zai_fidelity.py`, gated with `skipif` on Z.ai token presence.
- `test_zai_streaming_shape_is_faithful` drives a real streaming turn against the real Z.ai gateway through the Claude ACP path and asserts assistant deltas arrive (streaming-shape fidelity).
- `test_zai_tool_calling_is_faithful` forces a native `Write` tool call (auto-permitted via `allowed_tools`) and asserts the target file materialises with the expected content — an unfakeable end-to-end signal that Z.ai reproduces the Anthropic tool-calling schema faithfully enough for the CLI's agentic loop.

## Outcome

BLOCKED-ON-CREDENTIALS. No Z.ai token is present in the environment (checked `ZAI_AUTH_TOKEN`, `ZAI_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `GLM_API_KEY`, `ZHIPU_API_KEY`; all absent), so the probe cannot execute and the ADR's Z.ai-fidelity unknown remains open. The probe is written, lint/type clean, and deselected-by-default (`-m "not service"`), so the default suite is unaffected. No profile may mark Z.ai eligible until this passes.

## Notes

Re-arm in one command the moment the owner exports a token:

    ZAI_AUTH_TOKEN=<glm-anthropic-gateway-token> uv run --no-sync pytest -m service src/vaultspec_a2a/providers/tests/test_zai_fidelity.py

Override the gateway with `ZAI_BASE_URL` if the endpoint differs from the default. On a green run, update this record's Outcome to PASS with the observed streaming/tool evidence and check the plan row. The forbidden-skip mandate does not apply: this is a live resource gate (matching the accepted `Provider.CODEX` live-probe pattern), not a hidden failure.
