---
tags:
  - '#adr'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - "[[2026-07-17-kimi-provider-research]]"
  - "[[2026-07-17-tool-cores-adr]]"
  - "[[2026-07-15-multi-provider-execution-adr]]"
  - "[[2026-07-15-agent-harness-provisioning-adr]]"
---
# `kimi-provider` adr: `the kimi moonshot provider lane: native ACP reuse with per-backend conditioning and permission-RPC read-only enforcement` | (**status:** `accepted`)

## Problem Statement

The research-to-ADR authoring graph runs Claude, Codex, and Z.ai lanes (`2026-07-15-multi-provider-execution-adr`). The owner wants Kimi (Moonshot AI) added as a fourth lane with full tool-cores conformance (`2026-07-17-tool-cores-adr`): read-only grounding delivered mid-turn, an isolated per-run surface, and a live floor plus semantic proof. `2026-07-17-kimi-provider-research` (probe amendment decisive) resolves the shape-determining unknowns; this record fixes the integration shape, the read-only enforcement mechanism for a lane with no pre-declared allowlist, the conditioning of our Claude-specific ACP extensions, naming, provisioning, and the key-gated sequencing.

## Considerations

- Kimi Code CLI (`kimi-cli` 1.49.0) speaks the Agent Client Protocol natively: `kimi acp` is a stdio ACP server, `protocolVersion 1`, agent capabilities including `loadSession` and `mcpCapabilities` (`2026-07-17-kimi-provider-research`, live probe).
- Decisively, Kimi HONORS session-injected `mcpServers`: the probe drove a `session/new` with inline `mcpServers` to the auth gate (schema accepted, `-32000 Authentication required` on a dummy key). This is the contrast with the Claude lane's registration-scope surfacing gate - Kimi needs NO isolated-config-home workaround for MCP DELIVERY (`2026-07-17-kimi-provider-research`).
- Kimi's handshake carries `authMethods[0]._meta.terminal-auth` - the SAME `_meta` family our ACP client already sends as `clientCapabilities._meta.terminal-auth` (`src/vaultspec_a2a/providers/_acp_session.py:71`), so the handshake is portable and drivable keyless; the auth gate fires at `session/new`, not `initialize` (`2026-07-17-kimi-provider-research`).
- Our ACP client's `session/new` allowlist rides a Claude-CLI-only namespace `_meta.claudeCode.options.allowedTools` (`src/vaultspec_a2a/providers/_acp_session.py:144`), emitted whenever `config.allowed_tools` is set. Kimi has no `claudeCode`/`allowedTools` analogue, so this serialization is not portable.
- Kimi has no pre-declared per-tool allowlist (no `allowedTools`/`enabled_tools`). It gates client-side via the standard ACP `session/request_permission` RPC (approve / approve_for_session / reject), which our `AcpChatModel` already handles, plus a blanket `--yolo`/`default_yolo` auto-approve (`2026-07-17-kimi-provider-research`).
- Non-interactive auth EXISTS (contra the doc-inferred risk): the CLI reads `KIMI_API_KEY`, `KIMI_BASE_URL` (retargets Moonshot endpoints), and `KIMI_MODEL_NAME` from its own environment; `MOONSHOT_API_KEY` is not read. Per-run isolation is `--config <inline>` (complete config, no file) or `--config-file <path>` overriding `~/.kimi/config.toml` - cleaner than the CODEX_HOME redirect (`2026-07-17-kimi-provider-research`).
- The composition seam already dispatches two delivery shapes: an ACP model exposing `with_mcp_servers` (Claude/Z.ai session-inject) and a Codex model exposing `with_harness_mcp_servers` (config.toml) (`src/vaultspec_a2a/providers/_acp_mcp.py:236-241`). One read-only registry with a fail-loud trust-root guard feeds both (`_acp_mcp.py:147-158`).
- Moonshot exposes an Anthropic-compatible endpoint (`https://api.moonshot.ai/anthropic/v1/messages`), the structural analogue of the Z.ai lane, but with a `real_temperature = request_temperature * 0.6` remap and only community-attested Claude-CLI fidelity (`2026-07-17-kimi-provider-research`).
- Host provisioning: `kimi-cli` is absent; the natural lane is `uv tool install kimi-cli==1.49.0` (a NEW Python provisioning axis, not the Node `package.json` pin). Git for Windows is present (git 2.54.0); Git Bash is the CLI's shell, `KIMI_SHELL_PATH` overrides (`2026-07-17-kimi-provider-research`).
- Zero prior repository/vault mention of Kimi/Moonshot; the only prior art is the `ZAI`/`ZHIPU` product-vs-parent enum split and the tool-cores contract (`2026-07-17-kimi-provider-research`).

