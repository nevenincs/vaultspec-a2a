---
tags:
  - '#reference'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-multi-provider-execution-research]]"
---

# `multi-provider-execution` reference: `provider integration map: env vars, spawn paths, and config seams`

A file:line map of the exact seams a Z.ai and a Codex provider integration touch, grounding `[[2026-07-15-multi-provider-execution-adr]]`. Companion to `[[2026-07-15-multi-provider-execution-research]]`; this document is the blueprint, the research document is the evidence trail.

## Findings

### Provider dispatch seam

`src/vaultspec_a2a/providers/factory.py`:

- `Provider` enum consumed here is defined in `src/vaultspec_a2a/graph/enums.py:128-135` (`CLAUDE`, `GEMINI`, `MOCK`, `OPENAI`, `ZHIPU`). A new provider requires a new member here plus `MODEL_MAP`/`PROVIDER_DEFAULT_MODELS` entries (`graph/enums.py:164-191` pattern for `OPENAI`/`ZHIPU`).
- `ProviderFactory.create` (`factory.py:273-494`) is the single dispatch point: a `supported` set gate (`factory.py:303-312`), model-name resolution, then a per-provider `if` branch. New providers add a branch here.
- The **Claude ACP branch** (`factory.py:353-393`) is the template for a Z.ai variant: same `_classify_acp_command`/`AcpChatModel` construction, only `env_vars` and the `auth_mode` label differ.
- The **Gemini branch** (`factory.py:395-438`) is the template for the `_build_zai_env`-style helper: `_build_gemini_env` (`factory.py:41-66`) shows the pattern of building an explicit env dict from `settings.*` fields, independent of process-inherited env.
- The **Zhipu/OpenAI branches** (`factory.py:440-491`) are the template for a non-subprocess provider registered via `ChatOpenAI(**kwargs)` — not applicable to Codex (which is not an OpenAI-Chat-Completions-compatible endpoint per the research findings) but relevant if a future provider does speak an OpenAI-compatible HTTP API.
- `classify_provider_command` (`factory.py:235-267`) is the no-instantiation readiness seam consumed by `providers/model_profiles.py:369-385` (`_command_readiness`). A new subprocess-based provider (Z.ai variant, Codex) needs a `classify_*_command`-style branch here so `probe_provider_readiness` can report readiness without spawning.

### Env-injection seam (ACP path only)

`src/vaultspec_a2a/providers/acp_chat_model.py:230-289` (`_astream`):

- Line 251: `env = resolve_env_vars(_ws_path)` — base env, secrets scrubbed (`workspace/environment.py:70-89`).
- Line 252: `env.update(self.env_vars)` — provider-supplied overrides applied **after** scrubbing; this is where a Z.ai variant's `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` land. `workspace/environment.py`'s `scrub_keys` (lines 70-89) does not include either name, so they survive the base-env build untouched — only `self.env_vars` needs to carry them.
- Lines 257-258: `ANTHROPIC_API_KEY` is popped only when `CLAUDE_CODE_OAUTH_TOKEN` is present. `ANTHROPIC_API_KEY` is unconditionally scrubbed at the base-env layer regardless (`environment.py:72`), so this is a non-issue for a Z.ai variant using `ANTHROPIC_AUTH_TOKEN`.
- Lines 264-268: `CLAUDECODE` popped, `CLAUDE_CODE_DISABLE_*` flags set — provider-neutral, apply to any Claude-CLI-spawning provider including Z.ai.
- Lines 279-280: `ENABLE_TOOL_SEARCH=0` when `allowed_tools` is set — Claude-CLI-specific MCP-bridging workaround; inherited free by Z.ai, not applicable to Codex.

`claude-agent-acp` wrapper's own gateway hook (informational, upstream/vendored, not this repo's code to change): `knowledge/repositories/claude-agent-acp/src/acp-agent.ts:171-182` (`GatewayAuthMeta` type), `:475` (read from `session/new` `_meta`), `:1404-1415` (`createEnvForGateway` — emits `ANTHROPIC_BASE_URL`/`ANTHROPIC_CUSTOM_HEADERS`/empty `ANTHROPIC_AUTH_TOKEN`), `:1242-1246` (env layering: `process.env` base + gateway overrides). A2A does not need this hook — the simpler path is env-var injection at the Python spawn layer (`acp_chat_model.py:252`), matching how Claude's own OAuth token is injected today.

### Settings/credential seam

`src/vaultspec_a2a/control/config.py`: existing per-provider credential fields — `claude_code_oauth_token` (:163), `gemini_api_key` (:128), `openai_api_key` (:155), `zhipu_api_key` (:159), plus `acp_backend` (:290, `Literal["node","binary"]`). A Z.ai variant needs analogous `zai_base_url`/`zai_auth_token` (or similarly named) settings fields; Codex needs whatever credential model its chosen invocation mode requires (see research: unresolved whether headless Codex needs an API key or a local session).

### Readiness/eligibility seam

`src/vaultspec_a2a/providers/model_profiles.py:316-366` (`probe_provider_readiness`): one `if provider == Provider.X` branch per provider, checking `settings.*` credential presence then `_command_readiness` for subprocess providers. New providers add a branch here; the function's contract (never emit a secret, presence/resolvability only) is unchanged by new providers.

### Per-role assignment seam

- `TeamProfileRoleConfig` (`team/team_config.py:290-301`) and `TeamProfileConfig` (`:304-316`): the profile-overlay schema, keyed by worker `agent_id`. Already sufficient for per-role provider assignment across **distinct** roles (researcher/synthesist/adr-author/doc-reviewer).
- `resolve_role_assignment` (`providers/model_profiles.py:184-253`) and `resolve_effective_assignment` (`:256-304`): the resolution entry points; provider-agnostic, no change needed for new `Provider` members beyond the enum/factory work above.
- **Fan-out gap**: `ResearchThreadSpec` (`team/team_config.py:319-329`) has no model overlay field; `_resolve_research_adr_models` (`graph/compiler.py:942-953`) resolves one model per role name, not per thread spec, so `_compile_research_adr`'s diverge stage (`graph/compiler.py:1085-1100`) hands every parallel researcher branch the same `models["researcher"]` instance. Extending per-branch provider assignment requires adding a model overlay to `ResearchThreadSpec` and threading a per-spec model resolution through `_resolve_research_adr_models`/`_make_research_producer`.

### Codex integration seam (net-new, no existing hook)

No file in `src/vaultspec_a2a/providers/` currently drives a non-ACP JSON-RPC subprocess. The nearest structural precedent is `providers/mock_chat_model.py` (a `BaseChatModel` with no subprocess at all) for the class shape, and `providers/_subprocess.py`'s process-lifecycle helpers (spawn/kill-tree, protocol-agnostic) for process management. The installed codex plugin's own JSON-RPC client (`C:\Users\hello\.claude\plugins\cache\openai-codex\codex\1.0.4\scripts\lib\app-server.mjs:81-241,331`) is the reference implementation for the wire framing (`id`/`method`/`params` over stdin/stdout) a new `CodexChatModel` would need to replicate in Python — it is not itself reusable as a dependency (it is a Node.js script bundled with a different Claude Code plugin, not a library this repo can import).
