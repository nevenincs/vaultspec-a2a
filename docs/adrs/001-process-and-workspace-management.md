---
adr_id: 001
title: Process & Workspace Management
date: 2026-02-25
status: Proposed
related:
  - docs/distilled/2026-25-02-process-distilled.md
  - docs/distilled/2026-25-02-process-gaps-research.md
  - docs/distilled/2026-25-02-architecture-distilled.md
  - docs/distilled/2026-25-02-architecture-gaps-research.md
  - docs/process/2026-25-02-agent-process-lifecycle-research.md
---

# ADR-001: Process & Workspace Management

**Date:** 2026-02-25  
**Status:** Proposed

## 1. Context & Problem Statement

The Python Orchestrator must supervise the execution of multiple independent agent binaries as child subprocesses, and manage their filesystem workspaces. This presents several cross-platform and structural challenges:

1. **Cross-Platform Process Safety:** The orchestrator must run across Windows, Linux, and macOS. Windows lacks POSIX signals (`SIGTERM`), creating a severe risk of "orphan" agent processes if the orchestrator crashes. A unified but platform-aware process manager is required.
2. **Variable Agent Startup:** AI agents bind network ports quickly but often crash seconds later while loading massive context windows, causing false-positive health checks.
3. **Concurrent Filesystem Access:** Multiple coding agents editing the same repository will corrupt the `.git/index` and cross-contaminate test runs if they share a single working directory.
4. **Environment Resolution (`venv`):** The parent `vaultspec` app supports varied repository layouts, dictating entirely different rules for where an agent's Python virtual environment (`.venv`) and utility files are located.

## 2. The Decision

We have decided on a dual-strategy for Process Management and Workspace Isolation:

### Process Management

1. **Platform-Specific Subprocess Lifecycle:**
   - **Windows:** Spawn agents using `pywin32` Windows Job Objects configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. This guarantees the OS immediately kills the child process if the orchestrator terminates abruptly.
   - **Unix/Linux/macOS:** Spawn agents in their own POSIX Process Groups (`os.setsid`) and use `SIGTERM`/`SIGKILL` against the process group to ensure clean teardown.
2. **30-Second Stability Threshold:** Agents will transition from `STARTING` $\rightarrow$ `READY` (upon first successful HTTP 200 health probe). However, they will only reach the `RUNNING` state—clearing retry backoffs—after surviving 30 seconds without crashing.

### Workspace Isolation

3. **Dual-Mode Workspace Support:**
   - **Flat Hierarchy Mode:** The agent operates directly within the standard repository root. Python `.venv` and utility files are resolved locally within the current directory.
   - **Worktree Mode:** The agent operates within an isolated `git worktree` (e.g., `agent/coder/123`). Because worktrees are sparse checkouts, the orchestrator must resolve `.venv` and utility files to either the **container folder** (parent of the worktrees) or the **main repository root**.
2. **Manual Worktree Cleanup:** Worktree deletion functionality will be implemented but **will not be automatic**. Automatic cleanup is deemed too dangerous. We possess sufficient disk space to retain artifacts post-failure/completion for forensic review.
3. **Global Git Mutex:** A single `asyncio.Lock()` will serialize destructive, repository-wide operations (like `git fetch` or `git gc`) across all concurrent agents, preventing `.git` database corruption.

## 3. Rationale
- **Cross-Platform Parity:** While Windows Job Objects are essential for our primary target environment (Windows 11 PWSH), locking the orchestrator exclusively to Windows limits future deployment topologies. Implementing OS-specific branches within the Process Manager ensures universal reliability.
- **No Automatic Cleanup:** Blindly destroying worktrees after an agent crashes destroys vital context needed for debugging LLM hallucinations or system failures. Preserving the filesystem state is safer and more valuable than recovering disk space.
- **Dual-Mode Environments:** The parent `vaultspec` ecosystem inherently uses both flat and worktree configurations. Hardcoding the expectation that `.venv` is always locally available inside an agent's current working directory will instantly break worktree compatibility.

