---
tags:
  - '#exec'
  - '#container-release'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:7201f5d51723955a54d46584131b3cfae701ac5a111b3d6c446a3aaa02addf8f'
related:
  - "[[2026-10-04-container-release-plan]]"
---

<!-- Machine-owned, whole file: `vaultspec-core vault exec log` creates it
     on first use and appends every row; never hand-edit it. Add no
     frontmatter fields. Wiki-links belong in `related:` only.

     ONE ledger per plan, the only execution artifact. Each row's first
     column names its Step. -->

# `container-release` ledger

## Changes

<!-- MECHANICAL LOG, append-only, one row per path touched per Step, written
     by `--row`:
       - `S##` `A` `path`   added
       - `S##` `M` `path`   modified
       - `S##` `D` `path`   deleted
       - `S##` `R` `old` -> `new`   renamed
     Paths are repo-relative, in backticks. No prose: the Step row states the
     intent and the commit carries the diff.

     Optional per-Step rows, written by `--verify` and `--by`:
       - `S##` `verify:` `<command>` -> `pass` | `fail`
       - `S##` `by:` `<persona>`

     Rows are appended in Step order and never rewritten. Only rows in this
     section register a Step as covered. `--note` adds a `## Notes` section
     ONLY on exception (data loss, skipped work, a scaffold left in code, a
     persistent failure), one `S##`-prefixed line each; it is otherwise
     omitted. -->

- `S01` `A` `dev/container_release.py`
- `S01` `M` `Justfile`
- `S01` `M` `.github/workflows/test.yml`
- `S01` `M` `dev/tests/test_release_workflow_contract.py`
- `S01` `verify:` `ruff check and format changed Python` -> `pass`
- `S01` `verify:` `ty check changed Python` -> `pass`
- `S01` `verify:` `pytest dev/tests/test_release_workflow_contract.py (6 tests)` -> `pass`
- `S01` `verify:` `python -m dev.ci_contract` -> `pass`
- `S01` `verify:` `python -m dev.container_release --ref e97c7adca6dc02d78162815404eb9f62ac124f55` -> `pass`
