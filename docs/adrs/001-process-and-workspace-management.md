---
adr_id: 001
title: Process & Workspace Management (LangGraph Core)
date: 2026-02-26
status: Proposed
related:
  - docs/distilled/2026-25-02-process-distilled.md
  - docs/research/2026-26-02-langgraph-gap-audit-research.md
---

# ADR-001: Process & Workspace Management (LangGraph Core)

**Date:** 2026-02-26  
**Status:** Proposed

## 1. Context & Problem Statement

The Python Orchestrator must supervise the execution of multiple independent agent LLM runs and manage their filesystem workspaces. This presents several challenges:

1. **Cross-Platform Process Safety:** Originally, the orchestrator attempted to wrangle native CLI binaries (Claude/Gemini) as subprocesses. This created a severe cross-platform risk on Windows 11 (requiring `pywin32` Job Objects) and brittle stdout parsing.
2. **Concurrent Filesystem Access:** Multiple coding agents editing the same repository will corrupt the `.git/index` and cross-contaminate test runs if they share a single working directory.
3. **Environment Resolution (`venv`):** The parent `vaultspec` app supports varied repository layouts, dictating entirely different rules for where an agent's Python virtual environment (`.venv`) and utility files are located.

## 2. The Decision

We have decided on a revised dual-strategy for Process Management and Workspace Isolation:

### Process Management (Native LangGraph)

1. **No External Subprocesses:** The orchestrator will **no longer** spawn external CLI binaries as subprocesses. Agent execution occurs entirely as native asynchronous Python coroutines managed by **LangGraph**. Tool calls and LLM generation are executed via LangChain's `BaseChatModel` abstractions.
2. **Crash Isolation via AsyncIO:** Because agents are now native async tasks running in the Uvicorn event loop, crash isolation is handled via standard Python `try/except` and `asyncio.TaskGroup` semantics. A failing agent tool call will not corrupt the memory space of other running agents.

### Workspace Isolation

1. **Dual-Mode Workspace Support:**
   - **Flat Hierarchy Mode:** The agent operates directly within the standard repository root. Python `.venv` and utility files are resolved locally within the current directory.
   - **Worktree Mode:** The agent operates within an isolated `git worktree` (e.g., `agent/coder/123`). Because worktrees are sparse checkouts, the orchestrator must resolve `.venv` and utility files to either the **container folder** (parent of the worktrees) or the **main repository root**.
2. **Manual Worktree Cleanup:** Worktree deletion functionality will be implemented but **will not be automatic**. Automatic cleanup is deemed too dangerous. We possess sufficient disk space to retain artifacts post-failure/completion for forensic review.
3. **Global Git Mutex:** A single `asyncio.Lock()` will serialize destructive, repository-wide operations (like `git fetch` or `git gc`) across all concurrent agents, preventing `.git` database corruption.

## 3. Rationale

- **Subprocess Abandonment:** Moving from wrangling vendor CLIs (which often expect interactive Linux PTYs) to executing native Python REST API calls resolves the "Windows 11 CLI Incompatibility" Tier-3 crisis entirely.
- **No Automatic Cleanup:** Blindly destroying worktrees after an agent crashes destroys vital context needed for debugging LLM hallucinations or system failures. Preserving the filesystem state is safer and more valuable than recovering disk space.
- **Dual-Mode Environments:** The parent `vaultspec` ecosystem inherently uses both flat and worktree configurations. Hardcoding the expectation that `.venv` is always locally available inside an agent's current working directory will instantly break worktree compatibility.

## 4. Rejected Alternatives

- **Native Subprocess Management (Original Design):** Rejected. Attempting to use `pywin32` Job Objects to babysit brittle Node.js/Go CLI wrappers cross-platform was overly complex and unreliable compared to invoking LangChain interfaces.
- **Automated Worktree Teardown:** Rejected. While it keeps the disk clean, it is overly destructive and ruins debuggability.
- **Standard `git checkout`:** Rejected for concurrent agents. Moving the HEAD of the main shared directory corrupts simultaneous test executions for other agents.

## 5. Implementation Constraints & Pitfalls

- **Async Tool Execution:** Because agents are now running natively in the Uvicorn thread, all tools *must* be strictly asynchronous (`async def`). A synchronous library call inside a LangChain tool will block the entire host webserver.
- **Environment Injection Routing:** When configuring LangChain `Tool` environments for an agent in Worktree Mode, developers must explicitly rewrite the `VIRTUAL_ENV` and `PATH` variables to point to the parent/main repository, otherwise tools requiring the `.venv` will fail.
- **Mutex Deadlocks:** The Global Git Mutex must be rigorously trapped in `try/finally` blocks. An agent crashing mid-fetch without releasing the lock will permanently freeze the rest of the team.

## 6. Negative Consequences

- **Shared Memory Risks:** Running all agents natively inside the Orchestrator's Python process means a catastrophic C-extension segfault invoked by a single agent's tool could technically crash the entire server (a risk previously mitigated by subprocess isolation).
- **Disk Bloat:** Disabling automatic worktree cleanup will inevitably lead to massive disk usage over time. We accept this trade-off for improved safety and debuggability.

## 7. References

- [LangGraph Gap Audit Research](../research/2026-26-02-langgraph-gap-audit-research.md)
- [Architecture Domain - Distilled](../distilled/2026-25-02-architecture-distilled.md)
