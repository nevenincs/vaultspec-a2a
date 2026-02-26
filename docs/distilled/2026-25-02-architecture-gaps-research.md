---
name: "Architecture Gaps Research"
date: 2026-25-02
type: research
summary: "Rigorous technical specifications for Git worktree-based agent isolation and LangGraph state checkpointer patterns for LLM context management."
maturity: 70
---

# Architecture Gaps Research

**Date**: 2026-02-25
**Domain**: System Architecture

## 1. LLM Integration Layer: Context Management (Gap G9)

**Architectural Problem**: A team of coding agents discussing a project and reading files will rapidly exceed maximum context windows (e.g., 200k tokens). If an agent attempts to pass its entire thought history to the next agent (Planner -> Coder), the API will reject the payload.

**Inclusion/Exclusion Decision**:

- **Excluded**: "Sliding Window" truncation (dropping the oldest 10 messages). This causes fatal "amnesia" where the Coder forgets the core requirements defined by the Planner at the start of the session.
- **Included**: **State Checkpointing (LangGraph Pattern)**.

**Rationale**:
The orchestrator must decouple the *Conversation History* from the *Architectural State*. We adopt the state-graph pattern. The Orchestrator maintains a `TypedDict` representing the compiled state (e.g., `current_plan`, `files_to_edit`, `approved_code`).

When transferring control from the Planner to the Coder, the Orchestrator does *not* send the Planner's 50-turn internal deliberation. It only sends the finalized `State` object via the A2A `ContextId`.

**Implementation Reference (Concept)**:

```python
class TeamState(TypedDict):
    objective: str
    architectural_plan: List[str]
    modified_files: dict[str, str]

# The orchestrator compiles the state and starts the Coder with a clean context
# initialized ONLY with the explicitly required state, resetting token usage to ~1k.
coder_initial_prompt = format_state_for_prompt(team_state)
```

## 2. Git Worktree Merge Strategy (Gap G10)

**Architectural Problem**: Concurrent agents modifying the same repository will corrupt the `.git/index` if they share a working directory.

**Inclusion/Exclusion Decision**:

- **Excluded**: Standard `git branch` and `git checkout`. If the Orchestrator (on `main`) runs a test while an agent is checked out on `branch_a`, the orchestrator tests the wrong code.
- **Included**: **Isolated Git Worktrees**.

**Rationale**:
Worktrees allow multiple branches to be checked out simultaneously in entirely separate physical directories on the disk. They share the same `.git` database but have independent staging areas (`index.lock`).

**CRITICAL CONSTRAINT (Concurrency)**:
While local operations (`add`, `commit`) are safe because they use isolated indices, all worktrees share the global `.git/objects` and `.git/refs` databases. The Orchestrator MUST implement an `asyncio.Lock()` (Global Git Mutex) to serialize any repository-wide operations (`git fetch`, `git push`, `git gc`). Allowing concurrent agents to fetch simultaneously will corrupt the repository.

**Implementation Reference (Workspace Manager)**:
The `WorkspaceManager` class must execute exact shell commands to enforce isolation and cleanup.

1. **Provisioning**:

```powershell
# Create a physically separate folder linked to a new isolated branch
git worktree add ../.worktrees/agent-coder-123 -b agent/coder/123
```

1. **Merge Strategy (Sequential Fast-Forward/Rebase)**:
Once the Reviewer Agent signs off, the Orchestrator executes a rebase to keep history linear, rather than generating messy merge commits.

```powershell
cd /main/repo
git merge --ff-only agent/coder/123
# If ff fails due to concurrency, execute rebase:
# cd ../.worktrees/agent-coder-123 && git rebase main
```

1. **Cleanup Policy (Mandatory)**:
To prevent disk exhaustion on agent failure, the `ProcessManager` must trap `finally` blocks and execute:

```powershell
git worktree remove --force ../.worktrees/agent-coder-123
git branch -D agent/coder/123
```