## Considered options

- **(b1) Generic-ACP reuse: point our ACP transport at `kimi acp` (chosen).** Kimi is genuinely ACP and honors session `mcpServers`, so this is the own-agent shape with gate-free MCP delivery. Cost: the Claude-only `_meta.claudeCode.options.allowedTools` serialization must be conditioned per backend, and read-only enforcement moves to our permission-RPC handler. The probe de-risked the handshake, session-inject, and env auth.
- **(a) Z.ai-style Claude-CLI variant against Moonshot's Anthropic-compat endpoint.** Rejected as the primary, retained as the documented fallback only if (b1)'s live proof fails. It is cheapest and inherits the tool-cores mechanism unchanged, but runs Kimi's MODEL through Claude Code's agent scaffolding rather than Kimi's own agent, carries the `* 0.6` temperature remap and community-attested-only fidelity, and would inherit the isolated-config-home indirection that (b1) does not need.
- **(b2) From-scratch `BaseChatModel` class (codex precedent).** Rejected: Kimi is genuinely ACP, so a bespoke class reinvents (b1) with more code and more surface to maintain; justified only if (b1)'s `_meta` portability fails live, which the probe makes unlikely.
- **(c) Hosted OpenAI-compatible `BaseChatModel` (`Provider.ZHIPU` precedent).** Rejected: it has no MCP surface, so it structurally cannot satisfy the tool-cores grounding mandate; enumerated for completeness.

## Constraints

