---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:e22a56936ba9f55ab198a173895f07e3a9f1c71c2bd9d9821fa7f61a8f3f7a29'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` `W01.P01` summary

## Changes

- `A` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `A` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W01-P01-S01.md`
- `A` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W01-P01-S02.md`
- `A` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W01-P01-S03.md`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `M` `.vault/plan/2026-09-05-embedded-runtime-remediation-plan.md`
- `A` `.vault/reference/2026-09-05-embedded-runtime-remediation-provider-selection-prerequisites-reference.md`
- `A` `.vault/reference/2026-09-05-embedded-runtime-remediation-qualification-inputs-reference.md`
- `verify:` `vaultspec-core vault check all` -> `pass`

## Notes

### Step and review history

| Step | A2A implementation/correction commits | A2A review commits | Dashboard commits | Disposition |
|---|---|---|---|---|
| `W01.P01.S01` | `87782122`, `00fa0347` | `f03464cf`, `97f8dc24` | Baseline observed at `330b2efe` | Corrected after four review findings; re-review passed. |
| `W01.P01.S02` | `e9a56ff0`, `df8645c7`, `54a871a1` | `f3483512`, `66e82243`, `803dca96` | `dbc15e6f`, `02101b52`, `89706fb2` | Two failed reviews were corrected; final review passed. |
| `W01.P01.S03` | `fefd7540` | `63a58036` | Evidence-only; current coordinated reference remains `89706fb2` | Review passed. |

### Frozen qualification baseline

S01 froze the measurable A01-A34 applicability and pre-test limits without changing acceptance thresholds. The captured source pair was A2A `0b94bf8636d7145ae9420adeb1af635ef81f9dd7` and Dashboard `330b2efe294c8ab134fff2142f9fae98afd14fec`; the built A2A executable reported `0.3.0` with SHA-256 `B5F1DA8EDD6A6DC99C3FBD81645EFBA4BDF6646544B4140F4C51AE81E2EDF08F`, while Dashboard selected A2A `d59b41b6c1ac8b6e498326ea74ab32898ac9c08b` as release `0.1.0`. That mismatch remains an explicit qualification blocker for the intended binary/consumer pair.

The frozen operational bounds distinguish broker read/control/catalog budgets of 15/60/45 seconds, broker freshness/health of 120/1.5 seconds, lifecycle freshness/stop-plan of 30/5 seconds, drain connect/max of 5/600 seconds, SQLite's 5,000ms busy timeout, and the PostgreSQL-only configured QueuePool size 5 plus overflow 10. No durable follow-up-message capacity `Q` exists, so A10 remains blocked rather than deriving a limit from results. The freeze also records the host/toolchain/configuration, complete eight-mode external inventory, conditional `deterministic/in-process-deterministic` and `mock/in-process-mock` posture, and reproducible raw-output/source digests. The current frozen binary includes test-package modules and therefore is not release-qualified.

### Coordinated consumer contract

S02 recorded the accepted Dashboard-owned contract boundary without changing wire behavior. The final Dashboard ADR/reference at `89706fb2641bd5482667437ae1e4abf2d8194fd8` authorizes exactly eleven broker operations, with exact verbs and routes, input bounds, typed success/refusal/conflict/error envelopes, identities, authentication and scope, per-operation deadlines, and retry/reconciliation rules. It retains receipt-joined lifecycle/discovery identity, forbids a foreign resident from mutation, and assigns runtime conformance to `S43-S50` and proof to `S64-S65`.

Release provenance remains the accepted producer-first flow: A2A publishes fixed per-target versioned archives and SHA-256 sidecars; Dashboard selects a released version, fetches, verifies, and bundles it without source checkout/build/commit pinning; lock, member, receipt, process, and discovery must agree. This summary records the accepted decision and its implementation owners; it creates no new architectural decision.

### Provider prerequisite state

S03 revalidated provider-model-catalog at 14/21, with `P01.S10`, `P01.S11`, `P03.S19`, and `P03.S20` open, and provider-capability-evidence at 0/4. Eight external modes are registered; only `codex/codex-app-server` has an exact-mode completed-turn admission citation. Catalog enumeration, selectability, a handshake, historical provider-level proof, an in-process lane, or a skipped test cannot satisfy the real Dashboard-to-provider path or the refresh/stale/auth/unavailable/admitted/replay/legacy-restart state matrix.

Remediation `W05.P12.S57` must revalidate P03.S19/P03.S20 against the released A2A binary and receipt-matched Dashboard consumer before dependent external-provider and Dashboard claims in `S58-S64`. Independent environment, durability, context, broker, lifecycle, artifact, deterministic, local-load, and capability-matrix work may continue under their own prerequisites.

### Validation retained by the phase

- S01: locked binary build and smoke capture passed; 35 focused admission/component tests passed; correction validation passed 73 provider/in-process tests; all canonical captures and source manifests reproduced; explicit rustup shims later passed 16 product-drain and 21 lifecycle tests.
- S02: 39 focused A2A contract tests passed; Dashboard discovery-focused tests passed 19, lifecycle tests passed 21, and broker tests passed 70 through explicit rustup binaries; deterministic assertions passed the eleven-operation matrix, four added routes and bounds, typed envelopes, producer-first provenance, mutual links, every retry/reconciliation rule, and the corrected D2 marker.
- S03: exact-mode/plan capture digest `94A91AE6A4D9C4BB450BE9D9A35C26B1487248772A0E854196B509BF21877593` and source-manifest digest `2525AAD195A153019183D3898D36C1634E502A6AE4AAEC06FCE7973417FABA47` reproduced. The full focused command produced 90 passes and one audited host-state failure; excluding only that test passed 90 with one deselection. The pass is structural evidence and does not close catalog P03.S19/P03.S20.

### Findings and ownership

| Finding | Severity | Type | Current status | Owner/follow-up |
|---|---|---|---|---|
| `qualification-pair-lock-drift` | high | contract and evidence gap | open | `S47-S50`; proof `S64-S65` |
| `durable-message-capacity-absent` | high | concurrency and durability | open | `S16-S18`; measure `S52` |
| `frozen-binary-collects-test-modules` | medium | packaging and operational risk | open | `S50`; certify `S65` |
| `qualification-capture-provenance` / rereview | high | evidence reproducibility | resolved at `00fa0347` | S01 correction complete |
| `dashboard-pretest-deadlines-incomplete` / rereview | high | contract and evidence completeness | resolved at `00fa0347` | S01 correction complete; S02 reconciled semantics |
| `database-pool-backend-conflation` / rereview | medium | evidence accuracy | resolved at `00fa0347` | S01 correction complete |
| `in-process-mode-posture-unspecified` / rereview | medium | evidence completeness | resolved at `00fa0347` | S01 correction complete |
| `dashboard-rust-toolchain-unlaunchable` / launcher rereview | low | validation environment | open, narrowed; valid rustup route proven | Host PATH/shared shim repair before final qualification |
| `embedded-discovery-wire-contract-drift` | high | contract and integration | open | `S47-S48`, `S50`; proof `S64-S65` |
| `embedded-broker-foreign-substitution` | high | authorization and lifecycle | open | `S43-S45`, `S47-S48`; proof `S64-S65` |
| `embedded-discovery-receipt-compatibility-gap` | high | state compatibility and evidence | open | `S47-S50`; proof `S64-S65` |
| `embedded-component-authority-drift` | medium | architecture and packaging | open | `S47-S50`; qualify `S65` |
| `dashboard-rust-toolchain-s02-validation` | low | validation environment | resolved | S02 used explicit rustup binaries |
| `dashboard-vault-baseline-validation-debt` | low | documentation hygiene | open, unrelated/non-blocking | Dashboard architecture-corpus curation outside this plan |
| `s02-broker-decision-outside-adr` | high | architecture and decision ownership | resolved at Dashboard `02101b52` | S02 correction complete; implementation `S43-S45` |
| `s02-future-broker-wire-underspecified` | high | contract completeness | resolved at Dashboard `02101b52` | S02 correction complete; implementation `S43-S45` |
| `s02-release-provenance-contract-incomplete` | high | architecture and packaging | resolved at Dashboard `02101b52` plus A2A plan correction | Implement `S50`; prove `S65` |
| `s02-formal-review` | high | implementation review | historical fail, superseded by final pass | Corrected by `df8645c7` / Dashboard `02101b52` |
| `s02-existing-verb-retry-contract-regression` | high | contract completeness and regression | resolved at Dashboard `89706fb2` | S02 correction complete |
| `s02-edge-adr-d2-marker` | low | documentation quality | resolved at Dashboard `89706fb2` | S02 correction complete |
| `s02-corrected-formal-rereview` | high | implementation review | historical fail, superseded by final pass | Corrected by `54a871a1` / Dashboard `89706fb2` |
| `s02-final-formal-rereview` | low | implementation review disposition | resolved/pass at `803dca96` | No S02 review blocker remains |
| `provider-selection-positive-proof-absent` | high | integration evidence | open; blocks only dependent qualification | Catalog `P01.S10-S11`, `P03.S19-S20`; revalidate `S57` |
| `provider-capability-plan-state-source-drift` | medium | lifecycle and evidence accuracy | open | Capability plan `P01.S01-P02.S04`; remediation `S35-S36` |
| `provider-catalog-s08-step-record-gap` | low | lifecycle traceability | open/non-blocking | Catalog lifecycle reconciliation `P03.S23` |
| `provider-catalog-route-host-state-leak` | medium | test isolation | open/non-blocking | Catalog validation hardening `P03.S22` |
| `s03-formal-review` | low | implementation review disposition | resolved/pass at `63a58036` | No S03 review blocker remains |

Phase `W01.P01` is complete. The next open step is `W01.P02.S04`, which runs PostgreSQL URL checks under the locked server dependency profile and makes that profile explicit while preserving the SQLite binary profile.
