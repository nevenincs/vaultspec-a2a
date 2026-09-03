---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:acf3e0166e07ebb95a3e2b7a344e406cef4dfd465f8f01d584fd1e5b7abd719d'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `control-action-leases` ledger

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
- `S01` `T` `src/vaultspec_a2a/database/models.py`
- `S01` `T` `src/vaultspec_a2a/database/migrations/versions/0012_control_action_leases.py`
- `S02` `T` `src/vaultspec_a2a/database/permission_repository.py`
- `S02` `T` `src/vaultspec_a2a/database/__init__.py`
- `S03` `T` `src/vaultspec_a2a/database/tests`
- `S04` `T` `src/vaultspec_a2a/worker/app.py`
- `S04` `T` `src/vaultspec_a2a/worker/dispatch_ids.py`
- `S05` `T` `src/vaultspec_a2a/worker/tests`
- `S06` `T` `src/vaultspec_a2a/thread`
- `S06` `T` `src/vaultspec_a2a/graph/nodes/clarification.py`
- `S07` `T` `src/vaultspec_a2a/control/clarification_service.py`
- `S08` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S08` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S09` `T` `src/vaultspec_a2a/lifecycle/reconciliation.py`
- `S09` `T` `src/vaultspec_a2a/database/reconciliation.py`
- `S10` `T` `src/vaultspec_a2a/control/permission_service.py`
- `S11` `T` `src/vaultspec_a2a/control/event_handlers.py`
- `S12` `T` `src/vaultspec_a2a/control/message_service.py`
- `S13` `T` `src/vaultspec_a2a/control/cancel_service.py`
- `S14` `T` `src/vaultspec_a2a/control/verdict_subscriber.py`
- `S15` `T` `src/vaultspec_a2a/control/tests/test_verdict_subscriber.py`
- `S16` `T` `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`
- `S17` `T` `src/vaultspec_a2a/api/tests`
- `S17` `T` `src/vaultspec_a2a/lifecycle/tests`
- `S18` `T` `src/vaultspec_a2a/control/tests`
- `S18` `T` `src/vaultspec_a2a/api/tests`
- `S19` `T` `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`
- `S20` `T` `src/vaultspec_a2a/service_tests/test_clarification_loop_stitched.py`
- `S20` `T` `config/model_profiles.toml`
- `S21` `T` `src/vaultspec_a2a/service_tests`
- `S21` `T` `src/vaultspec_a2a`
- `S22` `T` `.vault/audit`

