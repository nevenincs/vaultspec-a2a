---
adr_id: 001
title: Process & Workspace Management (LangGraph Core)
date: 2026-02-26
status: Proposed
related:
  - docs/distilled/2026-25-02-process-distilled.md
  - docs/research/2026-26-02-langgraph-gap-audit-research.md
---

## ADR-001: Process & Workspace Management (LangGraph Core)

**Date:** 2026-02-26  
**Status:** Proposed

## 1. Context & Problem Statement

The Python Orchestrator must supervise the execution of multiple
independent agent LLM runs and manage their filesystem workspaces. This
presents several challenges:

- **Cross-Platform Process Safety:** Orchestrator must wrangle native CLI
  binaries (Claude/Gemini) as subprocesses. On Windows, provider CLIs are
  distributed as `.cmd` shims wrapping Node.js or native executables.
  `process.terminate()` kills only the immediate shell child, leaving the
  real worker process (node.exe, etc.) as an orphan. The implementation
  must handle full process-tree teardown on each platform.
- **Concurrent Filesystem Access:** Multiple coding agents editing the
  same repository will corrupt the `.git/index` and cross-contaminate
  test runs if they share a single working directory.
- **Environment Resolution (`venv`):** The parent `vaultspec` app
  supports varied repository layouts, dictating entirely different rules
  for where an agent's Python virtual environment (`.venv`) and utility
  files are located.

## 2. The Decision

We have decided on a revised dual-strategy for Process Management and
Workspace Isolation:

### Process Management (Native LangGraph)

- **Managed CLI Subprocesses via `AcpChatModel`:** LLM provider CLIs
  (Claude, Gemini) are executed as tightly managed child processes
  **inside** `AcpChatModel` — a custom `BaseChatModel` wrapper. These
  are **not** orchestration-level ephemeral processes; they are
  long-lived stdio pipes owned by the wrapper. The orchestration
  topology (graph routing, state transitions, tool dispatch) remains
  entirely native Python. What is banned is the old pattern of spawning
  independent agent processes that manage their own lifecycles outside
  LangGraph's supervision.
- **Platform-Specific Subprocess Spawning:** Provider CLIs on Windows are
  distributed as `.cmd` shims (node-based for Claude, native for Gemini)
  that require a shell to execute. Spawning strategy differs by platform:
  - **Windows:** `asyncio.create_subprocess_shell` with
    `creationflags=CREATE_NEW_PROCESS_GROUP`. The process group flag
    isolates console-signal handling (Ctrl+C cannot propagate from parent
    terminal into the subprocess group) and enables reliable process-tree
    teardown. `subprocess.list2cmdline` escapes command arguments for
    cmd.exe to prevent metacharacter injection.
  - **Unix/Linux/macOS:** `asyncio.create_subprocess_exec` — no shell
    intermediary. POSIX signals deliver directly to the target process.
  - **PTY and bare `cmd.exe /c` wrappers are forbidden** on all
    platforms. PTY breaks pipe semantics; a bare `cmd.exe /c` wrapper
    (without `CREATE_NEW_PROCESS_GROUP`) prevents reliable cleanup.
- **Crash Isolation via AsyncIO:** Because graph nodes are native async
  tasks running in the Uvicorn event loop, crash isolation is handled
  via standard Python `try/except` and `asyncio.TaskGroup` semantics.
  A failing `AcpChatModel` call (subprocess crash, pipe EOF) will not
  corrupt the memory space of other running agents.

### Workspace Isolation

- **Dual-Mode Workspace Support:**
  - **Flat Hierarchy Mode:** The agent operates directly within the
    standard repository root. Python `.venv` and utility files are
    resolved locally within the current directory.
  - **Worktree Mode:** The agent operates within an isolated `git
worktree` (e.g., `agent/coder/123`). Because worktrees are sparse
    checkouts, the orchestrator must resolve `.venv` and utility files
    to either the **container folder** (parent of the worktrees) or the
    **main repository root**.
- **Manual Worktree Cleanup:** Worktree deletion functionality will be
  implemented but **will not be automatic**. Automatic cleanup is deemed
  too dangerous. We possess sufficient disk space to retain artifacts
  post-failure/completion for forensic review.
- **Global Git Mutex:** A single `asyncio.Lock()` will serialize
  destructive, repository-wide operations (like `git fetch` or
  `git gc`) across all concurrent agents, preventing `.git` database
  corruption.

## 3. Rationale

