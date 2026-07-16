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

Retroactive Step Record, authored by the architect: the work landed inside commit `96bd13e` (the P04.S09/S10 call-site wiring) before this row existed; the row was added afterward so the third rule-injection entry point has plan traceability rather than riding invisibly on S09.

- Compile role-scoped rules inside the researcher producer: `_make_research_producer` in `src/vaultspec_a2a/graph/compiler.py` builds a `RuleManager` with the bundled defaults dir and calls `compile("researcher")`, injecting the result as a `Project Coding Rules & Guidelines` system message before the thread-spec message.
- Resolve the workspace root with the same fallback the worker path uses: an explicit argument or the graph state's `workspace_root` (mirroring `worker.py`), fed from the run's thread metadata by the worker graph lifecycle.
- Rationale carried in the producer docstring: `create_researcher_node` wraps a lightweight producer that never routes through `_build_worker_messages`, so without this the fourth research_adr document persona would author findings conventions-blind and the synthesist would fold them into a non-conformant document.

## Outcome

Landed and verified in `96bd13e` on main. Architect verified against HEAD by reading the producer in full: the researcher turn now receives the same role-scoped bundled conventions (S03 content through the S04 filter) as the worker/supervisor turns. Checkbox flipped on that landed evidence.

## Notes

The gap was flagged during the S09 wiring as the executor's own carried finding and closed within the same landing; team-lead separately authorized it as a follow-on before the landing was confirmed, so this record also serves as the do-not-refix marker. Live receipt-proof for the researcher persona (like the other three) belongs to P05.S11.
