---
generated: true
tags:
  - '#index'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-19'
related:
  - '[[2026-07-17-kimi-provider-P01-S01]]'
  - '[[2026-07-17-kimi-provider-P01-S02]]'
  - '[[2026-07-17-kimi-provider-P01-S03]]'
  - '[[2026-07-17-kimi-provider-P01-S04]]'
  - '[[2026-07-17-kimi-provider-P01-S05]]'
  - '[[2026-07-17-kimi-provider-P01-S06]]'
  - '[[2026-07-17-kimi-provider-P02-S07]]'
  - '[[2026-07-17-kimi-provider-P02-S08]]'
  - '[[2026-07-17-kimi-provider-P02-S09]]'
  - '[[2026-07-17-kimi-provider-P03-S10]]'
  - '[[2026-07-17-kimi-provider-P03-S11]]'
  - '[[2026-07-17-kimi-provider-P03-S12]]'
  - '[[2026-07-17-kimi-provider-P03-S13]]'
  - '[[2026-07-17-kimi-provider-P04-S14]]'
  - '[[2026-07-17-kimi-provider-P04-S15]]'
  - '[[2026-07-17-kimi-provider-P05-S16]]'
  - '[[2026-07-17-kimi-provider-P05-S17]]'
  - '[[2026-07-17-kimi-provider-P05-S18]]'
  - '[[2026-07-17-kimi-provider-P06-S19]]'
  - '[[2026-07-17-kimi-provider-P06-S20]]'
  - '[[2026-07-17-kimi-provider-P06-S21]]'
  - '[[2026-07-17-kimi-provider-adr]]'
  - '[[2026-07-17-kimi-provider-audit]]'
  - '[[2026-07-17-kimi-provider-dedup-audit]]'
  - '[[2026-07-17-kimi-provider-plan]]'
  - '[[2026-07-17-kimi-provider-research]]'
---

# `kimi-provider` feature index

Auto-generated index of all documents tagged with `#kimi-provider`.

## Documents

### adr

- `2026-07-17-kimi-provider-adr` - `kimi-provider` adr: `the kimi moonshot provider lane: native ACP reuse with per-backend conditioning and permission-RPC read-only enforcement` | (**status:** `accepted`)

### audit

- `2026-07-17-kimi-provider-audit` - `kimi-provider` audit: `S20 holistic safety and intent gate`
- `2026-07-17-kimi-provider-dedup-audit` - `kimi-provider` audit: `P06.S19 vault dedup sweep — decision-vs-decision, decision-vs-code, and grounding-staleness reconciliation`

### exec

- `2026-07-17-kimi-provider-P01-S01` - Grounding and dedup gate - via vaultspec-rag semantically ground every seam this plan touches (provider enum, factory dispatch, config settings, ACP session meta sites, request_permission handler, compose_harness_mcp_servers, readiness probe, preset profiles) and confirm no Kimi lane already exists before any coding begins (executor-core)
- `2026-07-17-kimi-provider-P01-S02` - Add Provider.KIMI to the provider enum with its MODEL_MAP and PROVIDER_DEFAULT_MODELS entries, additive and never renaming existing members (executor-core)
- `2026-07-17-kimi-provider-P01-S03` - Add passthrough Pydantic settings kimi_api_key as SecretStr, kimi_base_url, and kimi_model_name that inject into the subprocess as the CLI native KIMI_API_KEY, KIMI_BASE_URL, and KIMI_MODEL_NAME (executor-core)
- `2026-07-17-kimi-provider-P01-S04` - Add the factory KIMI dispatch branch that builds an AcpChatModel on the kimi acp command with the backend discriminator set to the kimi family and Kimi env injected (executor-core)
- `2026-07-17-kimi-provider-P01-S05` - Record the kimi-cli 1.49.0 pin as a named constant co-located with the factory binary-resolution code and surface it in the install hint mirroring the _classify_acp_command pattern, verifying the Git-Bash prerequisite and honoring KIMI_SHELL_PATH (executor-core)
- `2026-07-17-kimi-provider-P01-S06` - Add a probe_provider_readiness KIMI branch that verifies the kimi binary presence and never emits a secret, with unit coverage for the key-present and key-absent branches (executor-service)
- `2026-07-17-kimi-provider-P02-S07` - Gate the session-new meta.claudeCode.options.allowedTools emission to the claude family via the backend discriminator so the Kimi lane omits it (executor-core)
- `2026-07-17-kimi-provider-P02-S08` - Keep the clientCapabilities meta.terminal-auth handshake unconditional and add a deterministic test that the claude and zai families keep the allowedTools meta while kimi omits it (executor-service)
- `2026-07-17-kimi-provider-P02-S09` - Add a real-subprocess keyless handshake test that drives initialize against the installed kimi acp and asserts protocolVersion 1 and the terminal-auth meta family (executor-service)
- `2026-07-17-kimi-provider-P03-S10` - Extend the on_request_permission handler to auto-approve exactly the composed read-tool names plus the enumerated Kimi native read tools in autonomous mode and reject every other request (executor-core)
- `2026-07-17-kimi-provider-P03-S11` - Keep supervised-mode prompting unchanged and add deterministic tests for both the autonomous auto-approve-exact branch and the reject-by-default branch (executor-service)
- `2026-07-17-kimi-provider-P03-S12` - Launch kimi acp with a per-run config-file that excludes the ambient home config so ambient Kimi MCP is suppressed (executor-core)
- `2026-07-17-kimi-provider-P03-S13` - Verify Kimi harness composition rides the existing with_mcp_servers branch by testing through the real compose_harness_mcp_servers seam rather than a direct-field assertion (executor-service)
- `2026-07-17-kimi-provider-P04-S14` - Add a team.profiles.kimi overlay to the live document-authoring preset that skips loudly when the key is absent, mirroring the zai profile precedent (executor-service)
- `2026-07-17-kimi-provider-P04-S15` - Verify the document personas name the composed rag tools and native read tools against Kimi native read tool names and add a lane note only if the wording requires it (executor-service)
- `2026-07-17-kimi-provider-P05-S16` - Prove live on the Kimi lane that a document agent reads a named .vault ADR mid-turn and cites it, capturing run id and narration or frames with zero document writes, armed on KIMI_API_KEY arrival (executor-service)
- `2026-07-17-kimi-provider-P05-S17` - Prove live that a Kimi document agent invokes vaultspec-rag search mid-turn with citations resolving to real locations and port 8766 search corroboration, armed on KIMI_API_KEY arrival (executor-service)
- `2026-07-17-kimi-provider-P05-S18` - Run the shape-a fallback fidelity check of the Claude CLI against the Moonshot Anthropic-compat endpoint only if the primary Kimi proof fails, armed on KIMI_API_KEY arrival (executor-service)
- `2026-07-17-kimi-provider-P06-S19` - Sweep the codebase and vault via rag for dead or duplicate kimi-lane paths and reconcile any found (executor-service)
- `2026-07-17-kimi-provider-P06-S20` - Run the mandatory code-review gate over all landed kimi-provider changes for safety and intent, which must return PASS before close-out (vaultspec-code-reviewer)
- `2026-07-17-kimi-provider-P06-S21` - Reconcile the plan and exec records against what actually landed, ensuring every Step has its exec record and the Verification criteria are honestly closed (executor-service)

### plan

- `2026-07-17-kimi-provider-plan` - `kimi-provider` plan

### research

- `2026-07-17-kimi-provider-research` - `kimi-provider` research: `kimi moonshot provider lane grounding`
