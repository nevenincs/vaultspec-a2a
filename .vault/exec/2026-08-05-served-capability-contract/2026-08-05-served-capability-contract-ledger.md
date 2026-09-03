---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:a6d570cadc971a5ee8d0d90c7d2467a2ef0cc84da1d6b2fcf97ca247ff2f4a78'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `served-capability-contract` ledger

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
- `S01` `T` `src/vaultspec_a2a/providers/_codex_config_home.py`
- `S02` `T` `src/vaultspec_a2a/streaming/ingest.py`
- `S03` `T` `src/vaultspec_a2a/authoring/submitter.py`
- `S04` `T` `src/vaultspec_a2a/control/run_start_policy.py`
- `S07` `T` `docs/a2a-edge-conformance-verb-mapping.md`
- `S08` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S09` `T` `src/vaultspec_a2a/api/app.py`
- `S12` `T` `src/vaultspec_a2a/api/schemas/snapshots.py`
- `S16` `T` `docs/development.rst`
- `S17` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S18` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S19` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S21` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S23` `T` `src/vaultspec_a2a/streaming/transformer.py`
- `S23` `T` `src/vaultspec_a2a/streaming/emitters.py`
- `S23` `T` `src/vaultspec_a2a/control/snapshot.py`
- `S25` `T` `src/vaultspec_a2a/control/run_discovery_service.py`
- `S35` `T` `src/vaultspec_a2a/authoring/session.py`

