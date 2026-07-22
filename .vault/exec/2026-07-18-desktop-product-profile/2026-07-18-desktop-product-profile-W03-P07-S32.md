---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S32'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Parse the versioned secret-free gateway discovery record without weakening engine authoring discovery

## Scope

- `src/vaultspec_a2a/authoring/discovery.py`

## Description

- Add `parse_discovery_record` and a shape-agnostic `DiscoveryRecordView` to the
  shared reader in `authoring/discovery.py`, recognising both the legacy R8
  record and the versioned secret-free desktop record and preferring the
  versioned shape when its version and profile are present.
- Expose `read_discovery_record` for a dashboard-facing consumer to read and
  parse either shape from disk into one view.
- Route `resolve_engine` through the parser: a legacy record resolves exactly as
  before, and a versioned record is parsed rather than misread as malformed but
  is skipped for engine resolution because it carries no inline machine bearer.
- Keep the versioned shape's identity constants local to this lower reader module
  rather than importing `lifecycle.discovery`, which would create an import cycle.
- Add real tests: versioned and legacy parsing, fail-closed on a missing port,
  disk round-trip of both shapes, an unchanged live legacy engine resolution, and
  proof a live versioned record is never resolved into an engine endpoint.

## Outcome

The reader parses both shapes with no behavior change for engine flows. Gates:
`ruff` and `ty` clean; `pytest src/vaultspec_a2a/authoring -q` 109 passed
(all pre-existing engine tests unchanged); `pytest src/vaultspec_a2a/lifecycle -q`
117 passed.

## Notes

The desktop baseline shows three unrelated failures in the manifest, contract,
and component-contract schema golden-vector tests. They originate in a concurrent
`W02.P06.S26` manifest/schema campaign whose `desktop/contract.py`,
`desktop/manifest.py`, and new `database/checkpoint_schema.py` are dirty in the
shared working tree; none touch discovery, singleton, or authoring, and none are
included in this Step's commit. This Step's own surface (lifecycle and authoring
suites) is fully green.
