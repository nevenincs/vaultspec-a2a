---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:a4347ce5854c0d951a085cbf0e780b935c235e1f294ff55eca751f38b9354cec'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `resource-aware-test-execution` ledger

## Changes

<!-- MECHANICAL LOG, append-only, one line per path touched per Step:
       - `S##` `A` `path`   added
       - `S##` `M` `path`   modified
       - `S##` `D` `path`   deleted
       - `S##` `R` `old` -> `new`   renamed
     Paths are repo-relative, in backticks. No prose, no sentences: the Step
     row states the intent and the commit carries the diff. Example:

       - `S01` `M` `src/vaultspec_core/cli/exec_cmd.py`
       - `S01` `A` `src/vaultspec_core/cli/tests/test_exec_cmd.py`
       - `S02` `D` `src/legacy/shim.py`

     Optional per-Step check line:
       - `S01` `verify:` `<command>` -> `pass` | `fail`

     Rows are appended in Step order and never rewritten. Only rows in this
     section register a Step as covered; a `## Notes` section is added ONLY on
     exception (data loss, skipped work, a scaffold left in code, a persistent
     failure) and is otherwise omitted. -->
- `S01` `T` `pyproject.toml`
- `S02` `T` `src/vaultspec_a2a/testing/resources.py`
- `S03` `T` `src/vaultspec_a2a/testing/leases.py`
- `S04` `T` `src/vaultspec_a2a/testing/progress.py`
- `S05` `T` `src/vaultspec_a2a/testing/endpoints.py`
- `S06` `T` `src/vaultspec_a2a/testing/plugin.py`
- `S07` `T` `src/vaultspec_a2a/conftest.py`
- `S08` `T` `src/vaultspec_a2a/service_tests/test_pw7_acceptance.py`
- `S09` `T` `src/vaultspec_a2a/testing/tests/`
- `S10` `T` `pyproject.toml`
- `S11` `T` `src/vaultspec_a2a/control/config.py`
- `S12` `T` `src/vaultspec_a2a/testing/ports.py`
- `S13` `T` `src/vaultspec_a2a`
- `S14` `T` `src/vaultspec_a2a/tests/gateway_boot.py`
- `S15` `T` `src/vaultspec_a2a/testing/sessions.py`
- `S16` `T` `src/vaultspec_a2a/testing/tests/`
- `S17` `T` `pyproject.toml`
- `S18` `T` `src/vaultspec_a2a/tests/gateway_boot.py`
- `S19` `T` `src/vaultspec_a2a/testing/`
- `S20` `T` `src/vaultspec_a2a/testing/tests/`
- `S21` `T` `dev/toolchain.py`

