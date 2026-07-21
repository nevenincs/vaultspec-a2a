---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S114'
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
     The S114 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Drop the Intel macOS target from the shipped capsule matrix across the contract enum published manifest schema declared inputs and certification workflow and regenerate the schema snapshot and golden vector and ## Scope

- `src/vaultspec_a2a/desktop/contract.py`
- `schemas/desktop-capsule-manifest.json`
- `scripts/desktop_capsule_inputs.toml`
- `.github/workflows/desktop-capsule.yml` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Drop the Intel macOS target from the shipped capsule matrix across the contract enum published manifest schema declared inputs and certification workflow and regenerate the schema snapshot and golden vector

## Scope

- `src/vaultspec_a2a/desktop/contract.py`
- `schemas/desktop-capsule-manifest.json`
- `scripts/desktop_capsule_inputs.toml`
- `.github/workflows/desktop-capsule.yml`

## Description

- Remove the `MACOS_X86_64` member from the `TargetTriple` enum; document in the class
  docstring that `cryptography` publishes no `x86_64-apple-darwin` wheel and enters the
  closure through a required `mcp -> pyjwt[crypto]` edge that cannot be pruned.
- Remove the corresponding dict entries keyed by the removed member in
  `artifacts.py` (`_TARGET_SDK`-equivalent SDK package map) and `lock_reconciliation.py`
  (`_TARGET_SDK`, `_TARGET_ENVIRONMENT`, `_TARGET_NPM`); enumeration-only edit, no
  control-flow change.
- Remove the two `[targets.x86_64-apple-darwin.*]` sections from
  `scripts/desktop_capsule_inputs.toml`; the builder CLI derives its target choices
  dynamically from `TargetTriple`, so no other change was needed there.
- Remove the `x86_64-apple-darwin` / `macos-15-intel` matrix row from
  `.github/workflows/desktop-capsule.yml`.
- Regenerate `schemas/desktop-capsule-manifest.json` by writing
  `export_component_manifest_schema()`'s output directly (the single authority the
  committed snapshot mirrors); the diff is limited to the docstring and the enum list.
- Update every test that enumerated the five-target matrix: the mirrored SDK-package
  dict in the materializer test fixtures, both wheel-compatibility parametrizations in
  the package-archive tests, and every target-keyed dict in the lock-reconciliation
  tests (`_TARGET_SDK_SUFFIX`, `_COMMITTED_PYTHON_CLOSURE`, `_KNOWN_WHEEL_GAP`,
  `_PYTHON_TARGET`, `_NPM_TARGET`, and the per-target foreign-platform-tag map). The
  parametrized `tuple(TargetTriple)` tests self-correct once the enum shrinks; only the
  literal per-target dicts needed hand edits.
- Rename the exactly-five-targets contract test to exactly-four and drop the removed
  triple from its expected set.

## Outcome

- Enum member removed outright (not retained-but-unshipped): every use site keys
  target-specific data by the enum's own members, so there is no independent
  general-purpose platform vocabulary that outlives the shipped matrix here; the triple
  string itself remains directly recoverable from history if ever needed again.
- The manifest golden vector (`component-manifest-canonical-v1.b64`/`.sha256` in the
  desktop test fixtures) was inspected and left untouched: its embedded manifest
  instance declares `target: x86_64-unknown-linux-gnu`, which the enum change does not
  affect, so no regeneration of that pair was required.
- `ruff format --check`, `ruff check src/vaultspec_a2a/desktop/ scripts/`, and
  `ty check` (default and `--python-platform linux`) all pass clean on every touched
  file.
- `pytest src/vaultspec_a2a/desktop -q`: 474 passed, 3 deselected (baseline was ~442;
  the net increase reflects unrelated concurrent work landing in the shared tree during
  this Step, not a scope change here).
- The published schema was independently checked well-formed against
  `jsonschema.Draft202012Validator.check_schema`, and
  `test_committed_schema_snapshot_exactly_matches_production_exporter` plus the golden
  vector test were re-run standalone and pass.
- Consumer impact for the dashboard: the shipped target matrix in the published
  component-manifest schema's `TargetTriple` enum drops from five members to four;
  `x86_64-apple-darwin` is no longer a value a manifest's `target` field can declare.
  Any dashboard-side code branching on that literal value needs the same removal.

## Notes

- `src/vaultspec_a2a/desktop/wheel_compatibility.py` has one now-unreachable branch: with
  `MACOS_X86_64` gone, the trailing `return arch in {"x86_64", "universal2"}` fallback in
  `_tag_supports_target` can only ever be reached with `target is TargetTriple.MACOS_ARM64`
  (every other target returns earlier in the function), so it is effectively dead code
  rather than a defect. Left unchanged to keep this Step's blast radius to the target
  enumeration; flagged here as a low-severity follow-up for whoever next touches that
  function.
- No consumer-facing documentation (`docs/`, `README.md`) named the five/four-target
  list, so nothing there required updating.
