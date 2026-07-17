---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-16'
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

PASS (2026-07-16, on the funded account). The owner funded the Z.ai account
(team-lead verified live: a real glm-4.6 completion returned through the Z.ai
Anthropic gateway), and both service-marked probes then passed live against the
real gateway in 51.5s:

- `test_zai_streaming_shape_is_faithful`: a real streaming turn returned assistant
  deltas through the Claude ACP path - the streaming-chunk shape the reused
  `AcpChatModel` path depends on survives Z.ai's gateway.
- `test_zai_tool_calling_is_faithful`: a real turn drove the native `Write` tool
  to materialize `zai_probe.txt` containing `pong` - an unfakeable end-to-end
  signal that Z.ai reproduces the Anthropic tool-calling schema faithfully enough
  for the CLI's agentic loop.

The ADR's flagged Z.ai-fidelity unknown is CLOSED: Z.ai is fidelity-proven
(streaming shape AND tool-calling) for the reused Claude ACP path, so Z.ai
profiles may now be marked eligible.

This SUPERSEDES the first live attempt earlier the same day, which was
BLOCKED-ON-BALANCE: with the delivered token but an unfunded account, both tests
failed on HTTP 429 code 1113 ("Insufficient balance or no resource package"), NOT
on fidelity or auth - the token always authenticated (structured Z.ai error with a
request_id, base URL and env injection verified), the account simply had no funds
so no turn was produced. Once funded, the identical probe passed unchanged: the
gate was billing, never code, auth, base-URL, or fidelity.

## Notes

Re-arm in one command the moment the owner exports a token:

    ZAI_AUTH_TOKEN=<glm-anthropic-gateway-token> uv run --no-sync pytest -m service src/vaultspec_a2a/providers/tests/test_zai_fidelity.py

Override the gateway with `ZAI_BASE_URL` if the endpoint differs from the default. On a green run, update this record's Outcome to PASS with the observed streaming/tool evidence and check the plan row. The forbidden-skip mandate does not apply: this is a live resource gate (matching the accepted `Provider.CODEX` live-probe pattern), not a hidden failure.
