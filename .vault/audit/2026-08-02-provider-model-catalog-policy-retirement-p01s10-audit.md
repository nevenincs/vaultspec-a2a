---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
related:
  - "[[2026-08-02-provider-model-catalog-adr]]"
  - "[[2026-08-02-provider-model-catalog-plan]]"
  - "[[2026-08-02-provider-model-catalog-reference]]"
---

# `provider-model-catalog` audit: `P01.S10 policy retirement review`

## Scope

Review of product preset policy removal, static external model-map retirement,
modern exact-frozen compiler/factory authority, served preset DTO contraction,
legacy persisted-profile compatibility, and explicit live-selector gating.

## Findings

### durable-legacy-restart-evidence-displaced | high | Queued

The retired evidence suite started a new run using `profile_id`, which is
correctly forbidden by the catalog request schema, so that suite could not be
retained. Its deletion also displaced the only full second-gateway persistence
proof. P03.S20 must seed a real pre-migration `model_profile` record directly,
boot a second gateway and redispatch lifecycle on the same durable stores, and
prove exact legacy values are reused without serving or accepting profile policy
for a new run. The retained parser unit test does not close this finding.

### discovery-heavy-replay-proof-unbounded | medium | Queued

Two modernized gateway replay/race regressions request the full live provider
catalog and can exhaust their client budget while unrelated providers refresh.
P01.S11 should run the existing S09 modern race proof through a bounded
production registration or otherwise isolate the explicit lane without fakes,
then retain the exact replay/conflict assertions. Current attempts are non-runs,
not implementation failures.

### direct-static-gate-environment-invalid | low | Queued

The shared environment did not contain pytest, Ruff, or BasedPyright. Ephemeral
test and Ruff overlays worked, but a direct `uvx basedpyright` invocation missed
the repository's configured stubs/execution environment and emitted broad
unknown-type diagnostics in untouched graph internals. P01.S11 must run the
repository strict gate from a valid locked environment before campaign closure.

## Verification

- Provider legacy-reader and lane-admission tests: 8 passed.
- Provider factory and internal model-map tests: 63 passed.
- ACP model selection and Codex chat-model tests: 25 passed, 1 service test
  deselected.
- Served preset discovery tests: 3 passed.
- Team configuration and legacy schema tests: 117 passed.
- Focused Ruff boundary: all checks passed.
- Full gateway, isolated locked pytest, service collect-only, direct
  BasedPyright, and discovery-heavy replay/race attempts are explicitly
  non-runs or invalid proof boundaries as described above.

## Recommendations

- Close the durable legacy restart finding in P03.S20 before removing the final
  persisted-profile reader.
- Use P01.S11 for the bounded assembled gateway race and valid strict-type gate.
- Do not reintroduce product profiles, external model constants, or catalog-order
  selection to make legacy tests pass.
