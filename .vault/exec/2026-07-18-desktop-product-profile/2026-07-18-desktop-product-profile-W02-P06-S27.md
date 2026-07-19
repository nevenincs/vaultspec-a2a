---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S27'
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
     The S27 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Expose bounded snapshot inspect and restore commands for the external updater transaction and ## Scope

- `src/vaultspec_a2a/cli/main.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Expose bounded snapshot inspect and restore commands for the external updater transaction

## Scope

- `src/vaultspec_a2a/cli/main.py`

## Description

- Add three internal external-updater CLI commands beside the existing
  `desktop-serve` and `desktop-migrate` verbs, following the same flat
  hyphenated naming and lazy-import convention: `desktop-snapshot-create`,
  `desktop-snapshot-inspect`, and `desktop-snapshot-restore`.
- Take an explicit `--app-home` on every command and a `--group-id` naming the
  consistency-group snapshot; `restore` adds a `--resume/--no-resume` flag that
  rolls forward an interrupted restore.
- Print bounded machine-readable JSON to stdout: `create` and `inspect` emit the
  committed group descriptor; `restore` emits the restored members and whether it
  resumed. Add a shared `_emit_snapshot_failure` helper that prints a bounded
  failure envelope (operation, error class, actionable detail) and exits
  non-zero, so automation reads the exit status without parsing the payload.
- Reuse the snapshot module's real quiesced probe: `restore` requires the
  quiesced condition and refuses a live or locked store fail-closed, and refuses
  an interrupted restore unless `--resume` is given.
- Keep these lifecycle verbs off the run-control HTTP API entirely; they are CLI
  only, mirroring the `desktop-migrate` boundary.
- Add real child-process CLI tests driving the commands against real SQLite
  stores: the create/inspect/restore round trip returns both stores to snapshot
  content, an uncommitted group inspection fails closed, a live store refuses
  restore, missing options are a usage error, and no HTTP route carries a
  snapshot verb.

## Outcome

The desktop CLI exposes bounded snapshot create/inspect/restore for the external
updater transaction with JSON results and honest exit codes. `ruff` and `ty`
pass; the 5 real child-process CLI tests pass.

## Notes

- The commands are flat (`desktop-snapshot-*`) rather than a Click subgroup, to
  match the landed `desktop-serve`/`desktop-migrate` surface rather than rename
  it.
- A concurrent session touched the module docstring of `cli/main.py` (a one-line
  wording change unrelated to this Step) between reads; my additions are isolated
  to a separate region and were committed without that foreign hunk via
  index-level hunk isolation, leaving the other session's uncommitted change in
  the working tree untouched.
