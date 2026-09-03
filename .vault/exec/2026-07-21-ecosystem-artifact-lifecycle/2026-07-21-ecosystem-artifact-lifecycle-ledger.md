---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:aad0241cf2744eda17f6b0a7ae4956f4a4f5a03eceff80f6098b245e402f9f3a'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `ecosystem-artifact-lifecycle` ledger

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
- `S01` `T` `src/vaultspec_a2a/control/tests/test_thread_service_artifact_cleanup.py`
- `S02` `T` `.vault/audit`
- `S03` `T` `src/vaultspec_a2a/lifecycle/discovery.py`
- `S04` `T` `src/vaultspec_a2a/lifecycle/discovery.py`
- `S05` `T` `src/vaultspec_a2a/artifacts/retention.py`
- `S06` `T` `src/vaultspec_a2a/lifecycle/discovery.py`
- `S07` `T` `src/vaultspec_a2a/control/worker_management.py`
- `S08` `T` `src/vaultspec_a2a/artifacts/tests/test_retention.py`
- `S09` `T` `src/vaultspec_a2a/lifecycle/atomic_write.py`
- `S10` `T` `src/vaultspec_a2a/lifecycle/discovery.py`
- `S11` `T` `src/vaultspec_a2a/lifecycle/discovery.py`
- `S12` `T` `src/vaultspec_a2a/lifecycle/registry.py`
- `S13` `T` `src/vaultspec_a2a/lifecycle/tests/test_atomic_write.py`
- `S14` `T` `src/vaultspec_a2a/providers/_acp_config_home.py`
- `S15` `T` `src/vaultspec_a2a/desktop/profile.py`
- `S16` `T` `src/vaultspec_a2a/providers/_acp_config_home.py`
- `S17` `T` `src/vaultspec_a2a/control/db.py`
- `S18` `T` `src/vaultspec_a2a/control/db.py`
- `S19` `T` `src/vaultspec_a2a/control/db.py`
- `S20` `T` `src/vaultspec_a2a/service_tests/harness.py`
- `S21` `T` `src/vaultspec_a2a/service_tests/harness.py`
- `S22` `T` `.gitignore`
- `S23` `T` `src/vaultspec_a2a/lifecycle/discovery.py`
- `S24` `T` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S25` `T` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S25` `T` `src/vaultspec_a2a/providers/_config_home_roots.py`
- `S26` `T` `src/vaultspec_a2a/providers/factory.py`
- `S26` `T` `src/vaultspec_a2a/providers/kimi_catalog.py`
- `S27` `T` `src/vaultspec_a2a/artifacts/retention.py`
- `S27` `T` `src/vaultspec_a2a/providers/_config_home_roots.py`
- `S28` `T` `src/vaultspec_a2a/providers/codex_chat_model.py`
- `S28` `T` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S28` `T` `src/vaultspec_a2a/streaming/aggregator.py`
- `S29` `T` `src/vaultspec_a2a/streaming/aggregator.py`
- `S29` `T` `src/vaultspec_a2a/artifacts/retention.py`
- `S30` `T` `.vault/adr/2026-07-21-ecosystem-artifact-lifecycle-adr.md`
- `S31` `T` `.vault/adr/2026-07-21-ecosystem-artifact-lifecycle-adr.md`
- `S31` `T` `src/vaultspec_a2a/providers/codex_chat_model.py`

