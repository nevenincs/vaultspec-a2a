---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S13'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Verify Kimi harness composition rides the existing with_mcp_servers branch by testing through the real compose_harness_mcp_servers seam rather than a direct-field assertion (executor-service)

## Scope

- `src/vaultspec_a2a/providers/tests/`

## Description

- Add `test_kimi_harness_wiring`: build a Kimi `AcpChatModel` as the factory does and run it THROUGH the real `compose_harness_mcp_servers` seam, asserting the declared server reaches `mcp_servers` and the composed read tools reach `allowed_tools`, with `acp_family="kimi"` preserved across the compose `model_copy`.
- Add a guard test that the Kimi model exposes `with_mcp_servers` (ACP) and NOT `with_harness_mcp_servers` (Codex), so compose takes the ACP branch.

## Outcome

Kimi harness composition rides the EXISTING `with_mcp_servers` ACP branch with no new dispatch, proven through the real production seam rather than a direct-field assertion (the binding masking-gap lesson from the Codex wiring defect). Verified: a factory-shaped Kimi model starts with empty `mcp_servers`/`allowed_tools`; after `compose_harness_mcp_servers(model, ["vaultspec-rag"], allowed_tools=harness_allowed_tool_names(...))` it advertises `vaultspec-rag` in the session surface and carries the three `mcp__vaultspec-rag__*` read tools in the allowlist - identical to the Claude/Z.ai path - and `acp_family` survives the compose's `model_copy` so `_acp_session` still omits the Claude allowedTools `_meta` for this model. The dispatch guard confirms Kimi exposes `with_mcp_servers` (not the Codex `with_harness_mcp_servers`), so a future refactor cannot silently mis-route it to the Codex config.toml path. This closes P03 and the P01-P03 assignment. Gate: ruff clean, ty clean, 2 tests pass.

## Notes

- Test-through-the-real-seam (binding, ADR + plan): the wiring is asserted from the OUTPUT of `compose_harness_mcp_servers` - the exact call the worker composition site makes - not by constructing a model with `mcp_servers` pre-set. A regression that stopped Kimi from exposing `with_mcp_servers`, or that made compose no-op for the kimi family, would fail this test (the Codex defect that this discipline exists to prevent).
- No third branch, no config-home: because Kimi honors session-injected `mcpServers` (the probe drove `session/new` with inline `mcpServers` to the auth gate), it needs neither the Codex `config.toml` delivery nor the Claude isolated-config-home surfacing workaround - the ADR's central shape-(b1) claim, now confirmed at the composition layer. The allowlist that rides along is enforced at the permission-RPC handler (P03.S10), since the kimi family omits the Claude `allowedTools` `_meta` (P02.S07).
- The `allowed_tools` on the composed Kimi model carry the Claude-form `mcp__server__tool` names (from `harness_allowed_tool_names`); the permission handler reduces them to Kimi's raw tool names via `_strip_mcp_prefix` at decision time (P03.S10), so the two representations are reconciled without a second allowlist.
