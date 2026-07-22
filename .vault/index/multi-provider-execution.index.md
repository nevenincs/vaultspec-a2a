---
generated: true
tags:
  - '#index'
  - '#multi-provider-execution'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - '[[2026-07-15-multi-provider-execution-P01-S01]]'
  - '[[2026-07-15-multi-provider-execution-P01-S02]]'
  - '[[2026-07-15-multi-provider-execution-P01-S03]]'
  - '[[2026-07-15-multi-provider-execution-P01-S04]]'
  - '[[2026-07-15-multi-provider-execution-P01-S05]]'
  - '[[2026-07-15-multi-provider-execution-P01-S06]]'
  - '[[2026-07-15-multi-provider-execution-P01-S07]]'
  - '[[2026-07-15-multi-provider-execution-P02-S08]]'
  - '[[2026-07-15-multi-provider-execution-P02-S09]]'
  - '[[2026-07-15-multi-provider-execution-P02-S10]]'
  - '[[2026-07-15-multi-provider-execution-P02-S11]]'
  - '[[2026-07-15-multi-provider-execution-P02-S12]]'
  - '[[2026-07-15-multi-provider-execution-P02-S13]]'
  - '[[2026-07-15-multi-provider-execution-P02-S14]]'
  - '[[2026-07-15-multi-provider-execution-P03-S15]]'
  - '[[2026-07-15-multi-provider-execution-P03-S16]]'
  - '[[2026-07-15-multi-provider-execution-P03-S17]]'
  - '[[2026-07-15-multi-provider-execution-P04-S18]]'
  - '[[2026-07-15-multi-provider-execution-P04-S19]]'
  - '[[2026-07-15-multi-provider-execution-adr]]'
  - '[[2026-07-15-multi-provider-execution-audit]]'
  - '[[2026-07-15-multi-provider-execution-plan]]'
  - '[[2026-07-15-multi-provider-execution-reference]]'
  - '[[2026-07-15-multi-provider-execution-research]]'
---

# `multi-provider-execution` feature index

Auto-generated index of all documents tagged with `#multi-provider-execution`.

## Documents

### adr

- `2026-07-15-multi-provider-execution-adr` - `multi-provider-execution` adr: `provider matrix, per-role assignment, and cross-repo initialization for Codex, Claude, and Z.ai` | (**status:** `accepted`)

### audit

- `2026-07-15-multi-provider-execution-audit` - `multi-provider-execution` audit: `env_vars token redaction audit`

### exec

- `2026-07-15-multi-provider-execution-P01-S01` - Add Provider.ZAI to the Provider enum with MODEL_MAP and PROVIDER_DEFAULT_MODELS entries
- `2026-07-15-multi-provider-execution-P01-S02` - Add zai_base_url/zai_auth_token settings fields and validate they never leak into logs
- `2026-07-15-multi-provider-execution-P01-S03` - Add _build_zai_env mirroring _build_gemini_env and a factory dispatch branch mirroring the Claude ACP branch, reusing AcpChatModel unchanged
- `2026-07-15-multi-provider-execution-P01-S04` - Confirm workspace/environment.py's scrub list does not strip ANTHROPIC_BASE_URL or ANTHROPIC_AUTH_TOKEN
- `2026-07-15-multi-provider-execution-P01-S05` - Add a Provider.ZAI branch to probe_provider_readiness and classify_provider_command, never emitting a secret
- `2026-07-15-multi-provider-execution-P01-S06` - Live-probe the real Z.ai endpoint for Anthropic Messages API fidelity (tool-calling schema, streaming chunk shape) through claude-agent-acp before marking any profile eligible
- `2026-07-15-multi-provider-execution-P01-S07` - Unit and live-probe tests for the Z.ai env-injection path, readiness branch, and factory dispatch
- `2026-07-15-multi-provider-execution-P02-S08` - Resolve Codex's non-interactive/headless authentication model against the real Codex CLI (API key vs. ChatGPT-session vs. local device auth)
- `2026-07-15-multi-provider-execution-P02-S09` - Add Provider.CODEX to the Provider enum with model-map entries
- `2026-07-15-multi-provider-execution-P02-S10` - Implement CodexChatModel(BaseChatModel) driving codex app-server's JSON-RPC-over-stdio surface directly, following the mock_chat_model.py non-ACP precedent
- `2026-07-15-multi-provider-execution-P02-S11` - Reuse _subprocess.py's protocol-agnostic process lifecycle helpers (spawn/kill-tree) for Codex subprocess management
- `2026-07-15-multi-provider-execution-P02-S12` - Add a classify_codex_command-style readiness check and a Provider.CODEX branch in probe_provider_readiness, never emitting a secret
- `2026-07-15-multi-provider-execution-P02-S13` - Add a factory.py dispatch branch for Provider.CODEX
- `2026-07-15-multi-provider-execution-P02-S14` - Unit tests for CodexChatModel's JSON-RPC framing and subprocess lifecycle, plus a live probe against the real codex app-server once the auth model is resolved
- `2026-07-15-multi-provider-execution-P04-S18` - Check whether the dashboard/engine's own schema treats provider as an open string or a closed enum
- `2026-07-15-multi-provider-execution-P04-S19` - Document the outcome in a phase summary
- `2026-07-15-multi-provider-execution-P03-S15` - Author or extend a team profile assigning distinct providers per role (researcher=codex, synthesist=claude, adr-author=zai) on the vaultspec-adr-research preset
- `2026-07-15-multi-provider-execution-P03-S16` - Run a live research_adr run under the mixed-provider profile end to end riding the standing acceptance harness (PW7) once the adr-authoring-orchestration P04.S10 finale harness lands, verifying per-role attribution and document quality hold across providers
- `2026-07-15-multi-provider-execution-P03-S17` - Verify the a2a-edge discovery/eligibility responses correctly surface the new providers with safe reasons on failure and no secrets

### plan

- `2026-07-15-multi-provider-execution-plan` - `multi-provider-execution` plan

### reference

- `2026-07-15-multi-provider-execution-reference` - `multi-provider-execution` reference: `provider integration map: env vars, spawn paths, and config seams`

### research

- `2026-07-15-multi-provider-execution-research` - `multi-provider-execution` research: `provider matrix, ACP env-injection seam, and per-role assignment for Codex, Claude, and Z.ai across the LangGraph pipeline`
