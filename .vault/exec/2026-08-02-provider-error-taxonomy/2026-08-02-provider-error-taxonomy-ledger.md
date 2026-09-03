---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:5c1abc8bc4539d33bfd134080199c014fb5c2349fbbddcfff21cd683c7122b97'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `provider-error-taxonomy` ledger

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
- `S01` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S01` `T` `src/vaultspec_a2a/thread/errors.py`
- `S01` `T` `src/vaultspec_a2a/thread/tests/test_errors.py`
- `S02` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S02` `T` `src/vaultspec_a2a/graph/tests/nodes/test_worker.py`
- `S03` `T` `src/vaultspec_a2a/streaming/ingest.py`
- `S03` `T` `src/vaultspec_a2a/streaming/tests/test_aggregator.py`
- `S04` `T` `src/vaultspec_a2a/streaming/tests/test_aggregator.py`
- `S05` `T` `src/vaultspec_a2a/providers/tests/test_zai_error_fidelity_live.py`
- `S05` `T` `src/vaultspec_a2a/providers/tests/_installed_vocabulary.py`
- `S06` `T` `src/vaultspec_a2a/providers/conditions.py`
- `S06` `T` `src/vaultspec_a2a/providers/__init__.py`
- `S07` `T` `src/vaultspec_a2a/providers/conditions.py`
- `S08` `T` `src/vaultspec_a2a/providers/conditions.py`
- `S09` `T` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S09` `T` `src/vaultspec_a2a/providers/acp_exceptions.py`
- `S10` `T` `src/vaultspec_a2a/providers/codex_chat_model.py`
- `S11` `T` `src/vaultspec_a2a/providers/codex_chat_model.py`
- `S12` `T` `src/vaultspec_a2a/providers/tests/test_conditions.py`
- `S12` `T` `src/vaultspec_a2a/providers/tests/_installed_vocabulary.py`
- `S13` `T` `src/vaultspec_a2a/streaming/ingest.py`
- `S14` `T` `src/vaultspec_a2a/worker/state_projection.py`
- `S15` `T` `src/vaultspec_a2a/database/models.py`
- `S16` `T` `src/vaultspec_a2a/database/migrations/versions`
- `S16` `T` `src/vaultspec_a2a/database/tests/test_migrations.py`
- `S17` `T` `src/vaultspec_a2a/database/thread_repository.py`
- `S18` `T` `src/vaultspec_a2a/database/thread_repository.py`
- `S19` `T` `src/vaultspec_a2a/control/event_handlers.py`
- `S20` `T` `src/vaultspec_a2a/control/thread_state_service.py`
- `S21` `T` `src/vaultspec_a2a/api/schemas/snapshots.py`
- `S22` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S23` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S24` `T` `src/vaultspec_a2a/api/tests/test_internal.py`
- `S25` `T` `src/vaultspec_a2a/streaming/ingest.py`
- `S26` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S27` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S28` `T` `src/vaultspec_a2a/graph/tests/test_compiler.py`
- `S29` `T` `src/vaultspec_a2a/control/repair_transitions.py`
- `S30` `T` `src/vaultspec_a2a/control/thread_service.py`
- `S31` `T` `src/vaultspec_a2a/control/message_service.py`
- `S32` `T` `src/vaultspec_a2a/control/permission_service.py`
- `S33` `T` `src/vaultspec_a2a/control/clarification_service.py`
- `S34` `T` `src/vaultspec_a2a/worker/executor.py`
- `S35` `T` `src/vaultspec_a2a/worker/executor.py`
- `S36` `T` `src/vaultspec_a2a/worker/executor.py`
- `S36` `T` `src/vaultspec_a2a/worker/tests/test_executor.py`
- `S37` `T` `src/vaultspec_a2a/worker/executor.py`
- `S38` `T` `src/vaultspec_a2a/api/thread_stream.py`
- `S39` `T` `src/vaultspec_a2a/streaming/fanout.py`
- `S40` `T` `src/vaultspec_a2a/api/tests/test_internal.py`
- `S41` `T` `src/vaultspec_a2a/thread/errors.py`
- `S42` `T` `src/vaultspec_a2a/thread/__init__.py`
- `S43` `T` `src/vaultspec_a2a/service_tests/test_claude_web_grounding_live.py`
- `S44` `T` `src/vaultspec_a2a/team/presets/teams`
- `S45` `T` `src/vaultspec_a2a/service_tests/test_provider_condition_live.py`
- `S46` `T` `engine/crates/vaultspec-api/src/authoring/session/types.rs`
- `S47` `T` `engine/crates/vaultspec-api/src/authoring/session/validate.rs`
- `S48` `T` `engine/crates/vaultspec-api/src/authoring/session/mod.rs`
- `S49` `T` `engine/crates/vaultspec-api/src/routes/ops/a2a.rs`
- `S50` `T` `engine/crates/vaultspec-api/src/authoring/session/tests.rs`
- `S51` `T` `frontend/src/stores/server/agent/a2aTeam.ts`
- `S52` `T` `frontend/src/stores/server/liveAdapters/a2aRelay.ts`
- `S53` `T` `frontend/src/stores/view/agentPanel.ts`
- `S54` `T` `frontend/src/localization/catalogAgentKeys.ts`
- `S55` `T` `frontend/src/app/agent/AgentPanel.tsx`
- `S56` `T` `frontend/src/app/agent/AgentPanel.render.test.tsx`
- `S57` `T` `frontend/src/stores/server/agent/a2aTeam.live.test.ts`
- `S58` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S58` `T` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S58` `T` `src/vaultspec_a2a/api/schemas/snapshots.py`
- `S58` `T` `src/vaultspec_a2a/thread/snapshots.py`
- `S58` `T` `src/vaultspec_a2a/control/thread_state_service.py`
- `S58` `T` `src/vaultspec_a2a/api/tests/test_internal.py`
- `S59` `T` `src/vaultspec_a2a/worker/executor.py`
- `S60` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S60` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S60` `T` `src/vaultspec_a2a/thread/errors.py`
- `S60` `T` `src/vaultspec_a2a/graph/tests/test_compiler.py`
- `S61` `T` `src/vaultspec_a2a/providers/codex_chat_model.py`
- `S62` `T` `src/vaultspec_a2a/api/tests/test_engine_edge_bounds_agreement.py`
- `S63` `T` `engine/crates/vaultspec-api/src/routes/ops/a2a.rs`

