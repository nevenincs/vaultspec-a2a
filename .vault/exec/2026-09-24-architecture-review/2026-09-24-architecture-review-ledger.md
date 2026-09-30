---
tags:
  - '#exec'
  - '#architecture-review'
date: '2026-09-24'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:d2a5996b35ed006486822513430d998f897bb64c00db9556820e797b5c6f5959'
related:
  - "[[2026-09-24-architecture-review-plan]]"
---


# `architecture-review` ledger

## Changes

- `S01` `M` `pyproject.toml`
- `S01` `M` `uv.lock`
- `S01` `verify:` `pytest src/vaultspec_a2a/graph src/vaultspec_a2a/streaming src/vaultspec_a2a/thread` -> `pass`
- `S01` `by:` `orchestrator`
- `S02` `M` `src/vaultspec_a2a/graph/compiler.py`
- `S02` `M` `src/vaultspec_a2a/graph/_compiler_research.py`
- `S02` `M` `src/vaultspec_a2a/graph/tests/test_research_adr_clarification.py`
- `S02` `verify:` `pytest src/vaultspec_a2a/graph` -> `pass`
- `S02` `by:` `orchestrator`
- `S03` `M` `src/vaultspec_a2a/graph/compiler.py`
- `S03` `M` `src/vaultspec_a2a/graph/_compiler_retry.py`
- `S03` `M` `src/vaultspec_a2a/graph/nodes/action_completion.py`
- `S03` `M` `src/vaultspec_a2a/streaming/ingest.py`
- `S03` `A` `src/vaultspec_a2a/streaming/tests/test_ingest_node_timeout.py`
- `S03` `M` `src/vaultspec_a2a/graph/tests/test_compiler.py`
- `S03` `M` `src/vaultspec_a2a/graph/tests/nodes/test_action_completion.py`
- `S03` `M` `src/vaultspec_a2a/worker/tests/test_frozen_graph_authority.py`
- `S03` `verify:` `pytest src/vaultspec_a2a/streaming src/vaultspec_a2a/graph src/vaultspec_a2a/worker` -> `pass`
- `S03` `by:` `orchestrator`
- `S04` `M` `src/vaultspec_a2a/graph/nodes/vault_reader.py`
- `S04` `M` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S04` `M` `src/vaultspec_a2a/graph/compiler.py`
- `S04` `M` `src/vaultspec_a2a/graph/_compiler_topologies.py`
- `S04` `M` `src/vaultspec_a2a/thread/state.py`
- `S04` `A` `src/vaultspec_a2a/graph/tests/test_mounted_context_persistence.py`
- `S04` `M` `src/vaultspec_a2a/graph/tests/nodes/test_vault_reader.py`
- `S04` `M` `src/vaultspec_a2a/graph/tests/nodes/test_vault_write_isolation.py`
- `S04` `M` `src/vaultspec_a2a/thread/tests/test_state.py`
- `S04` `verify:` `pytest src/vaultspec_a2a/graph src/vaultspec_a2a/thread src/vaultspec_a2a/worker` -> `pass`
- `S04` `by:` `orchestrator`
- `S05` `A` `src/vaultspec_a2a/graph/run_context.py`
- `S05` `A` `src/vaultspec_a2a/graph/tests/test_run_context.py`
- `S05` `M` `src/vaultspec_a2a/graph/compiler.py`
- `S05` `M` `src/vaultspec_a2a/graph/_compiler_research.py`
- `S05` `M` `src/vaultspec_a2a/graph/_compiler_topologies.py`
- `S05` `M` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S05` `M` `src/vaultspec_a2a/graph/nodes/diverge.py`
- `S05` `M` `src/vaultspec_a2a/streaming/aggregator.py`
- `S05` `M` `src/vaultspec_a2a/streaming/ingest.py`
- `S05` `M` `src/vaultspec_a2a/streaming/types.py`
- `S05` `M` `src/vaultspec_a2a/worker/executor.py`
- `S05` `M` `src/vaultspec_a2a/streaming/tests/test_aggregator.py`
- `S05` `M` `src/vaultspec_a2a/worker/tests/test_state_projection_timeout_knob.py`
- `S05` `verify:` `pytest src/vaultspec_a2a/graph src/vaultspec_a2a/streaming src/vaultspec_a2a/worker src/vaultspec_a2a/thread src/vaultspec_a2a/team` -> `pass`
- `S05` `by:` `orchestrator`
- `S06` `M` `src/vaultspec_a2a/worker/executor.py`
- `S06` `M` `src/vaultspec_a2a/worker/_dispatch_settlement.py`
- `S06` `M` `src/vaultspec_a2a/worker/app.py`
- `S06` `M` `src/vaultspec_a2a/streaming/ingest.py`
- `S06` `M` `src/vaultspec_a2a/streaming/aggregator.py`
- `S06` `M` `src/vaultspec_a2a/streaming/types.py`
- `S06` `A` `src/vaultspec_a2a/worker/tests/test_executor_drain.py`
- `S06` `M` `src/vaultspec_a2a/streaming/tests/test_aggregator.py`
- `S06` `M` `src/vaultspec_a2a/worker/tests/test_state_projection_timeout_knob.py`
- `S06` `verify:` `pytest src/vaultspec_a2a/worker src/vaultspec_a2a/streaming src/vaultspec_a2a/graph` -> `pass`
- `S06` `by:` `orchestrator`
- `S07` `M` `src/vaultspec_a2a/streaming/transformer.py`
- `S07` `A` `src/vaultspec_a2a/streaming/tests/test_transformer_nostream.py`
- `S07` `verify:` `pytest src/vaultspec_a2a/streaming src/vaultspec_a2a/graph` -> `pass`
- `S07` `by:` `orchestrator`
- `S08` `A` `src/vaultspec_a2a/database/checkpoint_retention.py`
- `S08` `M` `src/vaultspec_a2a/database/checkpoints.py`
- `S08` `M` `src/vaultspec_a2a/control/event_handlers.py`
- `S08` `M` `src/vaultspec_a2a/conftest.py`
- `S08` `A` `src/vaultspec_a2a/database/tests/test_checkpoint_retention.py`
- `S08` `A` `src/vaultspec_a2a/control/tests/test_settled_history_pruning.py`
- `S08` `verify:` `runner database control gateway suites 1039` -> `pass`
- `S08` `by:` `vaultspec-high-executor`
- `S08` `verify:` `pytest database/tests/test_checkpoint_retention.py on sqlite and postgres connection, pool, selector-thread` -> `pass`
- `S08` `verify:` `pytest control/tests/test_settled_history_pruning.py` -> `pass`
- `S08` `by:` `orchestrator`
- `S09` `M` `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `S09` `M` `src/vaultspec_a2a/graph/compiler.py`
- `S09` `M` `src/vaultspec_a2a/graph/_compiler_topologies.py`
- `S09` `M` `src/vaultspec_a2a/thread/state.py`
- `S09` `M` `src/vaultspec_a2a/thread/errors.py`
- `S09` `M` `src/vaultspec_a2a/thread/__init__.py`
- `S09` `M` `src/vaultspec_a2a/domain_config.py`
- `S09` `M` `.env.example`
- `S09` `M` `src/vaultspec_a2a/worker/graph_lifecycle.py`
- `S09` `A` `src/vaultspec_a2a/graph/tests/test_supervisor_reask.py`
- `S09` `M` `src/vaultspec_a2a/graph/tests/nodes/test_supervisor.py`
- `S09` `M` `src/vaultspec_a2a/graph/tests/test_compiler.py`
- `S09` `M` `src/vaultspec_a2a/worker/tests/test_executor.py`
- `S09` `M` `src/vaultspec_a2a/thread/tests/test_errors.py`
- `S09` `M` `src/vaultspec_a2a/thread/tests/test_state.py`
- `S09` `verify:` `runner graph thread worker context streaming team suites` -> `pass`
- `S09` `by:` `orchestrator`
- `S10` `M` `src/vaultspec_a2a/worker/executor.py`
- `S10` `M` `src/vaultspec_a2a/thread/executable_graph.py`
- `S10` `M` `src/vaultspec_a2a/domain_config.py`
- `S10` `M` `src/vaultspec_a2a/team/team_config.py`
- `S10` `M` `src/vaultspec_a2a/thread/state.py`
- `S10` `M` `src/vaultspec_a2a/graph/nodes/phase_gate.py`
- `S10` `M` `src/vaultspec_a2a/graph/_compiler_research.py`
- `S10` `M` `src/vaultspec_a2a/graph/_compiler_topologies.py`
- `S10` `M` `src/vaultspec_a2a/graph/compiler.py`
- `S10` `A` `src/vaultspec_a2a/graph/tests/test_review_budget.py`
- `S10` `A` `src/vaultspec_a2a/worker/tests/test_executor_recursion_limit.py`
- `S10` `M` `src/vaultspec_a2a/worker/tests/test_executor.py`
- `S10` `M` `src/vaultspec_a2a/graph/tests/test_compiler.py`
- `S10` `M` `src/vaultspec_a2a/graph/tests/test_research_adr.py`
- `S10` `M` `src/vaultspec_a2a/thread/tests/test_state.py`
- `S10` `verify:` `runner graph team thread worker suites` -> `pass`
- `S10` `by:` `orchestrator`
- `S11` `M` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S11` `M` `src/vaultspec_a2a/control/permission_dispatch.py`
- `S11` `M` `src/vaultspec_a2a/control/permission_service.py`
- `S11` `A` `src/vaultspec_a2a/graph/tests/nodes/test_worker_permission_binding.py`
- `S11` `M` `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `S11` `verify:` `runner api worker acceptance providers control graph streaming suites` -> `pass`
- `S11` `by:` `orchestrator`
- `S12` `M` `src/vaultspec_a2a/worker/state_projection.py`
- `S12` `M` `src/vaultspec_a2a/worker/executor.py`
- `S12` `A` `src/vaultspec_a2a/worker/tests/test_executor_redelivery.py`
- `S12` `verify:` `runner worker api control acceptance streaming suites` -> `pass`
- `S12` `by:` `orchestrator`

## Notes

- `S01` pyproject.toml had drifted from taplo.toml, so the pre-commit format check refused any edit to it; a separate formatting-only commit (fa6d93c, parse-identical) landed first.
- `S06` LangGraph 1.2.12 astream_events drops its control keyword for version v2; the RunControl is seated as the parent runtime through the private CONFIG_KEY_RUNTIME, with the drain test as the tripwire.
- `S08` Closed by the orchestrator; the vaultspec-high-executor by-row above was a logging slip. Pruning runs on the gateway after terminal acceptance, not in the worker, because application receipts pin checkpoint ids the gateway reads in relay order.
- `S09` An exhausted re-ask budget fails the run with SupervisorRoutingError rather than finishing it; a new turn resets the budget through the graph input.
- `S10` The recursion limit resolves in the worker from the frozen graph definition (the lower of the gateway ceiling and the preset), not at the gateway call sites; the plan row scope was corrected through the plan verb.
- `S11` The binding needed no provider change: the worker names each permission request by task namespace and exact call, and the gateway echoes the answered request id in the tool-permission resume; the plan row scope was corrected through the plan verb.
- `S12` The receipt reducer's acceptance of a repeated dispatch_id (thread/action_receipts.py) was left as is: redelivery now continues from the checkpoint and never re-sends the receipt, so the reducer no longer sees the repeat; the plan row scope was corrected through the plan verb. The fix also closes the S06 drain/redelivery interaction, recorded in the audit.

