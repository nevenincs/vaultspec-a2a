---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S01'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Grounding and dedup gate - via vaultspec-rag semantically ground every seam this plan touches (provider enum, factory dispatch, config settings, ACP session meta sites, request_permission handler, compose_harness_mcp_servers, readiness probe, preset profiles) and confirm no Kimi lane already exists before any coding begins (executor-core)

## Scope

- `src/vaultspec_a2a/`

## Description

- Dedup sweep: grep the whole `src/` tree and `knowledge/` for `kimi`/`moonshot`; rag semantic search for an existing Kimi/Moonshot provider lane.
- Ground each of the eight seams the plan touches with grep against the worktree, recording the current exact location and shape of each.
- Verify the two live prerequisites the plan depends on: the installed `kimi` binary and the ACP model config home for the backend discriminator.

## Outcome

GATE PASSED - no Kimi lane pre-exists anywhere; every seam is grounded. NO code was written in this Step (the binding grounding gate).

Dedup: zero `kimi`/`moonshot` occurrences in `src/**/*.py`, in the presets/config TOML, or in `knowledge/` (the single `src/` match is a stale `.pyc` bytecode artifact in `__pycache__`, not source). The rag semantic search for "kimi moonshot provider lane factory dispatch" returned only generic, unrelated files (compiler, ipc schemas) - no Kimi/Moonshot code. This is genuinely new ground, matching the research's dedup finding; the only prior art is the `ZAI`/`ZHIPU` product-vs-parent split and the tool-cores contract.

Seam grounding (current worktree state, at main `9a4e4ab`):

- Provider enum: `graph/enums.py:128` `class Provider(StrEnum)` with `CLAUDE`/`CODEX`/`GEMINI`/`ZAI`/`ZHIPU`; `MODEL_MAP` at `:154`, `PROVIDER_DEFAULT_MODELS` at `:216`. No `KIMI`/`MOONSHOT` member (S02 adds `KIMI`, additive).
- Factory dispatch: `providers/factory.py`; the `Provider.ZAI` branch is the precedent (`classify_provider_command` handles `CLAUDE`/`ZAI` together at `:300`), `_build_zai_env` at `:69`, `_classify_acp_command` at `:206`. S04/S05 add the `KIMI` branch, the `kimi acp` command classifier, and the `kimi-cli==1.49.0` pin constant.
- Config settings: `control/config.py` - `zhipu_api_key:166`, `zai_base_url:177`, `zai_auth_token:182`, `codex_home:190`. No `kimi_*`. S03 adds `kimi_api_key` (`SecretStr`), `kimi_base_url`, `kimi_model_name`.
- ACP session `_meta` sites: `providers/_acp_session.py` - the unconditional `clientCapabilities._meta.terminal-auth` at `:71-72` (stays unconditional, Kimi-compatible), and the Claude-only `_meta.claudeCode.options.allowedTools` emission gated only on `if config.allowed_tools:` at `:139-145`. S07 adds the backend-family gate so Kimi omits the `claudeCode` namespace.
- Permission handler: `providers/_acp_rpc_handlers.py:127` `async def on_request_permission` (`session/request_permission`). S10 extends it with the autonomous exact-name auto-approve set.
- Compose seam: `providers/_acp_mcp.py:197` `compose_harness_mcp_servers` already dispatches by delivery method - `with_mcp_servers` (ACP, `:236`) vs `with_harness_mcp_servers` (Codex, `:239`). Kimi is an `AcpChatModel`, so it rides the existing `with_mcp_servers` branch with NO new dispatch (S13 proves this through the real seam).
- Readiness probe: `providers/model_profiles.py:320` `probe_provider_readiness`, with `CODEX:364`, `ZAI:370`, `ZHIPU:379` branches. S06 adds the `KIMI` branch.
- Preset profiles: `team/presets/teams/vaultspec-adr-research.toml` - `[team.profiles.zai]` at `:156` is the skip-loudly precedent. P04.S14 (executor-service) adds `[team.profiles.kimi]`.

Prerequisites verified: `kimi` binary present at `~/.local/bin/kimi`, `kimi, version 1.49.0` (so the P02.S09 keyless handshake is runnable). The backend discriminator has a home on `_AcpModelConfig` (`providers/_acp_types.py:23`), which already carries `provider`, `runtime_authority`, and `acp_backend` fields; the allowedTools emission reads `config.allowed_tools` and `config.provider`, so S07 keys the gate on a family discriminator set by the factory (S04).

## Notes

- Discriminator design deferred to S04/S07 (their re-grounding): the config already carries `provider` (str: `claude`/`zai`/...); the family gate can key on it or on a dedicated field. Recording here only that the home exists and the emission site is `_acp_session.py:139-145`.
- Kimi native read-tool enumeration (needed for P03.S10's exact-name auto-approve set) is deferred to P03.S10's own re-grounding against the installed `kimi-cli` source (uv-tool venv), per the ADR's "enumerate from the installed source, cite" - not enumerated here to keep this gate scoped to OUR seams.
- Grounding method: rag semantic search (shared index) to confirm no Kimi lane exists and to locate the factory dispatch, then grep in the worktree to confirm exact current line numbers and shapes - the sanctioned hybrid. No code written; this Step is pure grounding per the binding owner mandate.
