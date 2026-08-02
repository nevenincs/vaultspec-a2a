---
tags:
  - '#plan'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_hash: 'sha256:5b7458a0a79a77dbeab685110a1951cf1b848ffa3fcbc032cebb333ee70642bb'
tier: L2
related:
  - '[[2026-08-02-provider-model-catalog-adr]]'
  - '[[2026-08-02-provider-model-catalog-research]]'
  - '[[2026-08-02-provider-model-catalog-reference]]'
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
- [ ] `P01.S08` - Replace new-run profile admission with required served selection, bounded overrides, explicit fallbacks, controls, validation, and replay identity; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `P01.S09` - Freeze catalog provenance, exact model values, controls, fallbacks, execution modes, and schema version through compilation; `src/vaultspec_a2a/providers/model_profiles.py, src/vaultspec_a2a/graph/compiler.py`.
- [ ] `P01.S10` - Remove provider and model policy from product presets and retire static external model-map authority while preserving legacy restart; `src/vaultspec_a2a/team/, src/vaultspec_a2a/graph/enums.py`.
- [ ] `P01.S11` - Prove catalog discovery, stale refusal, health separation, served validation, replay, frozen restart, and legacy restart with real behavior; `src/vaultspec_a2a/providers/tests/, src/vaultspec_a2a/api/tests/, src/vaultspec_a2a/service_tests/`.

### Phase `P02` - Implement Dashboard and engine selection surfaces

Add the bounded Rust edge, live catalog store, provider/model/control chooser, authoritative frozen assignment display, and truthful unavailable states in Dashboard.

- [x] `P02.S12` - Add the provider-catalog verb and validate bounded catalog, health, selection, control, fallback, and override shapes without hard-coded enums; `Y:/code/vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/src/routes/ops/a2a.rs`.
- [x] `P02.S13` - Directly migrate the Dashboard store, composer chooser, and obsolete profile fixtures to opaque provider catalogs, structured health, required selection, controls, and frozen assignments; `Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/stores/server/agent/, frontend/src/app/agent/ComposerModelPicker.tsx, frontend/src/app/agent/Composer.tsx, frontend/dev/visual-review/specimens/agent.tsx`.
- [x] `P02.S15` - Add bounded per-role model and control overrides and explicit served fallbacks without arbitrary role keys or model values; `Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/app/agent/`.
- [x] `P02.S16` - Display configured, transport, authentication, catalog freshness, admission, and selectability states truthfully; `Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/app/agent/`.
- [x] `P02.S17` - Render exact frozen provider, model, native controls, and provenance returned for active runs; `Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/app/agent/TeamRunHeader.tsx`.

### Phase `P03` - Integrate, review, and reconcile the cross-project contract

Prove the selected provider, model, and controls across the live edge, review both implementations, classify findings, and update the audit trail.

- [ ] `P03.S19` - Drive a real catalog query and run start through Dashboard, Rust, and A2A and prove the frozen selection reaches prompt setup unchanged; `src/vaultspec_a2a/service_tests/, Y:/code/vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/`.
- [ ] `P03.S20` - Prove refresh, stale selection, unauthenticated, unavailable, admitted, replay, and legacy restart behavior across both repositories; `src/vaultspec_a2a/service_tests/, Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/stores/server/agent/`.
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
- Run start revalidates and freezes exact provider values; status and restart
  reproduce them unchanged; stale and conflicting selections fail closed.
- Structured health distinguishes configuration, transport, authentication,
  catalog, admission, and selectability.
- Gemini and Kimi installed-lane drift is either repaired with real-behavior
  proof or disclosed as unselectable with a truthful reason.
- Focused A2A, Rust, frontend, accessibility, and assembled cross-repo tests pass
  without fakes, mocks, monkeypatches, skips, xfails, or shadow business logic.
- Formal reviews classify every finding and record it in the owning audit queue;
  all critical and high findings are remediated before completion.
