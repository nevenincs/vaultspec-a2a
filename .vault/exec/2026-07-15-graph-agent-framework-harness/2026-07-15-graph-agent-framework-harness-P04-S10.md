---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S10'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# Wire the equivalent role-scoped rule selection into the supervisor node's rule-compilation call

## Scope

- `src/vaultspec_a2a/graph/nodes/supervisor.py`

## Description

Landed in `96bd13e` (`feat(graph)`). `supervisor.py`'s `_build_supervisor_messages` now compiles rules from `bundled_rules_dir=DEFAULT_BUNDLED_RULES_DIR` with `role=None` - the supervisor is not a document-authoring role, so it keeps the whole corpus unioned with the bundled defaults (P02.S03 union/shadow). Same commit as the worker call site (P04.S09); ruff/ty clean, 110 graph tests pass.

## Outcome

## Notes
