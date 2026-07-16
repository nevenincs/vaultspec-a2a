---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S09'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# Wire the P02 role-scoped rule selection into the worker node's rule-compilation call, replacing the unconditional whole-corpus compile

## Scope

- `src/vaultspec_a2a/graph/nodes/worker.py`

## Description

Landed in `96bd13e` (`feat(graph)`). `worker.py`'s `_build_worker_messages` now compiles rules from `bundled_rules_dir=DEFAULT_BUNDLED_RULES_DIR` and routes by role: a research_adr document role (researcher/synthesist/adr-author/doc-reviewer, via `_DOCUMENT_AUTHORING_ROLES`) compiles its role-scoped set; every other role compiles the whole corpus (role=None), so a coder's rules are never stripped. `create_worker_node` gains a `role` param; the compiler threads `agent_cfg.role` at the generic worker sites and the role literal at the four research_adr document-worker sites. Real-temp-dir test proves a document role gets the bundled conventions and NOT an untagged coder rule, while a coder role gets the whole corpus. 110 graph tests pass; ruff/ty clean. Known gap (flagged): the researcher's `create_researcher_node` (diverge.py) compiles no RuleManager rules at all today - pre-existing, outside the two named P04 call sites.

## Outcome

## Notes
