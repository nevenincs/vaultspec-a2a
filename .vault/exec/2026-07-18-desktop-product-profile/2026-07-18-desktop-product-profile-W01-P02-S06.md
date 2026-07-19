---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S06'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Declare migrations presets and desktop runtime metadata as explicit wheel package data

## Scope

- `pyproject.toml`

## Description

- Add an `exclude` list to the Hatch wheel target that drops every rust-style
  per-module `tests` tree and the `desktop_tests` certification package.
- Document, in the same target, that migrations, team presets, and the context
  authoring rule corpus ride in as Hatch default-included package data.
- Rebuild the clean wheel and inspect the archive listing to confirm the shape.

## Outcome

The production wheel is now deliberately shaped. A clean `uv build --wheel
--no-sources` produced a 269-entry archive, down from 452, with zero entries
under any `tests` directory or the `desktop_tests` package. The capsule-owned
runtime assets are all present: 11 migration entries (the package `__init__`,
`env`, the `script.py.mako` template, the versions package, and the seven
revision scripts), 39 preset entries, and the 23 bundled `mock-` preset TOMLs
that the discovery surface globs.

The `mock-` preset TOMLs were kept included rather than excluded. The versioned
run-control presets route and the internal presets listing both call
`discover_team_preset_ids`, which globs every `*.toml` under the bundled preset
directory, and the API layer then classifies each id through `is_mock_preset`.
Excluding the mock presets from the wheel would therefore change the installed
discovery contract and break the bundled preset-discovery behavior, so they
remain package data and are filtered at request time, not at packaging time. The
`mock` replay tapes are served by the VidaiMock HTTP container, not resolved by
installed Python; they live under the preset tree and were left in place rather
than special-cased, since the plan's exclusion target is packaged tests only.

Allowlist-style inclusion was deliberately avoided: Hatch default-includes all
tracked files under the package, so an `include` allowlist would have risked
silently dropping production modules. An `exclude` denylist scoped to the test
trees achieves the required shape without that hazard.

## Tests

- `uv build --wheel --out-dir <tmp> --no-sources` succeeded; archive inspection
  reported 269 total entries, 0 test entries, 39 preset entries, 11 migration
  entries, the Mako template present, and 23 mock preset TOMLs retained.
- `uv run --no-sync pytest src/vaultspec_a2a/desktop_tests -q` reported 5 passed.
  The S05 dependency-closure gate builds its own wheel, installs the base
  closure, and imports production gateway and worker telemetry from the clean
  environment; it stays green because it runs from the source tree and never
  imports a packaged test module.

## Notes

The pytest `testpaths` point at the source checkout, so excluding the test trees
from the wheel cannot weaken any source-run gate. No production module, preset,
or migration asset was removed. No mock, stub, patch, or skip was introduced.
