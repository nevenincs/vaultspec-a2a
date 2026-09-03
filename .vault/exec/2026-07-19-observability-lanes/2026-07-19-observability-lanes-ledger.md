---
tags:
  - '#exec'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:8654a89a93ea238a6373ec345502bf33ab1ea3282a14e621b37adf5a63fb1ef7'
related:
  - "[[2026-07-19-observability-lanes-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `observability-lanes` ledger

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
- `S01` `T` `src/vaultspec_a2a/utils/logging.py`
- `S01` `T` `src/vaultspec_a2a/utils/tests/`
- `S01` `T` `src/vaultspec_a2a/control/config.py`
- `S02` `T` `src/vaultspec_a2a/api/app.py`
- `S02` `T` `src/vaultspec_a2a/worker/app.py`
- `S02` `T` `src/vaultspec_a2a/cli/main.py`
- `S02` `T` `src/vaultspec_a2a/protocols/mcp/authoring_stdio.py`
- `S03` `T` `src/vaultspec_a2a/lifecycle/`
- `S03` `T` `src/vaultspec_a2a/control/worker_management.py`
- `S03` `T` `src/vaultspec_a2a/lifecycle/tests/`
- `S04` `T` `src/vaultspec_a2a/control/dispatch.py`
- `S04` `T` `src/vaultspec_a2a/api/websocket.py`
- `S04` `T` `pyproject.toml`
- `S04` `T` `docs/`
- `S05` `T` `src/vaultspec_a2a/protocols/mcp/__main__.py`
- `S05` `T` `src/vaultspec_a2a/utils/logging.py`
- `S05` `T` `src/vaultspec_a2a/utils/tests/`
- `S06` `T` `websocket: failing client ids at the recovery or periodic summary) so storm dedup keeps per-entity diagnosability`
- `S06` `T` `and scope the websocket recovered message so it cannot claim global recovery while other clients still fail. Live tests asserting ids appear in summaries while gapped occurrences stay unlogged`
- `S06` `T` `src/vaultspec_a2a/control/dispatch.py`
- `S06` `T` `src/vaultspec_a2a/api/websocket.py`
- `S06` `T` `src/vaultspec_a2a/control/tests/`
- `S06` `T` `src/vaultspec_a2a/api/tests/`

