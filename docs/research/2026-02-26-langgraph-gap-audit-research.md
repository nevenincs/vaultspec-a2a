---
name: 'LangGraph Gap Audit & Evaluation'
date: 2026-26-02
type: research
summary: 'Comprehensive inventory of all gaps, contradictions, and oversights found in the technical documentation, including a detailed evaluation of LangGraph and its architectural benefits to the project.'
maturity: 60
feature: langgraph-gaps
---

# Gap Audit & LangGraph Architecture Evaluation

This document consolidates and explicitly identifies all contradictions, gaps,
and oversights across the 5 core domains of the distilled documentation logic.
Furthermore, it addresses the open question regarding **LangGraph** (C6/G11) and
evaluates how its adoption resolves a significant portion of the critical
architectural gaps.

## 1. Inventory of Identified Contradictions

These are the internal disagreements discovered across the distilled notes that
must be formally resolved.

### Architecture

- **C1: Internal vs External SSE.** Rejecting SSE for user UI because it blocks
  CLI, but adopting it internally between Orchestrator and Agent without
  addressing similar blocking risks.
- **C2: Subprocess Spawning Complexity.** Described simultaneously as a "solved
  baseline" but tagged as "Tier 3: Novel implementation" in the integration
  assessments.
- **C3: Database Strategy.** SQLite is mandated for local zero-config execution
  (ADR-007), but Postgres is sporadically assumed in architecture research with
  no migration path defined.
- **C4: Ephemeral Agents Assumption.** Ephemeral agent subprocesses are assumed
  without empirical data on the latency overhead of their cold-starts.
- **C5: MCP Tasks Future.** MCP Tasks are described both as "the most promising
  structure" and "deferred due to instability." (Resolved in favor of stable
  tools for v1 by ADR-003).
- **C6: LangGraph Deferred.** Identified as heavily leaned-towards for agent
  internal loops but never actively confirmed or evaluated.
- **C7: Agent/LLM Framework Undecided.** LiteLLM and CrewAI listed as potential
  architectures but discarded silently.

### Agents

- **C1: ACP Heterogeneity.** Gemini has native ACP, Claude needs a wrapper,
  Codex/GLM-5 have no ACP wrappers. No consensus on whether to adapt all or
  favor a unified wrapper.
- **C2: A2A Integration Discord.** 3 distinct integration strategies: MCP-to-A2A
  bridges (Claude/Codex), Native A2A (Gemini), Custom APIs (GLM-5).
- **C3: Subscription By-passes.** Extreme fragility differences between
  officially supported headless API limits versus scraping browser session
  tokens (Codex/Gemini).

### Protocols

- **C1: ACP vs A2A Output Types.** Explicit guidance states agents should speak
  A2A, but acknowledges that A2A's generic data parts lack the crucial semantic
  richness of ACP's 11 distinct update types.
- **C2: The Richness Void.** Protocol foundations celebrate ACP's rich updates,
  but the architectural decision defaults to A2A without formally addressing how
  the lost UI context will be recovered.

### Process & Control Surface

- **C1: Monitoring Scope.** Research demands rich Cost & Latency matrices
  tracking, while the V1 scope explicitly defers them.
- **C2: WebSocket Multiplicity.** Research implies per-terminal WebSockets are
  ideal for isolation; architecture relies on a single multiplexed channel.
- **C3: Redis Need.** Disagreement on whether Redis is required for
  Webhooks/PubSub; successfully deferred to SQLite for local v1.

---

## 2. Inventory of Knowledge Gaps & Oversights

The following list identifies missing critical knowledge required to confidently
code the underlying architecture.

### Critical Blockers

- **G1 (Agents): Windows Incompatibility.** The constraint is Windows 11 PWSH,
  but the native CLIs of Claude/Gemini/Codex are optimized for Linux/macOS.
  Operating complex subprocess PTYs with them headless runs a massive risk of
  immediate execution failure.
- **G2 (Protocols): MCP Task CLI Support.** No verification that external
  end-user CLIs actually support calling tools as background asynchronous tasks
  (`call_tool_as_task`).
- **G3 (Architecture): No Provider Adapter Interface.** The core platform lacks
  an abstraction defining how to invoke tools and prompt text uniformly across
  Claude, Gemini, and Codex.
- **G4 (Architecture): Missing LLM Integration Layer.** Token counting, context
  overflow, and format mapping are missing completely.

### High Priority

- **G5 (Process): Health vs Stability Thresholds.** Ambiguous definition of when
  an agent has actually successfully booted vs just opened a port.
