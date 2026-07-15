---
tags:
- '#adr'
- '#universal-rule-propagation'
date: 2026-03-31
modified: '2026-07-15'
related:
  - '[[2026-03-31-docs-vault-migration-research]]'
  - '[[2026-07-15-graph-agent-framework-harness-adr]]'
---

# `universal-rule-propagation` adr: `adr-028` | (**status:** `accepted`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-028`
- Original title: `ADR 028: Universal Rule Propagation`
- Legacy status at migration time: `Proposed`

## Reconciliation Note (2026-07-15)

Status flipped `proposed` -> `accepted`: the `RuleManager` mechanism this ADR proposed was independently verified as fully implemented and wired into both `src/vaultspec_a2a/graph/nodes/worker.py:60` and `supervisor.py:310` (discovery, `@include` resolution, mtime caching, `SystemMessage` injection immediately after the persona system prompt) - the decision was executed, not merely drafted. The remaining gaps this ADR's "outstanding question" left open - what to do about builtin rules, and whether the propagated payload actually reaches document-authoring agents in a form they can act on - are picked up by `2026-07-15-graph-agent-framework-harness-adr` (accepted), which found: `include_builtin=False` at both call sites excludes exactly the mechanical builtin guidance (CLI reference, rag syntax, discovery sequence, core mandates); `.vaultspec/rules/rules/` is empty in this repo so there is nothing non-builtin to propagate today; and the four research_adr document personas' own prompts instruct CLI/rag invocations their `terminal=false` capability cannot execute. That ADR and its implementation plan are the live continuation of this one; this ADR is not superseded, its proposed mechanism was built and its unresolved question is now answered and tracked forward.

## Original ADR

# ADR 028: Universal Rule Propagation

Date: 2026-03-04
Status: Flaky - needs researching and formalizing

## Context

The LangGraph pipeline's agent toml and team toml config files already embed .vaultspec/rules/system semantic meaning - even if the exact success and prescision of the
implementation isn't substatiated 100%.

Two problem areas remain related to rules:

- are the contents of .vaultspec managed .vaultspec/rules/rules/*.builtin.md already part of agent and team personas? Do the rules contain extra context that would mandate loading them as extra context via the LangGraph pipeline?
- How are rules NOT managed by .vaultspec loaded by the LangGraph nodes and pipeline?

Must check and verify that .vaultspec manages and deploys custom rules via its cli interface. Is this a functionality it implements? I undertand that if the user uses the vaultspec cli to add a new rule the rule md file will be persisted to the .vaultspec/rules/rules folder without the builtin marker. These are considered custom rules managed by vaultspec (and later deplyoed to the provider folder like .gemini/rules or .agent/rules).

I propose that we make the Langgraph pipeline know about these rules in the vaultspec/rules/rules dir and always export the custom rules as system context.
The outstanding question is what to do about the builtin rules. The concern is context bloat and informatino duplication if their sematic meaning has already been added to the agent personas.

### The Problem

Currently, the LangGraph orchestration engine in `vaultspec-a2a` completely lacks a mechanism to discover and load these project rules into its execution context.

When `src/vaultspec_a2a/core/anchoring.py` constructs the base `SystemMessage` for an agent, it includes only the agent's intrinsic behavioral persona (from the TOML definition).

Consequently, **none of the project-defined mandates end up in the LangGraph pipeline**. All agents across all supported providers (OpenAI, Zhipu, Claude, Gemini) operate completely blind to the project-specific coding mandates that govern the repository they are working in. This leads to agents generating code that violates the project's established standards.

## Proposed Decision (Awaiting Author Approval)

To ensuring LangGraph context availability for project-set rules, we propose implementing a universal discovery and transclusion mechanism:

**1. Rule Discovery (`RuleManager`)**
We will implement a `RuleManager` in `src/vaultspec_a2a/core/rules.py`

**2. Rule Compilation and Transclusion**
The `RuleManager` will parse these discovered rule files, strip out any YAML frontmatter (which is for IDE metadata, not LLM context), and resolve any internal `@includes` (a vaultspec feature).

**3. LangGraph Context Injection**
In `src/vaultspec_a2a/core/anchoring.py`, the `build_anchoring_context` function will be updated. It will call the `RuleManager` to retrieve the active project mandates. These rules will be concatenated into a unified `## Project Coding Rules & Guidelines` block and injected into the LangGraph `SystemMessage` immediately *after* the agent's primary persona.

This ensures that every agent, regardless of whether it is powered by an ACP wrapper or a native API, explicitly receives all project mandates in its context pipeline.

## Consequences

### Positive

- **Persona Preservation**: The high-fidelity agent definitions remain the master source of truth, maintaining exact intent.
- **Provider Equivalence**: An OpenAI API agent and a Gemini CLI agent will receive the exact same rule mandates, eliminating arbitrary behavioral discrepancies.
- **Architectural Cleanup**: Rule compilation becomes a localized, testable LangGraph sub-routine rather than an OS-level environment variable bridging hack.

### Negative

- **Token Inflation**: Injecting large markdown rule sets directly into the `SystemMessage` on every loop cycle will increase input token usage against the LLM providers, though role-targeting mitigates this.
- **Complexity**: We must ensure native CLIs (like Gemini) don't duplicate the newly injected LangGraph rules with their own implicit file-reads.

## References

- Source implementation of legacy logic: `y:/code/vaultspec-worktrees/main/src/vaultspec/protocol/providers/base.py` (specifically `resolve_includes`).
- Initial Audit: `legacy-research/2026-03-04-rule-propagation-research.md` (Empirical finding of the gap).
- ADR-014 - Establishes the existence of the Context Preamble SystemMessage.
- ADR-022 - Governs the `build_anchoring_context` hook where these rules will be injected.
