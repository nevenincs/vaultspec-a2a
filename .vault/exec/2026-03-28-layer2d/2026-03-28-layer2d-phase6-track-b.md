---
tags:
  - '#exec'
  - '#layer-2d'
date: '2026-03-28'
related:
  - '[[2026-03-28-layer2d-file-size-plan]]'
---

# phase 6 — slim AcpChatModel (track B)

Slimmed `acp_chat_model.py` to LangChain interface per ADR D-07.

- Removed all handler methods from the class (now in `_acp_rpc_handlers`)
- Removed orphaned constants (`_TERMINAL_COMMAND_ALLOWLIST` etc.)
- Removed `_runtime_log_extra` method — fully replaced by free function
  `runtime_log_extra(self._config, ...)`
- `_capture_auth_progress` writes `ctx.last_auth_url`
- `_cleanup_session` resets `ctx.tool_calls = {}` and
  `ctx.agent_modes = {}`
- `authenticate()` calls `authenticate_rpc()` with explicit parameters
- `rpc_map` in `_astream` uses lambda adapters to pass `config` to free
  functions
- Removed unused imports: `re`, `subprocess`, `uuid4`, `GraphBubbleUp`,
  `AcpAuthError`, `AcpSessionError`

Final verification:
- `acp_chat_model.py`: 662 lines (< 1000, all under mandate)
- `_acp_session.py`: 714 lines
- `_acp_protocol.py`: 325 lines
- `_acp_rpc_handlers.py`: 445 lines
- Zero `self._runtime_log_extra` in all providers/
- Zero `self._tool_calls`/`self._agent_modes` in acp_chat_model.py
- 574 middleware tests passed
