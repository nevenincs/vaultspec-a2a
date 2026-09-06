---
tags:
  - '#adr'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:049c241800c3e306a5f2c81244ddd81c35c589ba24c3398566618e9f1d8d6cc1'
related:
  - '[[2026-09-05-embedded-runtime-remediation-research]]'
  - '[[2026-09-05-embedded-runtime-robustness-audit]]'
  - '[[2026-09-05-embedded-runtime-robustness-research]]'
  - '[[2026-08-02-control-action-leases-adr]]'
  - '[[2026-08-05-served-capability-contract-state-truthfulness-adr]]'
  - '[[2026-08-01-dashboard-bundled-runtime-subordination-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-02-25-llm-context-provider-abstraction-adr]]'
  - '[[2026-08-02-provider-error-taxonomy-adr]]'
  - '[[2026-08-02-provider-capability-evidence-adr]]'
  - '[[2026-08-02-provider-model-catalog-adr]]'
  - '[[2026-09-05-embedded-runtime-remediation-no-legacy-curation-audit]]'
  - '[[2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-research]]'
---
# `embedded-runtime-remediation` adr: `qualification and single-owner remediation of the embedded runtime` | (**status:** `accepted`)

## Problem Statement

The robustness audit establishes a measured baseline, but one qualification decision must bind closure across runtime correctness, consumer integration and evidence gaps. This record decides that closure contract. Existing amended ADRs remain the single homes of runtime semantics. Grounding is `2026-09-05-embedded-runtime-remediation-research`.

## Considerations

- Qualification must identify the intended binary and consuming Dashboard generation.
- Local orchestration, external-provider work and native capability effects establish different facts.
- Existing active plans retain implementation ownership; completed historical plans retain their execution record.
- Evidence, decisions and execution tracking remain in their respective related documents.

## Considered options

- **Adopt the complete audit scenario matrix as the remediation qualification gate - chosen.** Covers the measured boundary failures and preserves reproducibility.
- **Close findings on source regression alone - rejected.** Omits the consumer/provider boundaries the grounding identifies.
- **Replace the component or introduce a second broker/service - rejected.** The evidence supports correction within the existing control, persistence and binary owners.
- **Create a competing implementation plan for every finding - rejected.** Splits already-owned work and permits contradictory closure claims.

## Constraints

The scope is the Dashboard-embedded binary component, not a standalone product. Existing exact-mode provider admission stays fail-closed. Missing credentials, unavailable consumer prerequisites and unsafe fault controls are blocked evidence, never passes. Schema and new control-surface changes require coordinated consumer integration.

Parent decisions define the architecture but their implementations are not presumed stable: the audit's evidence governs that judgement. The provider capability, catalog and served-contract plans contain active dependencies. SDK replacement, broader capabilities and historical packaging apparatus are not prerequisites invented by this campaign.

The owner explicitly auto-approved the remediation ADRs on 2026-09-05. This acceptance and the related in-place amendments use that authorization. The implementation plan is approved and active. Architecture amendments are applied before further recovery implementation.

## Implementation

The remediation plan tracks ER01-ER28 to single implementation owners. It executes uncovered corrections under the amended leases, state-truthfulness, edge, provider/context, taxonomy and Dashboard-subordination decisions. Existing-plan deliverables enter as explicit dependency and verification gates, with precise owning Step identifiers. A completed historical Step is not silently rewritten as unexecuted.

Each implementation pass includes real-behavior verification, formal review, severity/type/status classification, an audit-queue update and an execution record before its Step closes. New findings remain visible even when deferred. The original failures remain historical evidence.

## Qualification

Adopt A01-A34 and their numerical thresholds from `2026-09-05-embedded-runtime-robustness-research` as this campaign's acceptance criteria. This does not retrospectively claim they were previously adopted product SLOs. Queue capacities, run-derived deadlines and host/load identities are recorded before tests; bounds cannot be loosened to convert an observed failure into a pass.

Qualification requires every applicable criterion passed, no unresolved critical/high finding, and exact binary/consumer/provider identities. Required positive behavior cannot qualify by being disabled. A genuinely optional unsupported capability may qualify through truthful refusal only where the criterion permits it. Missing evidence blocks qualification even after code correction.

The evidence report separates source/local, external-provider and actual Dashboard measurements. A finding closes only after its discriminator is removed and its stated boundary is rerun successfully. A completed test process, mock lane, skipped case or helper fixture cannot substitute for required real work.

## Rationale

Scenario qualification prevents a narrow code change from becoming a broader readiness claim. Existing owners preserve architectural consistency and audit history while the rollup supplies one reviewable remediation boundary. The related research supplies the option comparison and current ownership map.

## Consequences

The campaign gains an auditable completion contract and one tracking plan. Cross-repository integration, profile maintenance and real-provider prerequisites remain explicit work. Qualification can remain blocked after implementation when external evidence is unavailable. The approved plan executes this qualification contract and pauses affected implementation whenever formal review exposes an architectural contradiction.

## Amendment (2026-09-05): qualification excludes legacy support

The accepted no-legacy amendment in
`2026-08-02-provider-model-catalog-adr` governs this campaign's provider and
model lifecycle. Remediation must remove retired profile, preset-carried
provider/model, static model-map, compatibility-translation, restart,
redispatch, and product-wire paths. Historical audit and execution records stay
unchanged as evidence of what previously existed; they do not require the
runtime to preserve that behavior.

Qualification now requires a negative discriminator: legacy provider/model
input and durable state receive a bounded typed unsupported/incompatible
outcome before provider construction or dispatch, no legacy fields are served,
and no migration or substitution occurs. A test that successfully restarts,
reads, translates, or redispatches legacy provider/model state is evidence of a
defect, not compatibility success.
## Amendment (2026-09-06): root-cause recovery campaign

The condition registry in `2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-research` is the binding recovery scope. Conditions 1 through 16 are one architectural correction, not independent point fixes: replace fragmented startup, read-time, checkpoint, retry and projection decisions with the single durable recovery authority defined by the amended state-truthfulness and control-action-leases ADRs. The served-capability S56 work becomes verification of that authority's checkpoint-first behavior rather than a separate implementation owner.

Condition 17 has a distinct root and remains a separate architectural correction in `src/vaultspec_a2a/testing`: every verification process has one bounded lifecycle owner responsible for plugin sessions, database engines, transports, subprocesses and machine-global leases. A printed test summary does not qualify without natural process exit.

Formal review evaluates architecture and durable behavior before test color. A passing test that preserves fragmented ownership, polling-dependent progress, invented authority or missing process-exit ownership cannot close a Step. The recovery phase requires one architecture reviewer/executor to follow the condition registry across component boundaries and correct shared owners rather than accumulating branch-specific patches.
