---
title: Rule Propagation in A2A Pipeline
source: vaultspec-a2a research session
relevance: 10
---

# Rule Propagation in A2A Pipeline

## Executive Summary

This document analyzes the gap in rule propagation within the `vaultspec-a2a` LangGraph pipeline compared to the original `vaultspec` CLI framework. It details how rules are currently generated, how the native CLIs consume them, and how the A2A orchestrator must bridge the gap for API and CLI-agnostic agents.

## Original Mechanism in Vaultspec

1. **Rule Synchronization (The Source):**
   The `.vaultspec` framework acts as the centralized rule repository. The `vaultspec` CLI "compiles" and actuates these rules by copying them into provider-specific contexts (e.g., `.gemini/`, `.claude/`, `.agents/`). This generates:
   - Global definition files: `GEMINI.md`, `CLAUDE.md`, `AGENTS.md`
   - Copied rule fragments: `.gemini/rules/*.md`, `.agents/rules/*.md`

## The Architectural Gap in `vaultspec-a2a`

1. **Missing Project Mandate Injection:**
   In the `vaultspec` ecosystem, project-specific coding mandates (e.g., "Use absolute imports", "Follow snake_case conventions", "Do not truncate code") are stored as markdown files in the workspace root, typically deployed to `.agent/rules/` or `.gemini/rules/`.

   Currently, the LangGraph orchestration engine in `vaultspec-a2a` constructs a bare `SystemMessage` comprising *only* the intrinsic behavioral persona defined in the agent TOML files. It completely lacks a discovery pipeline to load the actual deployed project mandates.

2. **Universal Rule Blindness Across Providers:**
   Because `src/vaultspec_a2a/core/anchoring.py` does not resolve these project rule files, all native API agents (OpenAI, Zhipu) and ACP CLI wrapped agents (Gemini, Claude) operating within LangGraph are completely blind to the codebase's specific guidelines. This leads to code generations that violate project standards.

## Proposed Architecture (Awaiting Author Approval)

To fix this architectural gap, `vaultspec-a2a` must natively load these project mandates into the LLM context pipeline:

1. **Implement `RuleManager` Discovery Array:**
   The `RuleManager` (in `src/vaultspec_a2a/core/rules.py`) strictly targets the active project's file system (`workspace_root`). It must scan for actual rule directories in priority order:
   1. `[workspace_root]/.agent/rules/*.md` and `[workspace_root]/.agents/rules/*.md`
   2. `[workspace_root]/.gemini/rules/*.md` (or `.claude/rules/`)
   3. `[workspace_root]/.vaultspec/rules/rules/*.md` (Raw fallback if the CLI hasn't deployed them yet)

2. **Integrate into LangGraph Pipeline:**
   - Modified `build_anchoring_context` safely suppresses native mechanics. It calls `RuleManager` to parse the discovered rule fragments, drops the YAML frontmatter, resolves `@includes`, and explicitly appends them as a `## Project Rules & Guidelines` block *below* the Agent Persona in the `SystemMessage`.

3. **Suppress Native CLI Double-Reads:**
   - Ensure that `AcpChatModel` instances (or the CLI wrappers they spawn) are configured so they do not duplicate context by natively reading `GEMINI.md` while also receiving the LangGraph rules. This guarantees parity between native APIs and wrapped CLIs.

## Related Architecture Decisions

This research is formalized in **ADR-028: Universal Rule Propagation**. It executes in parallel with **ADR-029: Database Migration Framework**.

Source references for original logic studied:

- `y:/code/vaultspec-worktrees/main/src/vaultspec/protocol/providers/base.py` (for `resolve_includes`)
- `y:/code/vaultspec-worktrees/main/core/config_gen.py` (for `.gemini/` rule sync mechanics)
- `y:/code/vaultspec-a2a-worktrees/main/src/vaultspec_a2a/core/presets/agents/vaultspec-coder.toml` (for context bloat evidence)
