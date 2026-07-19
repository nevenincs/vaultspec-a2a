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

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S32 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Parse the versioned secret-free gateway discovery record without weakening engine authoring discovery and ## Scope

- `src/vaultspec_a2a/authoring/discovery.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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
