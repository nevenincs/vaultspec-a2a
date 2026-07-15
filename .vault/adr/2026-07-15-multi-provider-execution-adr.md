---
tags:
  - '#adr'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-multi-provider-execution-research]]"
  - "[[2026-07-15-multi-provider-execution-reference]]"
  - "[[2026-07-15-model-profiles-adr]]"
  - "[[2026-07-14-adr-authoring-orchestration-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
---

# `multi-provider-execution` adr: `provider matrix, per-role assignment, and cross-repo initialization for Codex, Claude, and Z.ai` | (**status:** `accepted`)

**Ratified 2026-07-15** (interactive owner decision): all decisions below are accepted as drafted, including the per-branch-diversity deferral and the mandatory cross-repo check in Constraints. Execution proceeds per `2026-07-15-multi-provider-execution-plan`, approved the same day with Phase 1 (Z.ai) and Phase 2 (Codex) authorized to run in parallel.

## Problem Statement

The research_adr graph topology (`adr-authoring-orchestration-adr`) and the model-profiles precedence chain (`model-profiles-adr`) currently run one provider family, LangChain-`BaseChatModel`-shaped, resolved per role. The owner's mission requires mixing Codex, Claude, and Z.ai (Z.ai routed through the existing Claude Code CLI) inside a single run, with per-role provider assignment (researcher=codex, synthesist=claude, adr-author=zai as a worked example) and clarity on what, if anything, becomes a cross-repo (dashboard/vaultspec-cli) contract event. Grounding: `2026-07-15-multi-provider-execution-research`, `2026-07-15-multi-provider-execution-reference`.

## Considerations

- Z.ai is not a new integration — it is the existing Claude ACP path (`AcpChatModel`, `_classify_acp_command`) with a different env-injection payload; the wrapper CLI's own `GatewayAuthMeta`/`createEnvForGateway` hook and the Python-side `env.update(self.env_vars)` seam (`acp_chat_model.py:252`) both already exist for exactly this purpose (research, reference).
- Codex speaks neither ACP nor a Chat-Completions-compatible HTTP API in its local-runtime form; its `codex app-server` is a bespoke JSON-RPC-over-stdio protocol (research). Adapting it to ACP would duplicate the codex-companion plugin's own client for no benefit; a dedicated non-ACP `BaseChatModel` (precedented by `providers/mock_chat_model.py`) is the cheaper, contract-clean path.
- The model-profiles precedence chain and `TeamProfileRoleConfig` already support per-role provider assignment across **distinct** worker `agent_id`s with zero new mechanism (reference: `team_config.py:290-301`, `model_profiles.py:184-253`).
- The research_adr diverge stage resolves one model per role name and hands it to every parallel fan-out branch (`_resolve_research_adr_models`, `graph/compiler.py:942-953,1085-1100`); `ResearchThreadSpec` has no model overlay. Per-**branch** (as opposed to per-role) provider diversity is not possible without a schema extension (research, reference).
- The a2a-edge contract is v1-additive and `Provider` is served as a plain string, not a wire-level closed enum on A2A's side (`graph/enums.py:128-135`, serialized via `.value`). Whether the dashboard/engine's own schema is closed is unverified — dashboard-repo state this ADR cannot ground (research).
- The LangGraph compiler and research_adr topology are provider-agnostic at the graph level (consume only `BaseChatModel`, read documents back via `AIMessage.name`); the two provider-specific behaviors found (`ENABLE_TOOL_SEARCH=0`, OAuth/API-key mutual exclusion) are both confined to the ACP/Claude-CLI path and either inherited free by Z.ai or irrelevant to Codex (research).

## Considered options

- **Build a from-scratch Z.ai HTTP client bypassing Claude Code entirely.** Rejected: throws away the exact env-injection hook the `claude-agent-acp` wrapper already ships for this purpose, and duplicates tool-calling/permission-bridge logic the ACP path already solves.
- **Adapt Codex to speak ACP via a translation shim.** Rejected: Codex's `app-server` JSON-RPC shape is bespoke, not ACP; a shim would re-implement what the vendored codex-companion plugin already does, with no reuse benefit, and adds an extra translation layer to maintain.
- **Give every `ResearchThreadSpec` branch its own model overlay now, as part of this feature.** Deferred, not rejected: real gap, but out of scope for a Codex/Claude/Z.ai matrix decision — the four named research_adr roles (researcher, synthesist, adr-author, doc-reviewer) already get correct per-role diversity via the existing profile mechanism; per-branch diversity inside one fan-out is a distinct, separable schema extension the plan may pick up as its own phase.
- **Provider matrix + per-role assignment via existing mechanisms, Codex via a new non-ACP `BaseChatModel` (chosen).** Z.ai: a `Provider.ZAI` enum member, a `_build_zai_env` helper mirroring `_build_gemini_env`, and a `factory.py` dispatch branch mirroring the Claude ACP branch — reuses `AcpChatModel` unchanged. Codex: a `Provider.CODEX` enum member and a new `CodexChatModel(BaseChatModel)` driving `codex app-server`'s JSON-RPC surface directly (or shelling to the companion script), following the `mock_chat_model.py` precedent of a non-ACP `BaseChatModel`, reusing `_subprocess.py`'s protocol-agnostic process lifecycle helpers. Per-role assignment: no new mechanism, `TeamProfileRoleConfig` already carries it. Per-branch fan-out diversity: explicitly out of scope for this ADR, tracked as a follow-on schema extension.

