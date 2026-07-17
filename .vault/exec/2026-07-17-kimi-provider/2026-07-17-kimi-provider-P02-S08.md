---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S08'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Keep the clientCapabilities meta.terminal-auth handshake unconditional and add a deterministic test that the claude and zai families keep the allowedTools meta while kimi omits it (executor-service)

## Scope

- `src/vaultspec_a2a/providers/tests/`

## Description

- Extend the ACP protocol simulator with an additive `--record-initialize` flag (records the client's `initialize` params, default off) alongside the existing `--record-session-new`.
- Add `test_kimi_acp_conditioning`: a real `AcpChatModel` drives the simulator subprocess for each backend family and asserts, from the recorded params, that the claude family serializes the allowedTools `_meta` while kimi omits it, and that the terminal-auth handshake is unconditional for both.

## Outcome

The per-backend `_meta` conditioning is proven deterministically through the REAL `setup_session`/`initialize_session` seam (no mocks): a real model drives a real subprocess that records exactly what the CLI would receive. Verified: with `allowed_tools` set, the claude family's `session/new` carries `_meta.claudeCode.options.allowedTools == ["mcp__vaultspec-rag__search_vault"]`, while the kimi family's `session/new` carries NO `_meta` (but still advertises `mcpServers`, so harness delivery is unaffected). The shared `clientCapabilities._meta.terminal-auth` in `initialize` is `True` for BOTH families, confirming the handshake stays unconditional. Gate: ruff clean, 3 new conditioning tests pass, and the pre-existing simulator-backed harness-wiring tests still pass (the new flag is additive).

## Notes

- The terminal-auth assertion required recording the `initialize` params the CLIENT sends; the simulator previously recorded only `session/new`. The `--record-initialize` flag is strictly additive (defaults off), so `test_harness_mcp_wiring` and every other simulator consumer are unaffected - confirmed by running them.
- Test-through-the-real-seam discipline (Codex masking-gap lesson): the conditioning is asserted from what the simulator RECEIVES over the wire, not by inspecting model fields, so a future regression that stops threading `acp_family` into `_AcpModelConfig` or mis-gates the emission would fail this test. Z.ai is covered by the claude-family case (Z.ai constructs with `acp_family="claude"`), so a dedicated Z.ai run is redundant - the discriminant under test is the family, not the provider.
