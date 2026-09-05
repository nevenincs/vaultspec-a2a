---
tags:
  - '#plan'
  - '#provider-model-catalog'
date: '2026-08-02'
tier: L2
related:
  - '[[2026-08-02-provider-model-catalog-adr]]'
  - '[[2026-08-02-provider-model-catalog-research]]'
  - '[[2026-08-02-provider-model-catalog-reference]]'
  - '[[2026-09-05-embedded-runtime-remediation-research]]'
modified: '2026-09-05'
body_hash: 'sha256:c60b1f4dae25bb4b71d4e96c241c3d976a4dfc0b20cdd794c97e137c18a3f420'
---
<!-- RETIRED: S14, S18 -->

# `provider-model-catalog` plan

## Description

Execute the accepted provider-owned catalog decision across A2A and Dashboard.
P01 owns backend discovery, health, bounded selection, freezing, replay, and
provider-specific remediation. P02 owns the Rust edge and agent-panel chooser.
P03 proves the assembled contract and completes the mandatory review, finding
classification, audit queue, and lifecycle reconciliation.

## Steps

### Phase `P01` - Implement A2A provider catalog and bounded run selection

Build the provider-owned catalog, structured health, provider-native controls, frozen selection, replay, and provider-specific execution adapters in A2A.

- [x] `P01.S01` - Define normalized provider catalog, native-control, selection-reference, catalog-state, structured-health, and refresh-cache contracts; `src/vaultspec_a2a/providers/provider_catalog.py`.
- [x] `P01.S02` - Implement prompt-free generic ACP catalog discovery with bounded cleanup and authentication evidence; `src/vaultspec_a2a/providers/_acp_session.py`.
- [x] `P01.S03` - Implement Codex model, reasoning-effort, service-tier, capability, and account discovery without a completion; `src/vaultspec_a2a/providers/codex_catalog.py`.
- [x] `P01.S04` - Implement Kimi configured-lane model and thinking-control discovery against the installed CLI contract; `src/vaultspec_a2a/providers/kimi_catalog.py`.
- [x] `P01.S05` - Implement authenticated OpenAI-compatible model discovery with unsupported metadata explicitly absent; `src/vaultspec_a2a/providers/openai_catalog.py`.
- [x] `P01.S06` - Register execution-mode-specific catalog adapters and report unsupported enumeration honestly; `src/vaultspec_a2a/providers/factory.py`.
- [x] `P01.S07` - Serve provider catalogs, refresh state, structured health, selectability, and safe reasons through bounded gateway contracts; `src/vaultspec_a2a/api/`.
- [x] `P01.S08` - Replace new-run profile admission with required served selection, bounded overrides, explicit fallbacks, controls, validation, and replay identity; `src/vaultspec_a2a/api/routes/gateway.py`.
- [x] `P01.S09` - Freeze catalog provenance, exact model values, controls, fallbacks, execution modes, and schema version through compilation; `src/vaultspec_a2a/providers/model_profiles.py, src/vaultspec_a2a/graph/compiler.py`.
- [ ] `P01.S10` - Remove every product provider/model/profile authority, static external model map, deprecated provider alias, legacy reader/writer/DTO and legacy restart or redispatch branch; remove the ACP `models.availableModels` compatibility fallback and retire the complete `gemini/gemini-cli-acp` provider, execution-mode, settings, auth, provisioning, permission, preset, factory, catalog and wire surface; reject retired input and stored state with a typed unsupported/incompatible outcome before construction or dispatch, without translation, migration or substitution; `src/vaultspec_a2a/team/, src/vaultspec_a2a/graph/enums.py, src/vaultspec_a2a/providers/, src/vaultspec_a2a/control/, src/vaultspec_a2a/api/`.
- [ ] `P01.S11` - Prove configOptions-only ACP catalog discovery, stale refusal, health separation, served validation, same-id replay and current-schema frozen restart with real behavior; prove `models.availableModels`, the retired Gemini provider/mode/configuration surface, and every other legacy provider/model/profile input or durable state are typed refused before construction or dispatch with no disclosure, translation, migration, substitution or redispatch; assert the supported-provider and exact-mode inventories contain no Gemini lane; retain the ER19 observed-availability correction and exact-mode admission assertions; `src/vaultspec_a2a/providers/tests/, src/vaultspec_a2a/api/tests/, src/vaultspec_a2a/service_tests/`.

