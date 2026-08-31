---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:c570756e670c6f94a2805f5604a831208b93cfc03f595ad6efdd81c0452d4815'
step_id: 'S10'
related:
  - "[[2026-08-02-provider-model-catalog-adr]]"
  - "[[2026-08-02-provider-model-catalog-plan]]"
---

# Remove product provider-model policy and retire static external model authority

## Scope

- `src/vaultspec_a2a/team/presets/`
- `src/vaultspec_a2a/graph/enums.py`
- `src/vaultspec_a2a/graph/compiler.py`
- `src/vaultspec_a2a/providers/factory.py`
- `src/vaultspec_a2a/providers/model_profiles.py`
- `src/vaultspec_a2a/api/`

## Description

- Remove provider, capability, fallback, and profile policy from bundled product
  agent and team TOMLs while retaining topology, personas, roles, and tools.
- Remove external providers from repository model maps and implicit defaults.
- Require modern external execution to consume exact frozen catalog values;
  retain deterministic and mock mappings as internal test/runtime fixtures.
- Stop serving legacy profiles and default profile IDs from preset discovery.
- Retain only provider readiness and a narrow parser for pre-catalog persisted
  `model_profile` records.
- Preserve explicit operator selection for billable service proofs and validate
  its opaque entry against prompt-free live catalog discovery.

## Outcome

Bundled product presets no longer choose an external provider or model tier.
External factory and compiler paths refuse implicit defaults and repository
model enums, accepting only exact values frozen from a served catalog. Preset
discovery exposes product topology and authoring capabilities without profile
assignments. Legacy custom team/profile TOMLs remain parseable, but their policy
is not served or resolved for new runs.

Focused verification passed 216 tests plus 1 intentional service deselection
across provider, factory, enum, gateway discovery, and team configuration
boundaries. A further 25-test ACP/Codex boundary is included in that total.
Ruff passes across all touched S10 source and test files.

## Notes

The shared virtual environment lacked the requested test and static tools.
Tests therefore ran through ephemeral `uv run --no-sync --with ...` overlays.
An isolated locked project command timed out without collection, and direct
`uvx basedpyright` lacked the repository stub environment; both are recorded as
non-runs rather than evidence. Discovery-heavy replay/race selectors also timed
out while refreshing unrelated live provider catalogs and remain for P01.S11's
bounded assembled proof.

The deleted profile evidence suite created new runs through the now-forbidden
`profile_id` field. A replacement durable pre-migration restart/redispatch proof
is required in the distinct P03.S20 integration-owned service boundary; the
narrow parser unit test is not sufficient by itself.
