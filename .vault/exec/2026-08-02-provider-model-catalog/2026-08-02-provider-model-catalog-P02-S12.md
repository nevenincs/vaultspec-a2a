---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:9409bef7f4555e0a126168a76be92facb6c872717d2218c50c86c11edc6cbeb5'
step_id: 'S12'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---

# Add the provider-catalog verb and validate bounded catalog, health, selection, control, fallback, and override shapes without hard-coded enums

## Scope

- `Y:/code/vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/src/routes/ops/a2a.rs`

## Description

- Add the bounded `provider-catalog` read verb, preserving A2A's catalog and health response without a Dashboard-side reclassification.
- Replace new-run `profile_id` acceptance with a required opaque selection reference containing provider, execution lane, catalog revision, entry, and provider-native controls.
- Bound controls, per-role override keys and maps, fallbacks, opaque values, and unknown request fields while leaving catalog membership and role authority to A2A.
- Prove the route, exact opaque forwarding, retired profile rejection, and resource ceilings through the focused Rust boundary and loopback tests.

## Outcome

- The engine now forwards the engine-owned workspace scope to `GET /v1/provider-catalog` and returns the sibling envelope unchanged, retaining A2A as the sole owner of structured health and catalog truth.
- `run-start` sends only an A2A-served whole-team selection, optional ordered fallbacks, and bounded per-role selection overrides. It carries no provider or model enum and rejects the retired `profile_id` field during deserialization.
- `cargo fmt --check --package vaultspec-api`, `cargo clippy -p vaultspec-api --lib -- -D warnings`, and `cargo test -p vaultspec-api routes::ops::a2a::tests --lib -- --nocapture` passed: 30 tests passed, zero failed.

## Notes

- Dashboard's semantic-search service was running but degraded because its shared installation has a CPU-only PyTorch build. The required semantic calls, status check, doctor, and warmup were attempted before source inspection; no global tooling was changed. Grounding continued from the accepted ADR, research, reference, plan, Dashboard ADR/plan, and focused current-source reads.
- A2A provider-catalog route implementation and served-membership validation remain owned by P01.S07 and P01.S08. The A2A catalog-contract owner confirmed the selection-reference field names used here.
- Formal review initially found the catalog path had only structural coverage. The finding was resolved with a real TCP loopback through the public handler and recorded in `2026-08-02-provider-model-catalog-implementation-review-audit`.
