---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S11'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Keep supervised-mode prompting unchanged and add deterministic tests for both the autonomous auto-approve-exact branch and the reject-by-default branch (executor-service)

## Scope

- `src/vaultspec_a2a/providers/tests/`

## Description

- Add `test_kimi_permission` covering the autonomous auto-approve-exact branch (every composed rag read + every native read tool -> `approve`) and the reject-by-default branch (writes, shell, web, agent, plan, dmail, and unknown tools -> `reject`), both via the real `_kimi_autonomous_option_id` and end to end through `on_request_permission`.
- Add a supervised test proving a Kimi run with a `permission_callback` present keeps its prompt: the callback decides, the auto-approve set is NOT consulted.

## Outcome

Both branches of the Kimi read-only enforcement are deterministically proven, plus the supervised-unchanged guarantee. The autonomous auto-approve set admits EXACTLY the composed rag reads (`search_vault`/`search_codebase`/`get_code_file`, matched against Kimi's raw MCP tool names) and the native reads (`ReadFile`/`Grep`/`Glob`/`ReadMediaFile`), and rejects everything else - including the native writes `WriteFile`/`StrReplaceFile`, the `bash` shell, the web tools `SearchWeb`/`FetchURL`, and `Agent`/`EnterPlanMode`/`SendDMail`/unknown tools. Supervised mode (a `permission_callback` present) never falls through to the auto-approve branch: a callback that rejects a `ReadFile` (which the autonomous set WOULD approve) wins, proving the human gate is preserved. Gate: ruff clean, ty clean, 18 tests pass.

## Notes

- Test-through-the-real-handler: the end-to-end cases call the actual `on_request_permission` with a real frozen `_AcpModelConfig` (`acp_family="kimi"`, `allowed_tools` set), asserting the returned option id, so a regression in the branch wiring (not just the pure decision function) is caught. The autonomous and normal-callback-return paths never touch the session context, so a lightweight stand-in is passed for it - no mocked services.
- The reject case is the security-critical one (the harness contract's "what the agent CAN do"): it is parametrized across writes, shell, web egress, planning mutators, mail, and an unknown tool, so the default is provably deny, not approve. This is the exact-name-allowlist invariant the ADR requires in place of blanket `--yolo`.
- Live interaction with Kimi's real toolset under a real turn remains key-gated (P05); this Step proves the decision logic and wiring deterministically without a key.
