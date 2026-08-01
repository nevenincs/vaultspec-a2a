---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-07-15'
body_hash: 'sha256:22b6f637df68063ffe635c4314112d435834c491523277e82d55ea6ecac06a30'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-8` `step-1`

Extracted graph lifecycle management into `GraphLifecycleManager` class.

- Created: `src/vaultspec_a2a/worker/graph_lifecycle.py` (319 lines)

## Description

Moved the following methods from `Executor` into a new `GraphLifecycleManager` class:

- `_get_or_compile_graph` -> `get_or_compile_graph` (public, called by Executor)
- `_compile_graph` (private, team/agent config loading and `compile_team_graph` call)
- `_send_graph_registered` (private, BE-12 node metadata relay)
- `_build_graph_input` -> `build_graph_input` (static method, graph input dict construction)

The class owns `_graph_cache` (LRU `OrderedDict`), `_thread_to_cache_key` mapping, and `_provider_factory`. `Executor` creates the manager in `__init__` and delegates all graph operations to it.

`GraphCompilationError` is defined in `graph_lifecycle.py` and re-exported from `executor.py` via `__all__` for backwards compatibility of the public API.

## Tests

51 worker tests pass. `TestGraphInputBuilding` updated to call `GraphLifecycleManager.build_graph_input` instead of `Executor._build_graph_input`.
