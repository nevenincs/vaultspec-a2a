---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# `desktop-product-profile` `W01.P02` summary

Phase P02 put every capsule-owned runtime asset behind a package or capsule
authority and fixed the exact deliverable shape the dashboard binds. All seven
Steps (S06 through S12) are closed. The wheel is deliberately shaped (test
trees, certification packages, and mock presets excluded; migrations, presets,
and the manifest schema included), Alembic and presets resolve from installed
package resources, the ACP adapter resolves from capsule-owned assets when the
capsule seam is armed, and a versioned component-manifest contract with a
deterministic emitter and a real dashboard release-manifest binding gate
defines the tandem shipping boundary.

- Modified: `pyproject.toml`, `src/vaultspec_a2a/database/migrate.py`,
  `src/vaultspec_a2a/team/team_config.py`, `src/vaultspec_a2a/providers/factory.py`,
  `src/vaultspec_a2a/control/config.py`
- Created: `src/vaultspec_a2a/desktop` (contract, manifest emitter, facade,
  tests), `schemas/desktop-capsule-manifest.json`,
  `src/vaultspec_a2a/desktop_tests/test_component_contract.py`,
  `src/vaultspec_a2a/desktop_tests/fixtures/dashboard-release-manifest.json`,
  `src/vaultspec_a2a/providers/tests/test_capsule_acp_resolution.py`

## Description

S06 shaped the Hatch wheel: an explicit denylist drops every in-package test
tree, the certification packages, root conftest, and mock and deterministic
presets, while migrations, production presets, the authoring rule corpus, and
the manifest schema ride in as package data. S07 replaced the repo-root
Alembic configuration read with a programmatic config whose script location
resolves from installed package resources; a clean installed wheel migrates a
fresh store to head with no checkout file consulted. S08 moved agent and team
preset roots to package-owned resource paths with unchanged discovery
semantics. S09 added the capsule-assets seam: when armed, the Claude ACP
adapter and Node runtime resolve only from capsule-owned assets with no
checkout or PATH fallback and fail loud naming the missing asset; unarmed
behavior is unchanged, and profile binding is deferred to the desktop profile
Step.

S10 defined the versioned component-manifest contract as a typed authority
with an exported schema snapshot: component identity, the five accepted target
triples, directional contract compatibility, protocol and migration ranges,
typed gateway and standalone MCP entrypoints, per-asset digests, the exact
four-asset base closure with pinned CPython, Node, and ACP versions, license
identifiers, and dependency-lock identity. S11 implemented the deterministic
emitter, later hardened to wheel-authoritative identity with canonical
manifest bytes and a cross-language golden vector. S12 certifies the boundary
from real artifacts: the clean wheel ships assets and no tests, the committed
schema snapshot equals the authority export, and the emitted manifest binds an
A2A-owned dashboard release-manifest fixture by pinned identity and canonical
digest. The standalone console script was renamed during the phase to avoid a
PATH collision, and the contract surface absorbed two concurrent hardening
waves that were reconciled before closure.

## Tests

Full desktop surface green at closure: 147 passed across the desktop package
tests and the desktop certification gates, plus 140 passed across the
providers, database migration, and team suites exercised by the asset steps.
All gates build real wheels and exercise real files, subprocesses, and
installed environments; no fakes, mocks, stubs, patches, monkeypatches, skips,
or expected failures. Independent code review passed S06 through S09 after one
high finding (a certification package leaking into the wheel) was fixed and
re-verified from a clean commit archive, and passed S10 and S11 with the S12
gate confirmed repaired and green at head. Ruff, formatting, and scoped ty
checks pass on all touched paths.
