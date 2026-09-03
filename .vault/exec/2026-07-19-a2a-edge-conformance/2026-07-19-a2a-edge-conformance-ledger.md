---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-19'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:b07b4cfd141d5c8f42ddd256b2fc1df6c9b35622525c1d29a1c6decbf2977593'
related:
  - "[[2026-07-19-a2a-edge-conformance-plan]]"
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
- `S01` `T` `src/vaultspec_a2a/database/thread_repository.py`
- `S01` `T` `src/vaultspec_a2a/control/run_discovery_service.py`
- `S02` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S02` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S02` `T` `src/vaultspec_a2a/api/tests/test_active_run_discovery_live.py`
- `S02` `T` `src/vaultspec_a2a/control/run_discovery_service.py`
- `S02` `T` `src/vaultspec_a2a/database/thread_repository.py`

