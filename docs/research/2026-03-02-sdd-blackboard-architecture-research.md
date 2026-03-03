---
title: "Architectural Overview: Implementing VaultSpec SDD in A2A"
date: 2026-03-02
type: research
feature: sdd-blackboard-architecture
description: "Architectural overview of integrating VaultSpec's file-system-as-a-blackboard SDD mandates with the A2A LangGraph orchestration engine."
source: "VaultSpec Mandates (.vaultspec/*) / A2A Implementation"
relevance: 10
---

# Architectural Overview: Implementing VaultSpec SDD in A2A

**Date:** 2026-03-02

The core premise of the `.vaultspec` architecture is the **File-System-as-a-Blackboard**. It uses a rigid, auditable pipeline (`Research → Specify → Plan → Execute → Verify`) where the "State" is not a transient chat history, but a persistent network of markdown artifacts stored in `.vault/`, linked via `[[wikilinks]]`.

Our current A2A implementation (`lib/core/state.py` and `lib/core/graph.py`) provides the mechanical engine (LangGraph), but it currently lacks the semantic awareness of this file-based blackboard.

## 1. The Enrichment Gaps

### A. State Definition Gap: In-Memory vs. File-System
*   **Current State:** `TeamState` defines `artifacts` and `current_plan` as in-memory JSON dictionaries. It passes the raw `messages` history to the LLM context (`worker.py`).
*   **VaultSpec Mandate:** Artifacts are physical files with strict YAML frontmatter (`tags: ["#adr", "#{feature}"]`) and `related:` wikilinks.
*   **The Feature-Tag Pivot:** In the VaultSpec system, the **Feature Tag** (e.g., `#editor-demo`) is the **central glue** that binds the entire architecture together. The pipeline (`Research → Specify → Plan → Execute → Verify`) is triggered *per feature*, not globally. The feature tag groups all related documents across the lifecycle, forming an isolated, feature-specific Blackboard.
*   **The Gap:** The LangGraph state is disconnected from the physical file system and unaware of this feature-centric grouping. If an agent writes an ADR to `.vault/adr/`, the A2A `TeamState` doesn't automatically know it exists, validate its structure, or associate it with a specific feature pipeline.
*   **Implementation Need:** The `TeamState` should act as an *index* or *pointer* to the file system. Instead of storing the full plan text in memory, the state should track the active `feature_tag` and current `pipeline_phase`, using the tag to load the correct context partition.

### B. Context Dilution Gap: Message History vs. Grounding Documents
*   **Current State:** `create_worker_node` concatenates the `system_prompt` with the entire `messages` array. This is the exact cause of "Context Dilution" identified in the research.
*   **VaultSpec Mandate:** The `vaultspec-standard-executor` persona explicitly commands the agent to *"CONSULT CONTEXT: `<ADR>`, `<Research>`, and `<Reference>` documents are your PRIMARY technical references."*
*   **The Gap:** We are forcing the agent to waste tokens reading "chat chatter" instead of injecting the high-signal SDD documents.
*   **Implementation Need:** **"Context Engineering 2.0"**. Before invoking the LLM, the `WorkerNode` should resolve the current task's wikilinks, read the physical `.vault/` files (e.g., the ADR and the Plan), and inject them directly into the context window as read-only grounding blocks, while aggressively compacting the chat history.

### C. Orchestration Gap: Free-form Routing vs. Pipeline Awareness
*   **Current State:** The `supervisor` node uses an LLM to guess "who acts next" based on the chat text without contextual awareness of the feature's lifecycle state.
*   **VaultSpec Mandate:** While the *user* ultimately manages the workflow and decides whether a request warrants the full pipeline (`Research → ADR → Plan → Execute`) or a direct trivial fix, the agents must always operate with the awareness that this pipeline exists. They operate in a strictly **per-feature context** and must be anchored to whatever binding documentation exists.
*   **The Gap:** The current LangGraph implementation treats every session as a blank slate. The supervisor routes based on conversational history rather than proactively seeking out the anchoring documents (like an existing ADR or Plan) that define the feature's current state.
*   **Implementation Need:** The orchestration engine does not need to rigidly lock or gate every pipeline phase (as the user dictates the workflow context), but it *must* enforce **Contextual Anchoring**. Before making routing decisions or executing tasks, the state machine must inject the supervisor and worker nodes with awareness of the active `feature-tag` and the current inventory of binding `.vault/` documents for that feature. This ensures the team always acts based on the established architectural ground truth rather than an empty chat window.