## Constraints

- Z.ai's actual API fidelity to the Anthropic Messages API surface `claude-agent-acp` depends on (tool-calling schema, streaming shape) is unverified; readiness must be proven with a live probe against the real endpoint before any profile marks it eligible, mirroring the model-profiles ADR's existing "presence/resolvability, not proven-working" posture for readiness. **STILL OPEN** (2026-07-15 resumability audit): P01.S02/S03 have landed `zai_base_url`/`zai_auth_token` settings and the `_build_zai_env` injection path in-flight (uncommitted, executor-opus-5), with unit coverage for the credential-present and credential-absent ("none_detected" auth_mode) branches; no `ZAI_AUTH_TOKEN` is configured in this environment, so the live fidelity probe (P01.S06) is currently blocked on credentials, not on missing code. Evidence when resumed: `src/vaultspec_a2a/providers/factory.py` (`_build_zai_env`), `src/vaultspec_a2a/providers/tests/test_factory.py` (Z.ai test block).
- Codex's non-interactive/headless authentication model (API key vs. ChatGPT-session vs. local device auth) is unresolved; the settings/credential seam (`control/config.py`) cannot be designed until this is confirmed against the actual Codex CLI's supported auth modes. **RESOLVED** (2026-07-15 resumability audit, P02.S08, executor-opus-6, in-flight uncommitted): Codex's `app-server` authenticates from a persisted local ChatGPT session in its Codex home (`~/.codex` by default); no API key or secret env injection is required. A `CODEX_HOME` settings override (non-secret, mirrors `gemini_cli_home`) was added rather than inventing a credential field. Evidence: `src/vaultspec_a2a/control/config.py` (`codex_home` field), `src/vaultspec_a2a/providers/codex_chat_model.py` module docstring and `_build_env`.
- The a2a-edge contract stays v1-additive: new `Provider` members and new profile/eligibility values are additive fields/enum values, never renames — consistent with the model-profiles ADR's existing constraint.
- Cross-repo contract event (flagged, not resolved here): if the dashboard/engine's own schema treats the `provider` field as a closed enum rather than an open string, it needs its own update before `zai`/`codex` values validate there. This ADR does not authorize any change to the dashboard/engine repo; the plan's verification phase must check this before declaring the feature cross-repo-complete, and any required dashboard-side change is a separate cross-repo contract event, not silently assumed compatible.
- Per-branch (fan-out) provider diversity inside `research_adr`'s diverge stage is explicitly deferred; this ADR's per-role assignment claim applies to the four named roles, not to N parallel branches of the same role.

## Implementation

High-level, elaborated by the plan (`2026-07-15-multi-provider-execution-plan`):

- Add `Provider.ZAI`/`Provider.CODEX` to `graph/enums.py` with `MODEL_MAP`/`PROVIDER_DEFAULT_MODELS` entries.
- Z.ai: `_build_zai_env` in `factory.py` (pattern: `_build_gemini_env`, `factory.py:41-66`), a `classify_provider_command`-compatible readiness check reusing `_classify_acp_command`, and a `factory.py` dispatch branch mirroring the Claude branch (`factory.py:353-393`) with Z.ai's `env_vars` swapped in.
- Codex: a new `CodexChatModel(BaseChatModel)` in `providers/`, a `classify_codex_command`-style readiness check, a `factory.py` dispatch branch, and settings fields for whatever credential model the auth investigation confirms.
- `probe_provider_readiness` (`model_profiles.py:316-366`) gains branches for both new providers, never emitting a secret.
- No change required to the research_adr graph topology, the phase-gate/submitter mechanism, or the a2a-edge wire contract for the per-role case; per-branch fan-out diversity, if picked up, extends `ResearchThreadSpec` and `_resolve_research_adr_models`/`_make_research_producer` in a later phase.

## Rationale

Both new providers ride mechanisms the codebase already has proven working for a structurally identical case: Z.ai is Gemini's `_build_*_env` pattern applied to the Claude ACP path instead of the Gemini ACP path; Codex is `mock_chat_model.py`'s non-ACP `BaseChatModel` pattern applied to a real subprocess instead of a stub. Per-role assignment needs no new mechanism because `model-profiles-adr` already built a profile-topped precedence chain generic over provider. Deferring per-branch fan-out diversity and the dashboard-schema cross-repo question keeps this ADR's decision surface to what the evidence actually supports, rather than assuming unverified cross-repo or third-party-API compatibility.

## Consequences

- Positive: Z.ai lands as a near-zero-new-code config variant; Codex lands without inventing an ACP-compatibility shim; per-role mixed-provider runs (researcher=codex, synthesist=claude, adr-author=zai) become possible with the existing profile schema once both providers exist.
- Negative / open: per-branch (fan-out) provider diversity remains unsupported until a follow-on schema extension; Z.ai and Codex both carry unverified real-world compatibility risk (API fidelity, auth model) that must be closed by live probes, not assumed from this ADR; the dashboard-side schema openness for new provider values is an unresolved cross-repo question this ADR explicitly does not authorize resolving unilaterally.
- Future: if per-branch diversity or additional providers (Gemini already exists; others may follow) are needed, the `TeamProfileRoleConfig`/`ResearchThreadSpec` schema is the extension point, not a new resolution mechanism.
