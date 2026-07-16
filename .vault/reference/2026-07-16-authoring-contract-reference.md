---
tags:
  - '#reference'
  - '#authoring-contract'
date: '2026-07-16'
modified: '2026-07-16'
related: []
---

# `authoring-contract` reference: `document-authoring roles/topology duplication sites and import-cycle map`

Ground-truth inventory of where "which roles and topologies author vault documents" is defined on the a2a backend, and the layering facts that constrain a single canonical home. Gathered by reading every site with `rg`/`fd` on the main branch; grounds the `authoring-contract` decision.

## Findings

### The contract is duplicated across five code/data sites plus test copies

- `TeamConfig.is_document_authoring` — `src/vaultspec_a2a/team/team_config.py` — a property returning `topology.type == RESEARCH_ADR`.
- `_DOCUMENT_AUTHORING_TOPOLOGIES` — `src/vaultspec_a2a/control/run_start_policy.py` — a frozenset of topology names.
- `_DOCUMENT_AUTHORING_ROLES` — `src/vaultspec_a2a/graph/nodes/worker.py` — a frozenset of the four role names `researcher`, `synthesist`, `adr-author`, `doc-reviewer`.
- `_RA_REQUIRED_ROLES` — `src/vaultspec_a2a/graph/compiler.py` — the SAME four roles as an ORDERED tuple (order matters for model resolution and node wiring); a variant the initial triage missed.
- `roles:` frontmatter of the bundled `src/vaultspec_a2a/context/presets/rules/document-authoring-conventions.md` — the fourth code/data copy of the roles list, consumed by role-scoped rule compilation.
- Hardcoded copies in tests (e.g. `src/vaultspec_a2a/context/tests/test_rules.py`).

Consequence: each added authoring role or topology must be replicated by hand across all sites; a missed site yields divergent policy — a role scoped out of its rules, or a preset admitted to run-start without its token bundle.

### The gateway→worker private cross-import is branch-only, not on main

On the main branch, no `gateway`/`api` module imports `worker._DOCUMENT_AUTHORING_ROLES`; the only consumers of that private constant live inside `worker.py`. The fragile cross-import review-fanout flagged existed on an unmerged campaign branch. Deleting the private constant during migration retires the pattern regardless: any branch still carrying it fails loudly with an `ImportError` at rebase rather than drifting silently.

### Two vocabularies must not be merged

Role NAMES (`researcher`, `synthesist`, `adr-author`, `doc-reviewer`) are `AgentConfig.role` values. Agent IDS (`vaultspec-synthesist`, ...) key actor tokens and profiles (`run_start_policy.required_role_ids`, derived from `team_config.workers`). The contract covers role and topology NAMES only; `required_role_ids` stays in `run_start_policy`.

### Import-cycle map constrains the canonical home

`graph/__init__.py` and `providers/__init__.py` already carry PEP-562 lazy imports to break a `context → thread → graph.enums` cycle, and `team_config` imports `graph.enums`. The canonical home must be importable by `api`, `graph`, `control`, `team`, and `context` without closing any cycle. The `authoring` package is internally a leaf (only external dependency `httpx`, zero `vaultspec_a2a.*` imports); a module with no internal imports cannot close a cycle. Candidate homes `team_config`, `control`, and `context` each either deepen the graph/team bidirectional coupling, invert control layering, or sit inside the known cycle chain.

### Verified enabling fact: StrEnum members hash equal to their str values

Confirmed in the project venv: `TopologyType.RESEARCH_ADR in frozenset({"research_adr"})` is `True`. A string-typed topology frozenset therefore accepts `TopologyType` members directly, so the contract module needs no import of the enum and stays a true zero-internal-import leaf.

### Sibling finding: the rules-presence signal is a semantic fork, not a copy

`verify_harness`'s `_rule_content_resolves` (`src/vaultspec_a2a/context/harness.py`) is bundled-AWARE — "does any rule content resolve over workspace ∪ bundled?" — the run-start/discovery eligibility predicate (a bundled-only Path B workspace passes). `RuleManager.has_workspace_rules` (`src/vaultspec_a2a/context/rules.py`) is bundled-BLIND by design — "is this workspace itself provisioned?" Post the bundled-aware ruling these answer different questions; `has_workspace_rules` had zero consumers outside its own tests and a docstring still claiming to be the harness signal, so it was removed as dead code rather than kept as a fork-prone parallel predicate.
