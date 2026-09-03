---
tags:
  - '#exec'
  - '#dev-process-registry'
date: '2026-07-15'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:42438257ebf500cc034f8dc5c351e7a547a6bd9ec8b41962e58957aba8ebdde8'
related:
  - "[[2026-07-15-dev-process-registry-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `dev-process-registry` ledger

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
- `S01` `T` `src/vaultspec_a2a/lifecycle/`
- `S01` `T` `procs.toml`
- `S02` `T` `src/vaultspec_a2a/cli/`
- `S02` `T` `src/vaultspec_a2a/lifecycle/`
- `S03` `T` `repoint the port-asserting MCP tests at the declared bands`
- `S03` `T` `src/vaultspec_a2a/api/app.py`
- `S03` `T` `src/vaultspec_a2a/worker/`
- `S03` `T` `scripts/`
- `S03` `T` `src/vaultspec_a2a/service_tests/`
- `S03` `T` `src/vaultspec_a2a/protocols/mcp/tests/`
- `S04` `T` `src/vaultspec_a2a/lifecycle/tests/`
- `S04` `T` `src/vaultspec_a2a/service_tests/`

