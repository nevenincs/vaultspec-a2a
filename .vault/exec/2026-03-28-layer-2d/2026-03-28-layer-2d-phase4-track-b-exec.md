---
tags:
  - '#exec'
  - '#layer-2d'
date: '2026-03-28'
modified: '2026-07-14'
related:
  - '[[2026-03-28-layer2d-file-size-plan]]'
---

# phase 4 — ACP protocol dispatch extraction (track B)

Extracted JSON-RPC protocol dispatch from `acp_chat_model.py` into
`providers/_acp_protocol.py` per ADR D-05.

- Moved `_CAPABILITY_REQUIREMENTS` constant
- Extracted `process_stdout_loop`, `dispatch_packet`,
  `handle_client_response`, `handle_server_rpc`, `handle_session_update`
- Extracted `on_tool_call`, `on_tool_call_update` — write to
  `ctx.tool_calls`
- Handler map passed as `rpc_handler_map` parameter to avoid circular
  imports (`_acp_protocol` does NOT import from `_acp_rpc_handlers`)
- Updated `_astream` to build `rpc_map` dict and pass to
  `process_stdout_loop`
- 123 providers tests pass
