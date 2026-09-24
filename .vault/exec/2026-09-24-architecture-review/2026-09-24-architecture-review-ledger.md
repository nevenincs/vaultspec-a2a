---
tags:
  - '#exec'
  - '#architecture-review'
date: '2026-09-24'
modified: '2026-09-24'
body_schema: 'body-v2'
body_hash: 'sha256:c7ea8ef7afa60b933599b96873ab2e42fcc1d8d375455684af37b7a7a03e3095'
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

## Notes

- `S01` pyproject.toml had drifted from taplo.toml, so the pre-commit format check refused any edit to it; a separate formatting-only commit (fa6d93c, parse-identical) landed first.