- **No Automatic Cleanup:** Blindly destroying worktrees after an agent
  crashes destroys vital context needed for debugging LLM hallucinations
  or system failures. Preserving the filesystem state is safer and more
  valuable than recovering disk space.
- **Dual-Mode Environments:** The parent `vaultspec` ecosystem inherently
  uses both flat and worktree configurations. Hardcoding the expectation
  that `.venv` is always locally available inside an agent's current
  working directory will instantly break worktree compatibility.

## 4. Rejected Alternatives

- **Orchestration-Level Subprocess Management (Original Design):**
  Rejected. Spawning independent agent processes with their own
  lifecycles, using `pywin32` Job Objects and `CTRL_BREAK_EVENT`
  signals, was overly complex and unreliable. `AcpChatModel` supersedes
  this by owning CLI subprocesses as private, scoped stdio pipes — not
  as independent orchestration actors.
- **Bare `cmd.exe /c` / PTY invocation:** Rejected. Wrapping CLI binaries
  via a PTY destroys pipe semantics. Invoking `cmd.exe /c` manually
  (without `CREATE_NEW_PROCESS_GROUP`) is also rejected because
  `process.terminate()` kills only cmd.exe, orphaning node.exe. The
  accepted pattern is `create_subprocess_shell` with
  `CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F` cleanup on Windows.
- **Windows Job Objects (pywin32):** Evaluated and rejected as the primary
  cleanup mechanism. `pywin32` compatibility with Python 3.13 is
  unverified, and `taskkill /T /F` achieves the same outcome (full process
  tree termination) using only builtins. Job Objects remain a viable
  fallback if `taskkill` proves insufficient in future scenarios.
- **Automated Worktree Teardown:** Rejected. While it keeps the disk
  clean, it is overly destructive and ruins debuggability.
- **Standard `git checkout`:** Rejected for concurrent agents. Moving
  the HEAD of the main shared directory corrupts simultaneous test
  executions for other agents.

## 5. Implementation Constraints & Pitfalls

- **Async Tool Execution:** Because graph nodes run natively in the
  Uvicorn thread, all tools _must_ be strictly asynchronous
  (`async def`). A synchronous library call inside a LangChain tool
  will block the entire host webserver.
- **`AcpChatModel` Subprocess Hygiene:** The CLI subprocess spawned inside
  `AcpChatModel` must have its `stdin`/`stdout` piped and `stderr`
  captured separately. Mixing stderr into stdout corrupts JSON-RPC
  framing. **Process teardown must use `_kill_process_tree`:**
  - **Windows:** `taskkill /T /F /PID {pid}` kills the entire tree
    (cmd.exe + node.exe + grandchildren). Never use `process.terminate()`
    alone on Windows — it kills only cmd.exe and orphans node.exe.
  - **Unix:** `process.terminate()` (SIGTERM) with 5-second escalation to
    `process.kill()` (SIGKILL).
  - `CTRL_BREAK_EVENT` is never used — it applies only to Uvicorn-style
    graceful HTTP shutdown, not ACP stdio subprocesses.
  - Always close the asyncio transport handle after process exit to
    prevent OS handle leaks (cpython#114177).
- **Environment Injection Routing:** When configuring tool environments
  for an agent in Worktree Mode, developers must explicitly rewrite
  `VIRTUAL_ENV` and `PATH` to point to the parent/main repository. For
  `AcpChatModel`, `CLAUDE_CODE_OAUTH_TOKEN` (and equivalent Gemini
  credentials) must be injected into the subprocess `env` dict — never
  logged or forwarded to the frontend.
- **Mutex Deadlocks:** The Global Git Mutex must be rigorously trapped
  in `try/finally` blocks. An agent crashing mid-fetch without
  releasing the lock will permanently freeze the rest of the team.

## 6. Negative Consequences

- **Shared Memory Risks:** Running all agents natively inside the
  Orchestrator's Python process means a catastrophic C-extension
  segfault invoked by a single agent's tool could technically crash the
  entire server (a risk previously mitigated by subprocess isolation).
- **Disk Bloat:** Disabling automatic worktree cleanup will inevitably
  lead to massive disk usage over time. We accept this trade-off for
  improved safety and debuggability.

## 7. References

- [LangGraph Gap Audit Research](../research/2026-02-26-langgraph-gap-audit-research.md)
- [Architecture Domain - Distilled](../research/2026-02-25-architecture-distilled-research.md)
