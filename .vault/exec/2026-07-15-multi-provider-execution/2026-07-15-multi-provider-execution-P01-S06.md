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

BLOCKED-ON-BALANCE (2026-07-16, first live attempt). The owner delivered a Z.ai
token (`ZAI_AUTH_TOKEN`, resolved through `settings`), and both probe tests ran
live against the real gateway but FAILED - NOT on fidelity and NOT on auth. Both
turns returned the same gateway error:

    HTTP 429 rate_limit_error, code "1113": "Insufficient balance or no resource
    package. Please recharge." (Z.ai request_id present)

surfaced as `AcpPromptError [-32603]` from the ACP path. What this establishes and
leaves open:

- The token AUTHENTICATES: the request reached the Z.ai Anthropic-Messages
  gateway and received a structured Z.ai API error with a request_id - a 429
  balance error, not a 401/403 rejection. Base URL correct
  (`settings.zai_base_url` = the Z.ai Anthropic endpoint); env injection verified
  (`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` present in the model env; the
  token value is never surfaced).
- NO FIDELITY VERDICT is possible: the account has no balance/resource package, so
  the endpoint never produced a turn to judge the streaming shape or tool-calling
  schema against. Neither green nor a fidelity-red - the ADR's Z.ai-fidelity
  unknown stays open.
- Each test failed clean at ~220s (the timeout-hardened retry window did its job -
  no hang). The default suite is unaffected (`-m "not service"`).

Checkbox stays UNCHECKED. No profile may mark Z.ai eligible until a green fidelity
run, which requires the owner to fund the Z.ai account (recharge / add a resource
package) - an account-billing action, not a code, auth, base-URL, or fidelity fix.

## Notes

Re-arm in one command the moment the owner exports a token:

    ZAI_AUTH_TOKEN=<glm-anthropic-gateway-token> uv run --no-sync pytest -m service src/vaultspec_a2a/providers/tests/test_zai_fidelity.py

Override the gateway with `ZAI_BASE_URL` if the endpoint differs from the default. On a green run, update this record's Outcome to PASS with the observed streaming/tool evidence and check the plan row. The forbidden-skip mandate does not apply: this is a live resource gate (matching the accepted `Provider.CODEX` live-probe pattern), not a hidden failure.