### Phase `P02` - Implement Dashboard and engine selection surfaces

Add the bounded Rust edge, live catalog store, provider/model/control chooser, authoritative frozen assignment display, and truthful unavailable states in Dashboard.

- [x] `P02.S12` - Add the provider-catalog verb and validate bounded catalog, health, selection, control, fallback, and override shapes without hard-coded enums; `Y:/code/vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/src/routes/ops/a2a.rs`.
- [x] `P02.S13` - Directly migrate the Dashboard store, composer chooser, and obsolete profile fixtures to opaque provider catalogs, structured health, required selection, controls, and frozen assignments; `Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/stores/server/agent/, frontend/src/app/agent/ComposerModelPicker.tsx, frontend/src/app/agent/Composer.tsx, frontend/dev/visual-review/specimens/agent.tsx`.
- [x] `P02.S15` - Add bounded per-role model and control overrides and explicit served fallbacks without arbitrary role keys or model values; `Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/app/agent/`.
- [x] `P02.S16` - Display configured, transport, authentication, catalog freshness, admission, and selectability states truthfully; `Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/app/agent/`.
- [x] `P02.S17` - Render exact frozen provider, model, native controls, and provenance returned for active runs; `Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/app/agent/TeamRunHeader.tsx`.

### Phase `P03` - Integrate, review, and reconcile the cross-project contract

Prove the selected provider, model, and controls across the live edge, review both implementations, classify findings, and update the audit trail.

- [ ] `P03.S19` - Drive a real catalog query and run start through Dashboard, Rust, and A2A, prove the frozen selection reaches prompt setup unchanged, and retain the exact current external-mode inventory with ACP entries derived only from `configOptions` and no retired Gemini lane; `src/vaultspec_a2a/service_tests/, Y:/code/vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/`.
- [ ] `P03.S20` - Prove refresh, stale selection, unauthenticated, unavailable, admitted, replay, current-schema restart, and typed refusal of every legacy provider/model/profile request, response and persisted-state shape across both repositories, including `models.availableModels` and retired Gemini provider/mode/configuration values, with no registration, translation, migration, substitution or redispatch; `src/vaultspec_a2a/service_tests/, Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/stores/server/agent/`.
- [ ] `P03.S21` - Run the formal A2A implementation review and record every classified finding in the audit queue; `src/vaultspec_a2a/, .vault/audit/`.
- [ ] `P03.S22` - Run the formal Dashboard and Rust implementation review and record every classified finding in the audit queue; `Y:/code/vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/, frontend/src/, .vault/audit/`.
- [ ] `P03.S23` - Reconcile ADRs, plans, execution records, audits, and follow-up work and close only evidence-proven steps; `.vault/adr/, .vault/plan/, .vault/exec/, .vault/audit/`.

## Parallelization

P01 and P02 execute in parallel against the accepted wire contract with
exclusive repository ownership. P03 starts after both phases have a focused
green test boundary. Within P01 and P02, Steps retain their listed order where
later work consumes an earlier contract; independent provider adapters may be
developed concurrently inside the owning A2A agent turn.

## Verification

- A2A serves no repository-authored external model identifiers for product runs.
- At least one real provider catalog exposes its model and native control choices
  without issuing a completion.
- Dashboard selects only current, selectable A2A-served entries and forwards the
  opaque selection through the Rust boundary.
- Run start revalidates and freezes exact current-schema provider values; status,
  same-id replay and current-schema restart reproduce them unchanged; stale,
  conflicting and legacy selections fail closed before construction or dispatch.
- Structured health distinguishes configuration, transport, authentication,
  catalog, admission, and selectability.
- Kimi installed-lane drift is either repaired with real-behavior proof or
  disclosed as unselectable with a truthful reason; the retired Gemini lane is
  absent from provider, mode, configuration, construction, catalog and wire
  inventories rather than disclosed as blocked.
- Focused A2A, Rust, frontend, accessibility, and assembled cross-repo tests pass
  without fakes, mocks, monkeypatches, skips, xfails, or shadow business logic.
- Formal reviews classify every finding and record it in the owning audit queue;
  all critical and high findings are remediated before completion.
