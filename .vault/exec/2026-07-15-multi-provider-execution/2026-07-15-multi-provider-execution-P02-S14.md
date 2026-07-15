---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S14'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Unit tests for CodexChatModel's JSON-RPC framing and subprocess lifecycle, plus a live probe against the real codex app-server once the auth model is resolved

## Scope

- `src/vaultspec_a2a/providers/tests/test_codex_chat_model.py`
- `src/vaultspec_a2a/service_tests/`

## Description

- Add `test_codex_chat_model.py` exercising the JSON-RPC framing against a real spawned subprocess (a minimal Python echo server), with no mocks: request and response id-correlation, two concurrent requests matched by id, an error frame surfacing as a protocol error, a server notification landing on the queue distinct from the request result, and rejection of requests after close.
- Add pure-logic tests for `_messages_to_prompt` (role labelling and empty-block dropping).
- Add command-classification, readiness, and factory-dispatch tests, plus a test asserting the returned `AIMessage` accepts a `name` assignment (the worker node's graph-consumption contract).
- Add a `service`-marked live turn against the real `codex app-server`, skipped when the `codex` binary is absent.

## Outcome

Fourteen tests pass; the `service`-marked live turn passes against the real `codex-cli` 0.144.4 and returns genuine output. `ruff`, `ruff format`, and `ty` are clean on both Codex files. This record and the tests land together in the Codex provider-file commit.

## Notes

No mocks: the framing tests use a real subprocess over genuine stdio pipes with real asyncio semantics. Graph consumption is proven through the `BaseChatModel` contract — live streaming, `ainvoke`, and a name-settable `AIMessage` — rather than a full `compile_team_graph` run; a full mixed-provider compile-and-run smoke belongs to the P03 acceptance phase and MUST RE-DERIVE there against the standing harness.
