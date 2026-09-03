---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:ea800358f0e28f8b3ae2e2ef778073f30ca339168176ce08a3d5c87f0974abf5'
related:
  - "[[2026-07-15-a2a-edge-conformance-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `a2a-edge-conformance` ledger

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
- `S01` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S01` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S01` `T` `src/vaultspec_a2a/control/thread_service.py`
- `S02` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S02` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S02` `T` `src/vaultspec_a2a/team/team_config.py`
- `S03` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S03` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S03` `T` `src/vaultspec_a2a/control/health.py`
- `S04` `T` `src/vaultspec_a2a/control/thread_state_service.py`
- `S04` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S04` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S05` `T` `src/vaultspec_a2a/streaming/`
- `S05` `T` `src/vaultspec_a2a/api/tests/`
- `S06` `T` `src/vaultspec_a2a/service_tests/`
- `S06` `T` `src/vaultspec_a2a/api/tests/`
- `S06` `T` `docs/`

