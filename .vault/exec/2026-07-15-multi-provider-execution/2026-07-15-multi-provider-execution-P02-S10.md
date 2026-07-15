---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S10'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Implement CodexChatModel(BaseChatModel) driving codex app-server's JSON-RPC-over-stdio surface directly, following the mock_chat_model.py non-ACP precedent

## Scope

- `src/vaultspec_a2a/providers/codex_chat_model.py`

## Description

- Implement `CodexChatModel(BaseChatModel)` in `src/vaultspec_a2a/providers/codex_chat_model.py`, driving the `codex app-server` JSON-RPC-over-stdio surface directly and following the non-ACP `mock_chat_model.py` precedent.
- Build an internal `_CodexAppServerClient` that owns one subprocess and a reader task: newline-delimited JSON framing, id-correlated request and response futures, a notification queue, error-frame propagation, and a rejection reply for server-initiated requests so the stream never blocks.
- Perform the `initialize` request then the `initialized` notification, open an ephemeral read-only thread with `thread/start`, and drive one turn with `turn/start`.
- Stream `item/agentMessage/delta` frames as `ChatGenerationChunk`s, terminate on `turn/completed` (raising on a non-`completed` status or an `error` frame), and accumulate to a single `AIMessage` in `_agenerate`.
- Flatten LangChain messages to one turn prompt with `_messages_to_prompt` (role labels for system, assistant, and tool turns; human passes through; empty content dropped).

## Outcome

A live turn against the real `codex app-server` returned genuine output for both the streaming path and `ainvoke`. The model satisfies the `BaseChatModel` contract the graph depends on: it returns a standard `AIMessage`, so the worker node's document extraction (which stamps and reads `AIMessage.name`) works identically to every other provider.

## Notes

Verified against `codex-cli` 0.144.4. Streaming opts out of only the reasoning-summary delta notifications, keeping agent-message deltas for genuine token streaming. Synchronous `_generate` raises `NotImplementedError` by design (async-only provider), matching the mock precedent. This record and the code land together in the Codex provider-file commit.
