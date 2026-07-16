---
tags:
  - '#adr'
  - '#authoring-contract'
date: '2026-07-16'
modified: '2026-07-16'
related:
  - '[[2026-07-16-authoring-contract-reference]]'
  - '[[2026-07-15-agent-harness-provisioning-adr]]'
  - '[[2026-07-15-graph-agent-framework-harness-adr]]'
---

# `authoring-contract` adr: `single-source document-authoring roles and topology contract` | (**status:** `accepted`)

## Problem Statement

The fact "which roles and topologies author vault documents through engine proposals" is defined independently in four code sites and one data file: `TeamConfig.is_document_authoring` in `src/vaultspec_a2a/team/team_config.py` (topology equality check), `_DOCUMENT_AUTHORING_TOPOLOGIES` in `src/vaultspec_a2a/control/run_start_policy.py` (frozenset), `_DOCUMENT_AUTHORING_ROLES` in `src/vaultspec_a2a/graph/nodes/worker.py` (frozenset of four role names), `_RA_REQUIRED_ROLES` in `src/vaultspec_a2a/graph/compiler.py` (the same four roles as an ordered tuple), and the `roles:` frontmatter of the bundled `document-authoring-conventions.md` rule file, plus hardcoded copies in tests. Review fanout additionally flagged a branch-side pattern of the gateway importing the worker's `_`-private roles constant across the api-to-graph boundary — a worker refactor would silently break run-start harness probing. Two concurrent campaigns (agent-harness-provisioning, dev-process-registry) both touch these files; every added authoring role or topology must currently be replicated by hand across five-plus sites, and a missed site produces divergent policy (a role scoped out of its rules, or a preset admitted to run-start without its token bundle). A decision on the single canonical home is needed before either campaign extends the contract again.

A sibling near-duplication was triaged in the same review: the harness rules-presence signal exists as the bundled-aware `_rule_content_resolves` leg in `src/vaultspec_a2a/context/harness.py` and as the deliberately bundled-blind `RuleManager.has_workspace_rules` in `src/vaultspec_a2a/context/rules.py`. These are a semantic fork, not copies; this record fixes their roles so the fork cannot be mistaken for redundancy again.

## Considerations

- Import-cycle fragility is the binding force: `graph/__init__.py` and `providers/__init__.py` already carry PEP-562 lazy imports to break a context-to-thread-to-graph.enums cycle, and `team_config` imports `graph.enums` while graph nodes would need the roles set — the canonical home must be importable by `api`, `graph`, `control`, `team`, and `context` without closing any cycle.
- Two vocabularies coexist and must not be merged: role names (`researcher`, `synthesist`, `adr-author`, `doc-reviewer`) are `AgentConfig.role` values; agent ids (`vaultspec-synthesist`, ...) key actor tokens and profiles. The contract covers role and topology names only; `required_role_ids` in `run_start_policy` derives agent ids from `team_config.workers` and stays put.
- The roles set gates security-relevant policy (run-start refusal, token-bundle coverage, rule scoping), so it must not be derivable from workspace-overridable data at runtime.
- `graph/compiler.py` needs the roles in a fixed order (model resolution and node wiring); `worker.py` needs set membership — the contract must serve both from one definition.
- Verified enabling fact: `StrEnum` members hash equal to their string values, so a string-typed topology frozenset accepts `TopologyType` members directly and the contract module needs no import of the enum.
- Both in-flight campaigns edit `worker.py`, `gateway.py`, and `run_start_policy.py`; the migration must land as small per-file diffs that rebase cleanly.

## Considered options

- New zero-internal-import leaf `src/vaultspec_a2a/authoring/contract.py` — CHOSEN. The `authoring` package is the engine-proposal client and is internally a leaf (only external dep httpx); a module with no internal imports cannot close a cycle, so every consumer imports it safely. Semantically the exact domain.
- `team/team_config.py` (already owns `TopologyType` and the property) — rejected: worker importing it adds a graph-to-team runtime edge on top of the existing team-to-graph.enums edge, deepening exactly the bidirectional coupling the lazy-import workarounds already fight.
- `control/run_start_policy.py` — rejected: graph importing control inverts layering (control is policy over team/graph outputs, not vocabulary under them).
- `context/` — rejected: participates in the known context-to-thread-to-graph.enums import chain, and team-topology vocabulary does not belong in the rules/harness package.
- Deriving the code constant from the bundled rule file's `roles:` frontmatter — rejected: makes security-relevant policy workspace-mutable and adds import-time file I/O.
- Generating the data file from code — rejected: build machinery for a four-line list.

## Constraints

