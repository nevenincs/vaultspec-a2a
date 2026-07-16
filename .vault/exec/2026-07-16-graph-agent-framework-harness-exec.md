---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
step_id: '{S##}'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
  - "[[2026-07-15-graph-agent-framework-harness-P02-S04]]"
  - "[[2026-07-15-graph-agent-framework-harness-P02-S13]]"
---

# context-graph import cycle fix + LOW-1 invariant

Broke the twice-flagged `context` <-> `graph` circular import that made the
`context` package uncollectable in isolation, and folded in the reviewer's
LOW-1 sole-writer invariant comment. Both changes are landed on `main`. This is
a standalone remediation record: the defect was surfaced during Phase `P02`
work (the `P02.S04` and `P02.S13` Step Records, linked above) rather than
carrying its own plan Step.

- Modified: `src/vaultspec_a2a/graph/__init__.py`, `src/vaultspec_a2a/control/verdict_subscriber.py`
- Created: `src/vaultspec_a2a/context/tests/test_import_isolation.py`

## Description

- Reproduce the cold-import failure: importing `vaultspec_a2a.context` fresh
  raised `ImportError: cannot import name 'compact_context' from partially
  initialized module ...token_budget`.
- Trace the real chain: `context/__init__` imports `context.token_budget`,
  which imports `vaultspec_a2a.thread.state` (running the `thread` package
  init), whose `snapshots`/`permission_fsm` import the Layer-1 leaf
  `graph.enums`; importing that leaf ran the `graph` package init, which
  eagerly imported the `.compiler` tree up through `graph.nodes.supervisor`,
  which imports back into the still-initializing `context.token_budget`.
- Break the cycle in `graph`'s package init (commit `85cb993`, merged
  `ce12612`): defer the two `.compiler` exports (`build_initial_vault_index`,
  `compile_team_graph`) behind a module-level PEP 562 `__getattr__` plus a
  `_LAZY_IMPORTS` map, mirroring the identical idiom already used in the
  `providers` package init. Importing the `graph.enums` leaf no longer drags
  `.compiler` in, so the cycle never forms.
- Add the regression pin `test_import_isolation.py`: import each of the four
  entangled modules in a real fresh subprocess and assert returncode 0.
- Document the sole-writer invariant (commit `6e38e0e`) at the resume-claim
  read-modify-write in `control/verdict_subscriber.py`: the whole-blob RMW on
  `thread_metadata` is lost-update-safe only because the verdict subscriber is
  its sole writer after thread creation. This was the reviewer's LOW-1 finding
  from the batch-1 review of the adr-authoring-orchestration recovery-race work.

## Outcome

Landed on `main` at `ce12612`. Acceptance gate met: `pytest` collect-only over
the `context` tests succeeds in isolation (151 collected on the committed
tree) - the ADR's static-`compile()` check was explicitly insufficient, and
this proves the package imports cold. Context, graph, and thread suites pass
(260 passed, 3 pre-existing environment-gated skips); `ruff` and `ty` are
clean, including `ty` on the module-level `__getattr__`. The enums-move
alternative was rejected as fighting the leaf module's "all consumers import
directly from here" design with wide blast radius. Reviewer verdict: PASS
(batch-3), no findings; the fix also retroactively closed the isolated-collection
caveat previously flagged on the batch-2 rule tests.

## Notes

The only full-suite reds are the eight
`protocols/mcp/tests/test_server.py::*_raises_when_server_unavailable` cases -
a live gateway answering on port 8000 makes them not raise. That is the
documented environmental flake, not a regression from an import change.
