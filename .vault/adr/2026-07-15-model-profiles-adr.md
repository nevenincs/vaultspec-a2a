---
tags:
  - "#adr"
  - "#model-profiles"
date: '2026-07-15'
related:
  - "[[2026-02-27-team-composition-topology-adr]]"
  - "[[2026-07-14-adr-authoring-orchestration-adr]]"
  - "[[2026-07-15-model-profiles-research]]"
  - "[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr]]"
  - "[[2026-08-02-model-profiles-acp-model-selection-research]]"
superseded_by: '2026-08-02-provider-model-catalog-adr'
modified: '2026-08-02'
body_hash: 'sha256:d5725d8aa61d2683428066f9bb32f82c5d1247c0e9b59f9d1e35d0fbc2efccfa'
---
# `model-profiles` adr: `named model profiles, shared resolution, and backend-served eligibility` | (**status:** `superseded`)

## Problem Statement

The dashboard's authoring surface needs truthful execution-target and model-profile controls for heterogeneous teams. Callers may select a declared profile but may not author a model map. The original decision established validation, eligibility, and frozen assignments; subsequent evidence shows that the Claude/Z.ai ACP path does not actually apply its resolved concrete model, that Kimi can override it from a global setting, and that the existing `fast` profile does not constrain every role to low cost. Grounding: `2026-07-15-model-profiles-research` and `2026-08-02-model-profiles-acp-model-selection-research`.

## Considerations

- A soft edge selects only a bounded `profile_id`; profile policy stays server-owned.
- Discovery, launch, compilation, restart, and the provider subprocess must observe the same frozen concrete model, or displayed model truth is not execution truth.
- ACP configuration is negotiated per session. The advertised configuration identifier, not an assumed method or key, is the runtime authority.
- Default pytest excludes service tests, but explicitly selected service tests can make real-provider calls; the selected model must be provable before a prompt.
- The ACP v1 wire-conformance ADR remains governing for protocol-contract replacement and its direct-removal posture.

## Considered options

- **Caller-authored per-role model maps on run-start.** Rejected: unbounded validation surface, reintroduces drift, and leaks model policy ownership to clients.
- **Keep capability-only freezing and rely on provider defaults.** Rejected: a mapping change, global override, or provider default can make a frozen profile execute a different concrete model.
- **Keep the `fast` profile as a partial cost reduction and add a hidden test profile.** Rejected: it does not provide a spend-control invariant and creates an unserved, unauditable selector.
- **Retain `session/set_model` or accept both ACP configuration shapes.** Rejected: the former is obsolete and the latter manufactures an unsupported compatibility contract.
- **Named backend-defined profiles, frozen concrete-model execution, negotiated ACP selection, and an all-low served `fast` profile.** Accepted.

## Constraints

- The A2A edge contract remains profile-id-only and v1-additive; arbitrary model-name and per-role maps remain forbidden.
- A profile's safe disclosure, persisted assignment, compiler input, factory input, and selected provider setting must agree on its concrete model name.
- ACP must select only a configuration option returned by that session. Missing option, malformed response, rejected selection, or no observed selected value must fail before `session/prompt`.
- No aliases, fallbacks, compatibility flags, or legacy `session/set_model` transport may remain.
- An all-low profile minimizes model tier, not provider billing, quotas, tokens, or rate limits; live tests still require explicit operator authorization and observable prerequisites.

## Implementation

- **Profiles and precedence.** A profile remains a named whole-team configuration in team TOML. Selected profile assignment is the top layer above worker override, agent TOML, and team defaults. `team-defaults` remains the empty implicit profile. The dashboard and every other permitted edge may submit only an eligible declared profile id.
- **Freeze concrete execution.** Run start resolves and persists per-role provider, capability, concrete model name, fallback order, and attribution before dispatch. Restart and compiler construction must consume the persisted concrete model name rather than resolve a name again from mutable mappings. A global provider setting is only a default when no profile-resolved name exists; it may never override a selected or frozen model.
- **ACP model selection.** Claude and Z.ai factories pass the resolved concrete model as the ACP model's desired model. Session setup retains the negotiated `configOptions`, finds the advertised model-selection option, and invokes `session/set_config_option` using `{sessionId, configId, value}` before any prompt. The result must demonstrate the selected desired value. Failure is typed and terminal for the run before a provider prompt. The obsolete `session/set_model` request, its request id, and malformed generic setter are removed directly.
- **Truthful low-cost profile.** The served `fast` profile means every role in the team resolves to `Model.LOW`. Its description and every provider-axis overlay must be explicit and truthful. The solo-coder preset provides the same low profile. There is no hidden test-only profile.
- **Test enforcement.** Every real-provider or service test selects `fast` or passes `Model.LOW` directly where it bypasses profile creation, and asserts the resolved assignment is all-low before spawning a provider. ACP coverage includes a real adapter initialize/session/configuration exchange that reaps the subprocess before a prompt; a separate explicit live turn proves the selected low tier where credentials are deliberately present. Deterministic tests remain the broad cost-free floor.

## Rationale

Named profiles remain the correct configuration-owned selector. Making the frozen concrete name authoritative closes the gap between dashboard disclosure and execution, while the negotiated ACP path keeps model selection compatible with the actual adapter rather than a guessed RPC. An all-low served profile provides a visible, reviewable cost-control contract instead of a test bypass. Direct removal avoids carrying obsolete protocol surface into future providers.

## Consequences

- Dashboard and A2A profile disclosure becomes a runtime claim that every provider must either honour or refuse before prompting.
- Claude and Z.ai gain an explicit model-configuration handshake; unsupported adapter versions fail closed instead of consuming their default model.
- Kimi loses its ability to override a selected profile through a global model setting.
- `fast` changes from partial latency reduction to a product-visible all-low contract; callers wanting higher quality must choose another profile intentionally.
- Real-provider tests gain a pre-spawn low-tier assertion and a no-prompt ACP handshake proof, but provider billing and quota controls remain outside this ADR.
- Supersession posture: this amends `2026-07-15-model-profiles-adr` in place and refines its freeze-and-persist and profile semantics. It relies on, but does not supersede, `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr`.
