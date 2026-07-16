---
generated: true
tags:
  - '#index'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
related:
  - '[[2026-07-15-graph-agent-framework-harness-P01-summary]]'
  - '[[2026-07-15-graph-agent-framework-harness-P02-S03]]'
  - '[[2026-07-15-graph-agent-framework-harness-P02-S04]]'
  - '[[2026-07-15-graph-agent-framework-harness-P02-S13]]'
  - '[[2026-07-15-graph-agent-framework-harness-P04-S09]]'
  - '[[2026-07-15-graph-agent-framework-harness-P04-S10]]'
  - '[[2026-07-15-graph-agent-framework-harness-adr]]'
  - '[[2026-07-15-graph-agent-framework-harness-plan]]'
  - '[[2026-07-15-graph-agent-framework-harness-research]]'
---

# `graph-agent-framework-harness` feature index

Auto-generated index of all documents tagged with `#graph-agent-framework-harness`.

## Documents

### adr

- `2026-07-15-graph-agent-framework-harness-adr` - `graph-agent-framework-harness` adr: `closing the framework-harness gap for graph-executed document-authoring agents` | (**status:** `accepted`)

### exec

- `2026-07-15-graph-agent-framework-harness-P01-summary` - `graph-agent-framework-harness` `P01` summary
- `2026-07-15-graph-agent-framework-harness-P02-S03` - Extract the taxonomy/frontmatter/wiki-link/template conventions a document-authoring agent needs into a role-scoped rule source, separate from the full builtin corpus
- `2026-07-15-graph-agent-framework-harness-P02-S04` - Add role-targeting to rule discovery so a worker's compiled rule set can be scoped by persona role instead of concatenating every non-builtin file into every turn
- `2026-07-15-graph-agent-framework-harness-P02-S13` - Fix the RuleManager path-misalignment defect: align _RULES_SUBDIR to the current flat vaultspec-core 0.1.42 schema (rules live directly under .vaultspec/rules/*.md, confirmed by spec rules status) rather than the nonexistent nested rules/rules/ directory, with no dual-read legacy fallback per the owner's no-compat-shims directive
- `2026-07-15-graph-agent-framework-harness-P04-S09` - Wire the P02 role-scoped rule selection into the worker node's rule-compilation call, replacing the unconditional whole-corpus compile
- `2026-07-15-graph-agent-framework-harness-P04-S10` - Wire the equivalent role-scoped rule selection into the supervisor node's rule-compilation call

### plan

- `2026-07-15-graph-agent-framework-harness-plan` - `graph-agent-framework-harness` plan

### research

- `2026-07-15-graph-agent-framework-harness-research` - `graph-agent-framework-harness` research: `what graph-executed research_adr agents actually receive vs. the vaultspec framework harness they need`