### D. Task Tracking Gap: Implicit Queues vs. Explicit Task State
*   **Current State:** The VaultSpec system defines `Plan` artifacts containing nested bullet points for phases and steps. It relies on the implicit assumption that the agent (or the human) manually tracks which task is currently active or completed by reading and editing the plan document.
*   **The Gap:** There is no formalized "Task Queue" document or schema. The system lacks:
    *   **Defined Task Naming Schema:** No standardized way to uniquely identify a task across the system.
    *   **Task vs. Execution Step Stress:** The boundary between a "Task" (a logical unit of work) and an "Execution Step" (the physical `.vault/exec/...-step.md` artifact) is blurry because tasks are not rigorously defined entities.
    *   **Annotation Definition:** There is no proper definition of how tasks are annotated or tracked for progress within the broader A2A state machine.
*   **Implementation Need:** We must introduce a rigorous, feature-derived, sequential task tracking mechanism. The A2A orchestration engine cannot rely on an agent "remembering" its place in a markdown list. 
    *   **Proposed Schema:** Introduce feature-derived task tags (e.g., for feature `#add-window-properties`, tasks become `AWP-001`, `AWP-002`, etc.).
    *   **Persistence Strategy:** The Task Queue must not be purely in-memory. It should be a dedicated state document (e.g., `.vault/plan/yyyy-mm-dd-{feature}-queue.md` or embedded structurally in the Plan) that the Orchestrator uses to track state. The `TeamState` will read this physical queue to determine the next task, ensuring execution is robust against session restarts and context flushes.

To align the A2A engine with the `.vaultspec` rules and mitigate context loss, we need to modify the LangGraph implementation as follows:

### Step 1: Enrich `TeamState` with the VaultSpec Schema
Expand `lib/core/state.py` to track the SDD context natively:

```python
class TeamState(TypedDict):
    # ... existing fields ...
    
    # SDD specific state
    active_feature: NotRequired[str]     # e.g., "editor-demo"
    pipeline_phase: NotRequired[str]     # "research", "specify", "plan", "execute", "verify"
    vault_index: dict[str, str]          # Mapping of wikilink -> physical file path
    validation_errors: list[str]         # Populated if an agent writes a malformed artifact
```

### Step 2: Implement "Blackboard Context Mounting"
Modify `lib/core/nodes/worker.py`. Instead of just passing `state["messages"]`, we implement a context-mounting step:

1.  Look at `state["active_feature"]`.
2.  Scan `.vault/` for the relevant `Research`, `ADR`, and `Plan` files.
3.  Inject these files as a high-priority `SystemMessage` block at the *bottom* of the context window (closest to the current prompt) so the agent is strictly grounded in the architectural decisions, not the chat history.

### Step 3: Implement the "Verifier" Loop Guard
The VaultSpec mandate states: *"DO NOT mark the task as complete until the review passes."*

We need to add a specialized node (or modify the `_loop_router` in `lib/core/graph.py`) that acts as the **Blind Critic**. 
*   When the `executor` attempts to return `FINISH`, the graph intercepts it.
*   It routes to the `vaultspec-code-reviewer` agent.
*   If the reviewer finds safety/intent violations (checked against the mounted ADR), it writes an audit artifact to `.vault/audit/` and forces the state back to the `executor`, incrementing the `loop_count`.

## Summary
The companion repo's `.vaultspec` rules are a perfect implementation of the **Blackboard Pattern**. To make the A2A codebase fully utilize it, we must move away from treating LangGraph as a "chat router" and instead treat it as a **File-System State Machine**. The `TeamState` should govern *which* `.vault/` documents are injected into the context, and graph transitions should be gated by the successful creation of the structured markdown artifacts.