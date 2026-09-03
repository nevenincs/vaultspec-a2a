---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:20421c716be7f92c673ce388c12d5cad1d90f810ef216e9af62e69f847dd2902'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `adr-authoring-orchestration` ledger

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
- `S01` `T` `src/vaultspec_a2a/graph/nodes/vault_reader.py`
- `S01` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S02` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S02` `T` `src/vaultspec_a2a/graph/tools/task_queue.py`
- `S03` `T` `src/vaultspec_a2a/thread/state.py`
- `S04` `T` `src/vaultspec_a2a/graph/nodes/`
- `S04` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S05` `T` `src/vaultspec_a2a/graph/nodes/`
- `S05` `T` `src/vaultspec_a2a/authoring/`
- `S06` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S06` `T` `src/vaultspec_a2a/team/team_config.py`
- `S07` `T` `src/vaultspec_a2a/control/`
- `S07` `T` `src/vaultspec_a2a/authoring/`
- `S07` `T` `src/vaultspec_a2a/database/`
- `S08` `T` `src/vaultspec_a2a/service_tests/`
- `S08` `T` `src/vaultspec_a2a/control/tests/`
- `S09` `T` `src/vaultspec_a2a/team/presets/agents/`
- `S09` `T` `src/vaultspec_a2a/team/presets/teams/`
- `S10` `T` `src/vaultspec_a2a/service_tests/`
- `S11` `T` `src/vaultspec_a2a/authoring/submitter.py`
- `S12` `T` `src/vaultspec_a2a/authoring/tests/`
- `S13` `T` `src/vaultspec_a2a/worker/graph_lifecycle.py`
- `S13` `T` `src/vaultspec_a2a/authoring/`
- `S14` `T` `src/vaultspec_a2a/worker/graph_lifecycle.py`
- `S14` `T` `src/vaultspec_a2a/authoring/`
- `S14` `T` `.vault/exec/2026-07-14-a2a-edge-conformance/`
- `S15` `T` `src/vaultspec_a2a/thread/state.py`
- `S15` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S15` `T` `src/vaultspec_a2a/worker/tests/`
- `S16` `T` `re-run live lane to a zero-error vault check`
- `S16` `T` `src/vaultspec_a2a/authoring/submitter.py`

