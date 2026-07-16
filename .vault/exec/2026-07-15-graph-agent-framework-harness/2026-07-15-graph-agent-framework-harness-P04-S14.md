---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S14'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# Wire the role-scoped rule compilation into the researcher producer path - create_researcher_node's injected producer never routed through the worker node's rule-compilation call, leaving the fourth document persona conventions-blind (P04.S09 follow-on flag, landed in 96bd13e as _make_research_producer compiling the researcher role with the bundled dir and the same workspace_root state fallback as the worker path)

## Scope

- `src/vaultspec_a2a/graph/compiler.py`

## Description

Step Record, authored by the architect. Attribution corrected per the executor: the wiring landed in `138f76f` (feat(graph): give the researcher persona its scoped conventions), NOT in `96bd13e` as this record first claimed - the architect's original "verified at HEAD" read was actually a read of the executor's then-uncommitted working tree, and `96bd13e` (the S09/S10 call-site wiring) never touched the diverge producer. The row itself was added before the landing on that mistaken read; the checkbox is honest against the real landing.

- Compile role-scoped rules inside the researcher producer: `_make_research_producer` in `src/vaultspec_a2a/graph/compiler.py` builds a `RuleManager` with the bundled defaults dir and calls `compile("researcher")`, injecting the result as a `Project Coding Rules & Guidelines` system message before the thread-spec message.
- Resolve the workspace root with the same fallback the worker path uses: an explicit argument or the graph state's `workspace_root` (mirroring `worker.py`), fed from the run's thread metadata by the worker graph lifecycle.
- Rationale carried in the producer docstring: `create_researcher_node` wraps a lightweight producer that never routes through `_build_worker_messages`, so without this the fourth research_adr document persona would author findings conventions-blind and the synthesist would fold them into a non-conformant document.

## Outcome

Landed in `138f76f` on main, with a real-object test (recording fake model, bare tmp workspace) proving the researcher's compiled messages carry the bundled conventions; 112 graph tests pass per the executor. The researcher turn now receives the same role-scoped bundled conventions (S03 content through the S04 filter) as the worker/supervisor turns. Checkbox stands on that landed evidence.

## Notes

The gap was flagged during the S09 wiring as the executor's own carried finding, authorized by team-lead as a follow-on, and closed by the executor in `138f76f`. Process lesson recorded: in this shared multi-writer tree a working-tree read is NOT landed evidence - verify landed claims with `git show HEAD:<file>` (or the commit diff), never the checkout, before citing a SHA. Live receipt-proof for the researcher persona (like the other three) belongs to P05.S11.
