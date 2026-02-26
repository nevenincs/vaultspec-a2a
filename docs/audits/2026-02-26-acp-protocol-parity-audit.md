---
title: ACP Protocol Feature Parity Audit
source: Toad, claude-agent-sdk, acp-python-sdk
relevance: 10
---

# ACP Protocol Feature Parity Audit

**Our implementation:** `lib/providers/acp_chat_model.py`
**Date:** 2026-02-26

**Sources audited:**

1. **Toad** — `toad/acp/agent.py`
2. **Anthropic claude-agent-sdk** — `claude_agent_sdk`
3. **acp-python-sdk** — `acp/client/`

---

## Key Finding: Two Distinct Wire Formats

### Format A: Raw ACP JSON-RPC over stdio (what we implement)

Used by **Toad** and **acp-python-sdk**. Bidirectional JSON-RPC:

```text
Client → stdin:  {"jsonrpc":"2.0","id":1,...}\n
Agent  → stdout: {"jsonrpc":"2.0","id":1,"result":{...}}\n
Agent  → stdout: {"jsonrpc":"2.0","method":"session/update",...}\n
```

### Format B: Streaming JSON (claude-agent-sdk)

Anthropic's SDK uses `--output-format stream-json`.
Not useful as a direct reference for raw ACP.

---

## Full ACP Client Protocol Surface

### Outbound: Client → Agent

| Method | acp-sdk | Toad | Ours | Notes |
| ------ | ------- | ---- | ---- | ----- |
| `initialize` | ✅ | ✅ | ✅ | Handshake |
| `session/new` | ✅ | ✅ | ✅ | Fresh session |
| `session/prompt` | ✅ | ✅ | ✅ | Send user turn |
| `session/load` | ✅ | ✅ | ✅ | Resume by id |
| `session/cancel` | ✅ | — | ✅ | Notification |
| `session/fork` | ✅ | — | ✅ | Session-gated |
| `session/list` | ✅ | — | ✅ | Session-gated |
| `session/set_mode` | ✅ | — | ✅ | Session-gated |
| `session/set_model` | ✅ | — | ✅ | Session-gated |
| `session/set_config_option` | ✅ | — | ✅ | Session-gated |
| `authenticate` | ✅ | — | ✅ | Session-gated |
| `session/resume` | ✅ | — | ❌ | Deferred |

### Inbound: Agent → Client

| Agent method | Gated? | Toad | Ours |
| ------------ | ------ | ---- | ---- |
| `session/update` (notification) | No | ✅ | ✅ |
| `session/request_permission` | **No** | ✅ | ✅ |
| `fs/*` | Yes | ✅ | ❌ |
| `terminal/*` | Yes | ✅ | ❌ |

### `session/update` Subtypes

| Type | Ours | Action |
| ---- | ---- | ------ |
| `agent_message_chunk` | ✅ | → `AIMessageChunk` |
| `agent_thought_chunk` | ✅ | → `AIMessageChunk` |
| `tool_call` | ✅ | → `ToolCallChunk` |
| `tool_call_update` | ✅ | Status tracking |
| `plan` | ✅ | Logged |
| `available_commands_update` | ✅ | Logged |
| `current_mode_update` | ✅ | Logged |
| `user_message_chunk` | ✅ | Ignored |
| `rate_limit_event` | ✅ | Warning logged |

---

## Implementation Status

| Feature | Status |
| ------- | ------ |
| `session/request_permission` | ✅ Auto-grant + callback |
| `tool_call` → `ToolCallChunk` | ✅ LangGraph visibility |
| `session/cancel` | ✅ Notification in cleanup |
| `session/load` | ✅ Via `session_id` field |
| MCP server injection | ✅ Via `mcp_servers` field |
| All session/update subtypes | ✅ Handled or logged |
| Outbound session methods | ✅ Session-gated live calls |
| `permission_callback` | ✅ Optional async callback |
| `fs/*` / `terminal/*` | ❌ Deferred (caps disabled) |

## Toad Reference Alignment (2026-02-26)

| Fix | Detail |
| --- | ------ |
| `agentCapabilities` storage | From initialize response |
| `loadSession` gating | `session/load` only if capable |
| Modes extraction | From `session/new` response |
| `session/cancel` as RPC | Not notification, 3s timeout |
| Tool call tracking | Merge dict + orphan handling |
| Field name corrections | `entries`, `availableCommands`, `currentModeId` |

## Key Learnings

1. `PermissionOption` uses `optionId` (camelCase), not `id`
2. `terminal: false` is correct — agents fallback internally
3. `claude-agent-sdk` uses a different wire format
4. Gemini probe passed: initialize → session/new → prompt → end_turn
5. Toad uses identical code for Claude & Gemini (`gemini --experimental-acp`)
6. `loadSession` capability must be checked before `session/load`

## References

| Source | Path |
| ------ | ---- |
| ACP client router | `acp-python-sdk/src/acp/client/router.py` |
| ACP schema | `acp-python-sdk/src/acp/schema.py` |
| Toad agent | `toad/src/toad/acp/agent.py` |
| Toad jsonrpc | `toad/src/toad/jsonrpc.py` |
| Claude SDK types | `claude-agent-sdk/.../types.py` |
