---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S03'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Add _build_zai_env mirroring _build_gemini_env and a factory dispatch branch mirroring the Claude ACP branch, reusing AcpChatModel unchanged

## Scope

- `src/vaultspec_a2a/providers/factory.py`

## Description

- Add `_build_zai_env`, mirroring `_build_gemini_env`: it returns an explicit env dict carrying `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN`, and returns empty when no token is present (a blank base URL is dropped, a blank token yields no auth at all).
- Add a `Provider.ZAI` dispatch branch mirroring the Claude ACP branch: it reuses `_classify_acp_command` (the same `claude-agent-acp` wrapper as Claude), injects the Z.ai env via `_build_zai_env`, applies the binary Bun flag when the backend is `binary`, and constructs `AcpChatModel` unchanged.
- Set `auth_mode` to `zai_auth_token` when the token is injected, else `none_detected`.

## Outcome

Z.ai runs as a config variant of the Claude ACP path with zero changes to `AcpChatModel`. The Claude-CLI behaviours in `_astream` (the `ENABLE_TOOL_SEARCH=0` bridge workaround, the `CLAUDE_CODE_DISABLE_*` flags, the `CLAUDECODE` pop) are inherited unchanged. `ANTHROPIC_API_KEY` is already scrubbed at the base-env layer, so it cannot shadow the injected `ANTHROPIC_AUTH_TOKEN`.

## Notes

The Claude branch's OAuth-token path sets `CLAUDE_CODE_EXECUTABLE` to the system `claude` binary only when `CLAUDE_CODE_OAUTH_TOKEN` is present; the Z.ai path does not carry that token, so it relies on the wrapper's own binary resolution with the gateway vars set — validated structurally here and end-to-end by the S06 live probe. Shared `factory.py` file, landed with the Codex branch (P02.S13).