## 4. Rejected Alternatives
- **`atexit` or `psutil` exclusively:** Rejected as the primary cleanup mechanism on Windows because it fails entirely during hard orchestrator crashes (e.g., power loss, `taskkill /F`).
- **Automated Worktree Teardown:** Rejected. While it keeps the disk clean, it is overly destructive and ruins debuggability.
- **Standard `git checkout`:** Rejected for concurrent agents. Moving the HEAD of the main shared directory corrupts simultaneous test executions for other agents.

## 5. Implementation Constraints & Pitfalls
- **Windows Handle Retention:** The orchestrator **must** retain the `hJob` handle in memory. If Python garbage collects it, the OS silently assassinates the child agent.
- **Environment Injection Routing:** When constructing the subprocess environment (`os.environ`) for an agent in Worktree Mode, developers must explicitly intercept and rewrite the `VIRTUAL_ENV` and `PATH` variables to point to the parent/main repository, otherwise the agent will fail to launch its dependencies.
- **Mutex Deadlocks:** The Global Git Mutex must be rigorously trapped in `try/finally` blocks. An agent crashing mid-fetch without releasing the lock will permanently freeze the rest of the team.

## 6. Negative Consequences
- **Implementation Complexity:** The Process Manager must maintain two entirely separate code paths (Windows APIs vs POSIX APIs), increasing the testing burden.
- **Disk Bloat:** Disabling automatic worktree cleanup will inevitably lead to massive disk usage over time. We accept this trade-off for improved safety and debuggability.
- **Git Mutex Bottleneck:** Serializing global git operations across 5+ active agents may create artificial latency during intense repository syncs.

## 7. References

### 7.1 Local Research & Distilled Docs

- [Process Domain - Distilled](../distilled/2026-25-02-process-distilled.md)
- [Process Gaps Research](../distilled/2026-25-02-process-gaps-research.md)
- [Architecture Domain - Distilled](../distilled/2026-25-02-architecture-distilled.md)
- [Architecture Gaps Research](../distilled/2026-25-02-architecture-gaps-research.md)
- [Agent Process Lifecycle Research](../process/2026-25-02-agent-process-lifecycle-research.md)

### 7.2 Codebase Modules & Patterns

- **Process Spawning:** `subprocess.Popen` (standard library) for initial execution with `creationflags=CREATE_NEW_PROCESS_GROUP` on Windows.
- **Windows Cleanup:** `win32job.CreateJobObject`, `win32job.SetInformationJobObject`, and `win32job.AssignProcessToJobObject` from the `pywin32` library.
- **Unix Cleanup:** `os.setsid` and `signal.SIGTERM` (standard library) for process group management.
- **Async Process Monitoring:** `asyncio.create_subprocess_exec` and `anyio` (used in `mcp-python-sdk/src/mcp/server/stdio.py`) for non-blocking I/O.
- **Process Hierarchy:** `psutil.Process(pid).children(recursive=True)` for cross-platform process tree auditing.
- **Workspace Isolation:** `git worktree add`, `git worktree remove`, and `git worktree prune` CLI commands.
- **Concurrency Control:** `asyncio.Lock` for the Global Git Mutex.
- **Port Allocation:** Native `socket` library bind-to-zero pattern for dynamic port discovery.

### 7.3 Online Reference Implementation

- **PM2 Restart Strategy:** [PM2 Process State Machine](https://pm2.io/docs/runtime/guide/process-management/) (referenced for stability threshold).
- **Supervisord Lifecycle:** [Supervisord Process States](http://supervisord.org/subprocess.html#process-states) (referenced for STARTING -> RUNNING transitions).
- **Anyio TaskGroups:** [Anyio Structured Concurrency](https://anyio.readthedocs.io/en/stable/tasks.html) (referenced for stdout/stderr relay tasks).