- **G6 (Process): pywin32 Support.** Risk of Windows Job Objects functioning
  incorrectly in newer Python 3.13 environments.
- **G7 (Architecture): State Persistence & Schema.** Lacking DB schema for
  SQLite.
- **G8 (Architecture): Error Recovery Engine.** No mechanism to recover state on
  agent fault.
- **G9 (Architecture): Permission Flow Resolution.** Granularity of agent
  permissions handling not fleshed out in the core pipeline.
- **G10 (Architecture): Context Management.** No rules for dropping context when
  agents exceed LLM token limits (`context window exhausted`).

### Medium Priority

- **G11 (Agents): Token Lifecycles.** Assuming static tokens ignores mid-task
  token expiry.
- **G12 (Process): OTel Setup Timing.** Blindly implementing massive
  asynchronous event pipelines without structured telemetry active.
- **G13 (Control): Multiplexer Flow Control.** Custom backpressure not specified
  for generic WebSocket relaying.
- **G14 (Architecture): Merge Conflict Resolution.** Multi-agent Git worktree
  collision rules are missing.

---

## 3. The LangGraph Opportunity (Evaluating C6 / G11)

Based on a thorough review of the `langgraph`and`langchain`reference
repositories, **LangGraph provides a tremendous opportunity to offload
significant architectural burden.**

LangGraph is a library for building stateful, multi-actor applications by
defining a control flow graph of nodes and edges, powered underneath by
LangChain's massive integration ecosystem.

### How LangGraph Systematically Resolves Existing Constraints

| Identified Gap                                              | LangGraph Resolution                                                                                                                                                                                                                                                                                |
| :---------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **G3 / G4: Custom LLM Integration & Provider Abstractions** | **Solved entirely.** LangChain provides out-of-the-box`BaseChatModel`abstractions. You write tool schemas and prompts once, and LangChain invokes Claude, Gemini, OpenAI uniformly. No bespoke mapping needed.                                                                                      |
| **G1 (Agents): CLI Windows Incompatibility Risk**           | **Major Risk Reduced.** Instead of trying to wrangle unstable vendor CLI binaries via subprocess PTYs in Windows, we can use LangGraph to execute native Python functions. The agent logic lives natively inside the orchestrator or stable A2A python agents, bypassing CLI wrapper bugs entirely. |
| **G7: State Persistence Schema**                            | **Solved entirely.** LangGraph contains a production-ready`checkpoint-sqlite`package built for async Python 3.10+. It natively saves the state graph persistently after every node execution.                                                                                                       |
| **G8: Error Recovery & State Resumption**                   | **Solved entirely.** Because every transition is checkpointed via SQLite, LangGraph inherently supports resuming execution exactly from where it crashed.                                                                                                                                           |
| **G9: Permission & H-I-T-L Flows**                          | **Natively Supported.** LangGraph supports`interrupt_before`and`interrupt_after`on any node. The agent pauses natively, writes its checkpointer state, and allows the Orchestrator to ping the user via WebSocket. Once permission is updated, execution resumes seamlessly.                        |
| **G10: Context Window Accumulation**                        | **Natively Supported.** LangGraph offers features like`trim_messages`inside graph nodes to safely drop older messages or summarize reasoning to avoid LLM token-exhaustion crashes.                                                                                                                 |
| **C1 / C2 (Protocols): The ACP Richness Gap**               | By using LangGraph, we capture structured JSON outputs from LangChain callbacks at every step. This provides native insight into _tool execution_, _routing decisions_, and _thoughts_ without having to reverse-engineer a generic CLI's output strings.                                           |

## 4. Conclusion & Architectural Recommendation

Adopting **LangGraph** (with its`checkpoint-sqlite`package) shifts the
orchestrator's role from building an experimental, error-prone workflow engine
from scratch, to instead hosting a mature, proven state-machine framework.

By defining the Team Strategy (Planner → Coder → Reviewer) as a compiled
LangGraph`StateGraph`, the codebase instantly gains:

1. Resilient execution and SQL state persistence.
2. Cross-provider vendor neutrality instantly.
3. Clean user-interruption breakpoints for permission elevation.
4. Robust abstractions over context-window truncation.

**Recommendation:** We formally resolve the C6 contradiction by moving to adopt
LangGraph and LangChain as the underlying execution core for internal agent
representation and orchestration. This eliminates vast swaths of high-risk tasks
("G1: No Provider Adapter", "G2: LLM Integration Layer Missing") and allows
focusing strictly on the frontend and MCP bridges.