- The contract module must remain zero-internal-import permanently; a single internal import can re-close the documented cycle and crash the gateway at import time. This is a reviewable invariant (its import block is empty of `vaultspec_a2a` names).
- Depends on stable, already-merged parents: `TopologyType` (`team_config`), the role-scoped rule compile (`RuleManager.compile(role)`, graph-agent-framework-harness P02), and the harness verifier (`verify_harness`, agent-harness-provisioning P01 plus the bundled-aware rules-leg ruling). All are on main and test-covered; no frontier risk.
- Landing occurs while two campaigns hold branches over the consumer files; the migration order below is part of the decision, not an implementation detail.

## Implementation

Create `src/vaultspec_a2a/authoring/contract.py` exposing: `DOCUMENT_AUTHORING_ROLES` (ordered tuple `("researcher", "synthesist", "adr-author", "doc-reviewer")`), `DOCUMENT_AUTHORING_ROLE_SET` (frozenset derived from the tuple), `DOCUMENT_AUTHORING_TOPOLOGIES` (string frozenset `{"research_adr"}`), and predicates `is_document_authoring_role(role)` and `is_document_authoring_topology(topology_type)` (parameter typed `str`; `TopologyType` members pass directly as `StrEnum`). Consumers migrate to delegations: `TeamConfig.is_document_authoring` calls the topology predicate (property retained as the ergonomic API); `run_start_policy.is_document_authoring_preset` delegates to that property and drops its private frozenset; `worker.py` drops `_DOCUMENT_AUTHORING_ROLES` for the role predicate; `compiler.py` imports the ordered tuple as its required-roles source. Gateway and any future api-layer consumer import `authoring.contract`, never `graph.nodes.*`. Data-file sync is test-enforced: a test using the existing `_read_frontmatter`/`_roles_from_meta` helpers asserts the bundled `document-authoring-conventions.md` `roles:` set equals `DOCUMENT_AUTHORING_ROLE_SET`; the hardcoded role lists in existing tests switch to the contract constant.

For the rules-presence fork: `verify_harness`'s bundled-aware `_rule_content_resolves` remains the sole rules-eligibility predicate; `RuleManager.has_workspace_rules` had no consumer and its P01.S02 rules-absence-surfacing intent is already delivered by the bundled-aware verifier, so it is removed as dead code rather than kept as a fork-prone parallel predicate — the same change corrects any docstring that named a workspace-only probe the harness signal.

Migration lands in three isolated commit groups, never combined: first the additive contract module with its unit test and the data-sync test (touches no contested file); then one consumer file per commit (`team_config`, `run_start_policy`, `compiler`, `worker` — each a roughly three-line mechanical diff) plus the dead-code removal; finally the test files holding hardcoded role lists.

## Rationale

The knockout criterion is cycle-proofness by construction: every candidate home except a zero-internal-import leaf either deepens the graph/team bidirectional coupling or inverts the control layering, and the codebase's existing lazy-import scars show how costly a new cycle is. Among leaf placements, `authoring/` wins on domain fit — the contract literally enumerates who authors through engine proposals, which is that package's subject. Code-truth with a sync test wins over data-derivation because the roles set gates run-start refusal and token coverage; policy must not be mutable by a workspace file that agents and operators can override. Deleting the private worker constant (rather than exporting it) is what permanently retires the fragile gateway-to-worker cross-import: any branch still carrying it fails loudly with an ImportError at rebase and migrates to the contract, instead of silently drifting. Grounding: the review-fanout findings and the harness eligibility work recorded under the agent-harness-provisioning ADR and the graph-agent-framework-harness execution records.

## Consequences

- Binding decision (a): the document-authoring roles/topology contract lives in the zero-internal-import leaf `authoring/contract.py`; new authoring roles or topologies are added there and nowhere else. Re-inlining a private copy in a consumer is a review-blocking violation of this record.
- Binding decision (b): policy constants are code-truth, never derived from workspace-overridable data; code-data agreement is test-enforced, and the bundled conventions file's `roles:` list follows the constant.
- Binding decision (c): the harness rules-eligibility predicate is the bundled-aware `verify_harness` leg (`_rule_content_resolves`); workspace-only rules-presence is a provisioning-status question, never an eligibility input. The dead bundled-blind probe was removed so the two cannot be confused again.
- Gains: one edit point for the next authoring topology or role; the gateway/api layer gains a public, stable import target; four code copies and the test copies collapse; the rules-presence fork is named and each predicate has exactly one job.
- Costs accepted: one more top-level contract module to know about; the `authoring` package now carries vocabulary alongside its HTTP client (a deliberate scope widening); campaign branches holding the old private constant must rebase through an intentional ImportError.
- Pitfall to watch: the leaf invariant is enforced only by review and the module's own test; adding a convenience import of `TopologyType` "for typing" would quietly break it — annotations stay `str`.
- Opens: future authoring topologies (for example a plan-authoring machine) join by extending two constants and their preset TOML, with run-start policy, rule scoping, compiler role resolution, and harness probing all following automatically.
