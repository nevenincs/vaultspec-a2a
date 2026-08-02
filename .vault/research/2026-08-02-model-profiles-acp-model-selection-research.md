---
tags:
  - '#research'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:6907a55190b05ecf4e5da8818790f308b3c856a0d9672e93213d570863f22df2'
related:
  - "[[2026-07-15-model-profiles-adr]]"
---

# `model-profiles` research: `ACP model selection and low-cost test profile`

Question: does the model level selected at the dashboard (or another permitted
soft edge) survive to every provider, and can real-provider tests be made
unambiguously low cost? The evidence shows that named profile selection is
validated, frozen, and passed through the A2A graph, but the Claude and Z.ai
ACP branches discard the selected concrete model before construction. The
current `fast` profile is also a mixed-cost product profile, not an all-low
test control. An ADR amendment must settle a truthful all-low profile contract
and a negotiated, fail-closed ACP model-selection contract before code changes.

## Findings

### The permitted dashboard edge selects a bounded profile, not a caller-authored model

The dashboard only submits an offered eligible `profile_id`; the A2A request
schema bounds it and the run-start route resolves and freezes it before
dispatch. The compiler receives the frozen provider/capability map. This
retains the governing ADR's configuration-owned policy, rather than adding a
soft-edge model-name override. `src/vaultspec_a2a/api/schemas/gateway.py:236-238`
`src/vaultspec_a2a/api/routes/gateway.py:352-427`
`src/vaultspec_a2a/providers/model_profiles.py:262-310`
`src/vaultspec_a2a/providers/model_profiles.py:620-666`
`src/vaultspec_a2a/graph/compiler.py:546-675`

### Capability tiers are config-selectable, but concrete mappings remain central policy

Role assignment resolves profile overlay, worker override, agent configuration,
and team defaults into a capability. The canonical `MODEL_MAP` translates that
capability to a provider model name. Therefore the levels are not hard-coded
per LangGraph persona, although the concrete provider mapping is intentionally
centralized code policy. `src/vaultspec_a2a/providers/model_profiles.py:245-310`
`src/vaultspec_a2a/graph/enums.py:213-294`

### Claude and Z.ai do not apply the resolved ACP model today

Both factory branches resolve `model_name` yet construct `AcpChatModel` without
it. Session setup then keeps the session id and modes but discards the adapter's
negotiated `configOptions`. The retained `session/set_model` request is not the
negotiated configuration mechanism, while the generic configuration method
sends `key` where ACP's configuration request requires the advertised
configuration identifier. Neither path can prove that a requested model was
accepted before a prompt is sent. `src/vaultspec_a2a/providers/factory.py:684-770`
`src/vaultspec_a2a/providers/_acp_session.py:230-312`
`src/vaultspec_a2a/providers/_acp_types.py:28-127`
`src/vaultspec_a2a/providers/acp_chat_model.py:890-929`
`src/vaultspec_a2a/utils/enums.py:69`

The adapter contract documented by `@agentclientprotocol/claude-agent-acp@0.59.0`
exposes model choice as a session configuration option. The public provider
guides describe supported Claude and Z.ai model configuration, but adapter
negotiation and the returned option identifier must remain the runtime source
of truth. https://code.claude.com/docs/en/model-config
https://docs.z.ai/devpack/tool/claude

### Two further paths can defeat a frozen low-tier selection

The persisted assignment records a concrete `model_name` and describes restart
stability, but its compiler projection keeps only provider, capability, and
fallback. The compiler then resolves a model name again in the factory. A
mapping change between first dispatch and restart could therefore change the
concrete model despite the frozen record. Separately, Kimi chooses
`settings.kimi_model_name` before the resolved `model_name`, allowing a global
setting to override a selected profile. The amendment needs to require that
the frozen concrete model is the factory input on every restart and that a
global Kimi setting is only a default when no named/profile-resolved model was
selected. `src/vaultspec_a2a/providers/model_profiles.py:612-666`
`src/vaultspec_a2a/graph/compiler.py:161-167`
`src/vaultspec_a2a/providers/factory.py:572-657`
`src/vaultspec_a2a/providers/factory.py:812-815`

### The present fast profile cannot control real-provider test spend

The ADR-research preset documents that `fast` lowers only researcher and
document-reviewer; the synthesist, ADR author, and plan author fall through to
the team mid default. Provider-axis profiles also overlay providers without
lowering every role. Default pytest excludes service tests, but the service
marker includes explicit live provider turns when selected. Thus `fast` is
truthful as a lower-latency product profile but insufficient as the requested
all-low testing control. `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml:130-190`
`src/vaultspec_a2a/team/presets/teams/vaultspec-solo-coder.toml:9-40`
`pyproject.toml:192-216`
`src/vaultspec_a2a/service_tests/conftest.py:19-23`
`src/vaultspec_a2a/providers/tests/test_codex_chat_model.py:243-267`
`src/vaultspec_a2a/providers/tests/test_claude_live_turn.py:50-68`

### The test profile must remain an honest served preset, not a hidden bypass

All declared profiles are part of backend preset discovery. A hidden test-only
profile would create a second, unauditable selector and contradict the accepted
truthful-discovery contract. The viable alternatives are to make the existing
`fast` profile all-low and route live tests through it, or to add a separately
served all-low profile. The former preserves the existing public selector while
requiring its description and every provider-axis overlay to be made truthful.
The ADR must choose the product naming and enforce that every live test resolves
all selected roles to `Model.LOW` before it can start a provider process.

Not investigated: provider rate limits, token budgets, or billing-account
caps; an all-low capability assignment is spend minimization, not a monetary
spend ceiling. The exact Z.ai low/mid/high aliases also require an adapter-level
acceptance proof against its advertised configuration options.

## Sources

- `src/vaultspec_a2a/api/schemas/gateway.py:236-238`
- `src/vaultspec_a2a/api/routes/gateway.py:352-427`
- `src/vaultspec_a2a/providers/model_profiles.py:245-310,620-666`
- `src/vaultspec_a2a/graph/compiler.py:546-675`
- `src/vaultspec_a2a/graph/enums.py:213-294`
- `src/vaultspec_a2a/providers/factory.py:684-770`
- `src/vaultspec_a2a/providers/_acp_session.py:230-312`
- `src/vaultspec_a2a/providers/_acp_types.py:28-127`
- `src/vaultspec_a2a/providers/acp_chat_model.py:890-929`
- `src/vaultspec_a2a/utils/enums.py:69`
- `src/vaultspec_a2a/graph/compiler.py:161-167`
- `src/vaultspec_a2a/providers/factory.py:572-657,812-815`
- `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml:130-190`
- `src/vaultspec_a2a/team/presets/teams/vaultspec-solo-coder.toml:9-40`
- `pyproject.toml:192-216`
- `src/vaultspec_a2a/service_tests/conftest.py:19-23`
- `src/vaultspec_a2a/providers/tests/test_codex_chat_model.py:243-267`
- `src/vaultspec_a2a/providers/tests/test_claude_live_turn.py:50-68`
- `@agentclientprotocol/claude-agent-acp@0.59.0` (locally inspected adapter contract)
- https://code.claude.com/docs/en/model-config
- https://docs.z.ai/devpack/tool/claude