- Read-only is a hard boundary (`2026-07-17-tool-cores-adr`, `2026-07-15-agent-harness-provisioning-adr`): only read-only registry servers may be composed, and no write path may be handed to the agent. Kimi has no config-level allowlist, so the enforcement point is our own `session/request_permission` handler; this must be an EXACT-name auto-approve set, never blanket approval.
- Frontier/probe-gated: the probe drove `session/new` with `mcpServers` only to the auth gate; the full connect-and-surface behavior post-auth, and the live floor/semantic proofs, are gated on a Moonshot API key. The `--yolo`-free permission-RPC path and the per-backend `_meta` conditioning are deterministically verifiable now without a key.
- Third-party surface risk: Moonshot's Anthropic-compat endpoint (only relevant to the rejected shape (a)) is community-attested, remaps temperature by `* 0.6`, and is unverified against the tool-calling/streaming shape; the (a) fallback fidelity check is itself key-gated.
- New provisioning axis: `uv tool install kimi-cli==<pin>` is a Python tool install, distinct from the Node `package.json` adapter pin; the pin must have one recorded home and the factory must resolve the `kimi` binary and hint the install, mirroring the existing `_classify_acp_command` pattern. Git for Windows is a hard host prerequisite (Git Bash is the CLI's shell).
- Additive contract: a new `Provider.KIMI` enum member and new profile/eligibility values are additive, never renames, consistent with the multi-provider ADR's v1-additive constraint. The dashboard/engine schema openness for a new provider string is the same unresolved cross-repo question flagged there and is not resolved here.
- No shims (owner mandate): the per-backend conditioning is a clean discriminator-keyed branch, not a compatibility shim over the Claude serialization.

## Implementation

High-level; the plan elaborates and sequences.

**Lane shape.** Kimi is an `AcpChatModel` variant (like Z.ai), not a new class: a `Provider.KIMI` enum member with `MODEL_MAP`/`PROVIDER_DEFAULT_MODELS` entries, a `factory.py` dispatch branch that resolves the `kimi acp` command and injects Kimi's env, and a `_classify_acp_command`-style readiness check. `MOONSHOT` is reserved for a possible future hosted lane (parallel to the `ZAI`/`ZHIPU` split) and is NOT added now.

**Backend conditioning (no shims).** A single backend discriminator is carried on the ACP model config and set by the factory branch (claude-family for Claude/Z.ai, kimi-family for Kimi). It selects the ALLOWLIST TRANSPORT only: the claude family serializes `config.allowed_tools` into `session/new _meta.claudeCode.options.allowedTools` (`_acp_session.py:144`, unchanged for Claude/Z.ai); the kimi family does NOT emit that namespace and instead feeds the same composed names to the permission-RPC auto-approve set. The shared `clientCapabilities._meta.terminal-auth` handshake (`_acp_session.py:71`) stays unconditional - the probe confirms Kimi accepts it.

**MCP delivery reuses the existing ACP branch.** Because Kimi honors session `mcpServers`, its harness composition rides the SAME `with_mcp_servers` path Claude/Z.ai use in `compose_harness_mcp_servers` (`_acp_mcp.py:236`); NO third dispatch branch, NO `config_home` surfacing, NO Codex-style `config.toml` is added for Kimi. The one read-only registry and its fail-loud trust-root guard are reused unchanged.

**Read-only enforcement at our RPC layer.** In autonomous mode the client's `session/request_permission` handler auto-approves EXACTLY an explicit read-only allowlist - the composed `mcp__<server>__<tool>` read tools (from `harness_allowed_tool_names`) plus Kimi's native read tools - and rejects every other request; blanket `--yolo`/`default_yolo` is NOT used, because it would auto-approve arbitrary tool calls (including Kimi's native write/shell tools) even with read-only-only composition, defeating the exact-name-allowlist invariant. This is the Claude `allowedTools` allowlist re-expressed at our RPC handler for a lane whose CLI carries no config allowlist.

**Per-run isolation and ambient suppression.** The factory launches `kimi acp` with `--config-file <per-run>` (or inline `--config`) carrying only the run's auth and flags, which excludes the operator's `~/.kimi/config.toml` and thereby suppresses any ambient Kimi MCP - the same per-run-config isolation pattern as Codex `CODEX_HOME` and the Claude isolated home, but for auth/isolation rather than MCP delivery.

**Auth, settings, provisioning.** New Pydantic settings `kimi_api_key` (`SecretStr`), `kimi_base_url`, `kimi_model_name` are injected into the subprocess as the CLI's native `KIMI_API_KEY`/`KIMI_BASE_URL`/`KIMI_MODEL_NAME` (passthrough naming, not `VAULTSPEC_`-prefixed, because the CLI reads the unprefixed names directly - the Z.ai `ANTHROPIC_*` injection precedent). The `kimi-cli==1.49.0` pin lives as a named constant co-located with the factory binary-resolution/classify code (single source), surfaced in the install hint mirroring `_classify_acp_command`; the readiness check verifies the `kimi` binary and the Git-Bash prerequisite and honors `KIMI_SHELL_PATH`. `probe_provider_readiness` gains a `KIMI` branch that never emits a secret, and a `[team.profiles.kimi]` overlay skips loudly when the key is absent (the `[team.profiles.zai]` precedent).

**Sequencing (build now, prove on key).** All non-key work lands and is deterministically verified now: the dispatch branch, env injection, per-run config, the backend-conditioned allowlist transport, the permission-RPC auto-approve set, and the readiness probe (with unit coverage for the key-present and key-absent branches). The live floor proof (Kimi reads a named `.vault` ADR mid-turn and cites it) and semantic proof (Kimi invokes vaultspec-rag search mid-turn, citations resolve, `:8766` corroboration) - and the shape-(a) fidelity fallback check - are the only key-gated items, mirroring the Z.ai blocked-on-credentials-not-code posture; no code work is deferred.

## Rationale

The probe makes (b1) the evidence-favored shape: Kimi is real ACP, honors session `mcpServers`, shares the terminal-auth `_meta` family, and has env auth - so the natural own-agent integration is also the one that AVOIDS the Claude lane's biggest cost, the isolated-config-home surfacing workaround, because Kimi has no registration-scope gate. The one genuine seam that is not portable, the Claude-only `allowedTools _meta`, is isolated behind a single backend discriminator rather than a shim, and the read-only invariant is preserved by moving enforcement to our own permission-RPC handler as an exact-name auto-approve set - the same allowlist idea Claude expresses in config, re-expressed at the RPC layer. Choosing (b1) over (a) buys Kimi's own agent instead of Kimi-the-model-through-Claude, sheds the temperature remap and third-party fidelity risk, and reuses the one registry and its trust-root guard with zero new composition branch; (a) survives only as the fallback the plan proves if (b1) fails live. Blanket `--yolo` is rejected because read-only-only composition still leaves Kimi's native write/shell tools reachable, and the harness contract's enforcement principle is what an agent CAN do, not what a prompt or a compose-list asks it not to do. Building everything non-key now and gating only the live proofs honors the owner's sequence-not-defer directive against a real credential dependency.

## Consequences

- Gains: a fourth provider lane on the own-agent ACP shape with gate-free MCP delivery; the one registry, trust-root guard, and permission bridge are reused; the Claude-specific `_meta` is finally isolated behind a backend discriminator, which also makes any future ACP backend cheaper to add.
- New surface / debt: a new Python provisioning axis (`uv tool install kimi-cli`) distinct from the Node pin, with its own binary-resolution and Git-Bash prerequisite; a backend discriminator threaded through the ACP session builder; a permission-RPC auto-approve path that must be unit-covered for the reject-by-default case.
- Honest risk: the full connect-and-surface behavior post-auth and all live proofs are key-gated (Moonshot API key not present); the permission-RPC read-only enforcement is deterministically testable but its live interaction with Kimi's native toolset is proven only on key arrival; the `real_temperature = request_temperature * 0.6` remap and community-attested fidelity remain caveats for the rejected (a) fallback.
- Explicitly out of scope: per-branch (fan-out) provider diversity (still deferred by `2026-07-15-multi-provider-execution-adr`); the dashboard/engine cross-repo schema-openness question for a new provider string (same unresolved cross-repo event flagged there); a hosted `MOONSHOT` OpenAI-compat lane (reserved name, not built).
- Opens: if `--config-file` per-run isolation proves insufficient to suppress ambient Kimi MCP in a live run, the isolation mechanism is revisited; if (b1)'s `_meta` conditioning fails live, the (a) fallback is promoted by a superseding decision rather than a silent pivot.

## Correction (2026-07-17, `P01.S05` grounding correction)

The Considerations and Implementation sections above name the Windows shell-override environment variable as `KIMI_SHELL_PATH`. Installed-source re-grounding during execution (`P01.S05`) found this was an inferred name, falsified by the installed `kimi-cli` 1.49.0 source (`utils/environment.py:100`) and its CHANGELOG, which read `os.environ.get("KIMI_CLI_GIT_BASH_PATH")`. The correct override name is `KIMI_CLI_GIT_BASH_PATH`; the landed code (`factory.py:_KIMI_GIT_BASH_ENV`) uses the corrected name and the resolution order this ADR describes (env override, then `git`/`bash` on PATH, then standard install path) is otherwise accurate and unchanged. `KIMI_SHELL_PATH` does not exist in the `kimi-cli` source and should not be treated as a valid override in any future reference to this record.
