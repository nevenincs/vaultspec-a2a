---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S02'
related:
  - "[[2026-07-15-a2a-edge-conformance-plan]]"
---

# Make presets-list truthful: loadable/unloadable status with unavailable_reason, resilience to any single preset load or validation failure, required roles and authoring capability, mock/test marking, and workspace-context-aware resolution

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/api/schemas/gateway.py`
- `src/vaultspec_a2a/team/team_config.py`

## Description

- Extended preset discovery to be workspace-aware: it now returns the union of
  the requested workspace's local team TOML stems and the bundled set, so a
  workspace-local preset is listed rather than silently dropped.
- Added a mock/test preset marker (the mock- id convention) and a topology to
  authoring-capability mapping (document_authoring for research_adr, coding for
  the coder topologies) as team-config helpers.
- Reshaped the v1 preset summary schema to carry the truth the Rust backend
  needs: a loadable flag, an unavailable_reason, required roles, authoring
  capability, and the mock marker, with descriptive fields optional so an
  unloadable preset is still listed.
- Rewrote the presets-list endpoint to resolve with the requested workspace
  context and to summarize each preset through a helper that catches any load or
  validation failure, reporting the preset as unloadable with a reason rather
  than omitting it or letting one bad TOML crash the whole listing.
- Added unit tests for workspace-aware discovery, the mock marker, and the
  capability mapping, and a live-socket test that lists a workspace containing a
  malformed preset and asserts it is reported unloadable while the bundled and
  document-authoring presets load with their roles and capability.

## Outcome

- presets-list is now truthful and resilient: one invalid preset no longer
  crashes the listing, workspace-local presets resolve, and each entry states
  whether it is actually runnable plus its roles, capability, and mock status.
- Scoped suites green: team (preset discovery unit) and api (gateway live
  truthful-listing), plus the internal and MCP preset listings unaffected (116);
  `ruff check`, `ruff format`, and `ty check` clean.

## Notes

- The listing catches a broad exception per preset deliberately: the handover
  requires that an arbitrarily malformed preset never crash the listing, so the
  per-preset summary fails closed to unloadable with a bounded reason. The
  project's ruff profile does not select the blind-except rule, so no lint skip
  was needed.
- Required roles are the worker agent ids, matching the token-bundle key space
  the run-start eligibility check validates against.
