---
generated: true
tags:
  - '#index'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
related:
  - '[[2026-07-17-kimi-provider-P01-S01]]'
  - '[[2026-07-17-kimi-provider-P01-S02]]'
  - '[[2026-07-17-kimi-provider-P01-S03]]'
  - '[[2026-07-17-kimi-provider-P01-S04]]'
  - '[[2026-07-17-kimi-provider-P01-S05]]'
  - '[[2026-07-17-kimi-provider-P01-S06]]'
  - '[[2026-07-17-kimi-provider-P04-S14]]'
  - '[[2026-07-17-kimi-provider-P04-S15]]'
  - '[[2026-07-17-kimi-provider-adr]]'
  - '[[2026-07-17-kimi-provider-plan]]'
  - '[[2026-07-17-kimi-provider-research]]'
---

# `kimi-provider` feature index

Auto-generated index of all documents tagged with `#kimi-provider`.

## Documents

### adr

- `2026-07-17-kimi-provider-adr` - `kimi-provider` adr: `the kimi moonshot provider lane: native ACP reuse with per-backend conditioning and permission-RPC read-only enforcement` | (**status:** `accepted`)

### exec

- `2026-07-17-kimi-provider-P01-S01` - Grounding and dedup gate - via vaultspec-rag semantically ground every seam this plan touches (provider enum, factory dispatch, config settings, ACP session meta sites, request_permission handler, compose_harness_mcp_servers, readiness probe, preset profiles) and confirm no Kimi lane already exists before any coding begins (executor-core)
- `2026-07-17-kimi-provider-P01-S02` - Add Provider.KIMI to the provider enum with its MODEL_MAP and PROVIDER_DEFAULT_MODELS entries, additive and never renaming existing members (executor-core)
- `2026-07-17-kimi-provider-P01-S03` - Add passthrough Pydantic settings kimi_api_key as SecretStr, kimi_base_url, and kimi_model_name that inject into the subprocess as the CLI native KIMI_API_KEY, KIMI_BASE_URL, and KIMI_MODEL_NAME (executor-core)
- `2026-07-17-kimi-provider-P01-S04` - Add the factory KIMI dispatch branch that builds an AcpChatModel on the kimi acp command with the backend discriminator set to the kimi family and Kimi env injected (executor-core)
- `2026-07-17-kimi-provider-P01-S05` - Record the kimi-cli 1.49.0 pin as a named constant co-located with the factory binary-resolution code and surface it in the install hint mirroring the _classify_acp_command pattern, verifying the Git-Bash prerequisite and honoring KIMI_SHELL_PATH (executor-core)
- `2026-07-17-kimi-provider-P01-S06` - Add a probe_provider_readiness KIMI branch that verifies the kimi binary presence and never emits a secret, with unit coverage for the key-present and key-absent branches (executor-service)
- `2026-07-17-kimi-provider-P04-S14` - Add a team.profiles.kimi overlay to the live document-authoring preset that skips loudly when the key is absent, mirroring the zai profile precedent (executor-service)
- `2026-07-17-kimi-provider-P04-S15` - Verify the document personas name the composed rag tools and native read tools against Kimi native read tool names and add a lane note only if the wording requires it (executor-service)

### plan

- `2026-07-17-kimi-provider-plan` - `kimi-provider` plan

### research

- `2026-07-17-kimi-provider-research` - `kimi-provider` research: `kimi moonshot provider lane grounding`
