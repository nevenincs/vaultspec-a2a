---
tags:
  - '#exec'
  - '#agent-harness-provisioning'
date: '2026-07-15'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:ee415445e4c89d882430675eb4bb0935fa02bd01fc58b8bc7af3f20dcf0aa47a'
related:
  - "[[2026-07-15-agent-harness-provisioning-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `agent-harness-provisioning` ledger

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
- `S01` `T` `src/vaultspec_a2a/context/`
- `S01` `T` `src/vaultspec_a2a/providers/model_profiles.py`
- `S01` `T` `src/vaultspec_a2a/control/`
- `S02` `T` `src/vaultspec_a2a/team/team_config.py`
- `S02` `T` `src/vaultspec_a2a/context/rules.py`
- `S03` `T` `src/vaultspec_a2a/cli/`
- `S03` `T` `src/vaultspec_a2a/service_tests/`
- `S04` `T` `src/vaultspec_a2a/service_tests/`
- `S04` `T` `src/vaultspec_a2a/api/tests/`

