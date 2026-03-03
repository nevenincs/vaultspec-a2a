---
title: "External Research: SDD Blackboard Integration Patterns"
date: 2026-03-03
type: research
feature: sdd-blackboard-integration
description: "Survey of real-world implementations for file-system-as-blackboard, LangGraph state enrichment, persistent task queues, context grounding, and artifact-store bridges in agentic/LLM systems."
---

# External Research: SDD Blackboard Integration Patterns

**Date:** 2026-03-03
**Feature tag:** `#sdd-blackboard-integration`
**Feeds into:** ADRs 019–022

---

## 1. File-System-as-Blackboard in Agentic / LLM Systems

### 1.1 Academic Blackboard Architecture (2025 Literature)

Two directly relevant papers appeared in 2025:

**[LLM-Based Multi-Agent Blackboard System for Information Discovery in Data Science](https://arxiv.org/abs/2510.01285)**
(arXiv 2510.01285, Oct 2025)

The system implements a three-component blackboard:
1. **Blackboard** — a global, hierarchical data structure divided into public and private spaces. Public space enables all agents to read and write; private spaces support focused sub-team discussions.
2. **Agent Group** — specialized roles (planner, decider, critic, conflict-resolver, cleaner) plus dynamically generated domain experts.
3. **Control Unit** — an LLM-based coordinator that selects which agents should act in each iteration based on the query and current blackboard state.

Coordination is iterative: control unit examines blackboard → selects agents → agents contribute outputs → blackboard updates → next cycle. Stopping condition: decider declares a solution or max iterations reached.

Key result: outperforms master-slave baselines by 13–57% on end-to-end success, 9% gain in data discovery F1.

**Key insight for our use:** The "private spaces for sub-team discussion" maps exactly to our per-feature `vault_index` partitioning. Each feature tag is a private namespace on the blackboard.

**[Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture](https://arxiv.org/abs/2507.01701)**
(arXiv 2507.01701, Jul 2025)

Confirms the same three-component model and adds: agents communicate *exclusively through the blackboard*, eliminating direct agent-to-agent messaging. The blackboard "replaces traditional per-agent memory modules" — consolidation reduces prompt length while maintaining context.

**Pitfall cited:** Dynamic collaboration adjustment based on evolving problem state is difficult to implement without a reliable stopping condition. Without explicit phase gates, the control unit can cycle indefinitely.

**Adoption for us:** Our `pipeline_phase` field in `TeamState` functions as the explicit stopping condition / phase gate that prevents indefinite cycling. The `vault_index` is our blackboard namespace.

---

### 1.2 MetaGPT — Shared Message Pool as File-System Blackboard

**[MetaGPT: Meta Programming for a Multi-Agent Collaborative Framework](https://arxiv.org/html/2308.00352v6)**
GitHub: [FoundationAgents/MetaGPT](https://github.com/FoundationAgents/MetaGPT)

MetaGPT is the most direct real-world precedent for our architecture. It implements a **shared message pool** where agents communicate exclusively through structured documents — not dialogue. The architecture:

- Agents publish structured artifacts to the pool: PRD, System Design, Task List, Test Cases.
- Agents subscribe to the pool based on role — engineers only activate after receiving architect outputs.
- Sequential dependency: each document type gates the next pipeline stage.
- Physical persistence: artifacts are written to a `workspace/` directory. A `FileRepository` (later consolidated with `GitRepo`) tracks all generated files.

**Document schema used by MetaGPT:**
- PRD: user stories, requirement pools, competitive analysis
- System Design: file lists, data structures, interface definitions, sequence diagrams
- Task List: breaking down system design into engineer assignments
- Each document is structured markdown with defined sections, not free-form chat.

**Pitfalls MetaGPT encountered:**
- Information overload: despite subscription filtering, agents still received more context than needed.
- Hallucination during review: LLMs overlooked errors without executable verification. Required runtime code testing as a quality gate (analogous to our `validation_errors` accumulator).
- Context efficiency: long document chains caused prompt bloat, requiring compression strategies.

**What we adopt:**
- Document-as-communication pattern: `.vault/` artifacts are our message pool. Agents communicate through structured markdown, not conversation.
- Role-based subscription: our `vault_index` with doc-type priority ordering (ADR > plan > research) mirrors MetaGPT's subscription model — each agent receives only the tier relevant to its role.
- `validation_errors` in `TeamState` mirrors MetaGPT's runtime testing quality gate.

**What we improve on:**
- MetaGPT's `FileRepository` is a passive store. Our `vault_index` in `TeamState` is an active index that nodes can query without rescanning disk.
- MetaGPT uses a fixed pipeline (Product Manager → Architect → Engineer → QA). Our LangGraph implementation supports dynamic `star` topology while still enforcing phase-aware anchoring.

---

### 1.3 "Codified Context" Infrastructure (arXiv 2602.20478)

**[Codified Context: Infrastructure for AI Agents in a Complex Codebase](https://arxiv.org/html/2602.20478v1)**

This 2026 paper describes production context infrastructure for a complex codebase with a three-tier model:

- **Tier 1 (Hot Memory):** A single ~660-line "constitution" file auto-loaded into every AI session. Contains conventions, naming standards, orchestration protocols.
- **Tier 2 (Specialists):** 19 domain-expert agent specifications (115–1,233 lines each). Over half of each spec's content is project-domain knowledge, not behavioral instructions.
- **Tier 3 (Cold Memory):** 34 on-demand specification documents (~16,250 lines total). Retrieved via MCP tools: `list_subsystems()`, `get_files_for_subsystem()`, `find_relevant_context()`.

**Document format:** Documents follow a structured format: core mechanisms → correctness requirements (as tables) → known failure modes (symptom → cause → fix). Treated as "load-bearing artifacts that AI agents depend on."

**Trigger tables:** Automatically route tasks to specialized agents based on file patterns being modified. Encodes "which domain expertise each file area requires."

**Pitfall:** Human oversight cannot be delegated — agents lack autonomous judgment for "design decisions, aesthetic evaluation, architecture." Quality gates require human checkpoints.

**What we adopt:**
- The Tier 1/2/3 hot/warm/cold distinction maps to our mounting priority: ADR (hot) > Plan (warm) > Research (cold).
- "Load-bearing artifacts" framing validates our `[BLACKBOARD: ...]` marker in mounted SystemMessages.
- The constitution-file pattern (always-loaded) maps to the ADR-014 context preamble (always present in message history).
- Trigger tables → our `vault_index` doc-type routing: supervisor reads the index to determine phase-appropriate routing.

---

## 2. LangGraph State Enrichment with External File Context

### 2.1 LangGraph Official Reference Pattern

**[LangGraph Persistence Guide](https://fast.io/resources/langgraph-persistence/)** |
**[External Persistent Memory for Agents](https://medium.com/@princekrampah/external-persistent-memory-for-agents-building-robust-applications-with-langgraph-8415b170beef)**

The canonical LangGraph recommendation for file/artifact integration is the **reference pattern**:

> "Store large files in specialized storage and keep only the reference URL or metadata in the LangGraph state."

Example state:
```python
{"file_url": "https://...", "filename": "report.pdf"}
```

The anti-pattern is direct embedding: "If the agent state includes a 50MB PDF and the agent takes 10 steps, the checkpointer writes 500MB of data."

**LangGraph BaseStore:** A cross-thread key-value store (`langchain_ai/data-enrichment` template). Nodes access it via `def node(state: State, store: BaseStore)`. Enables shared memory across thread boundaries without per-checkpoint serialization of large blobs.

**What we adopt:**
- Our `vault_index: dict[str, list[str]]` is the reference pattern applied to `.vault/` documents. We store paths, not content, in `TeamState`. Content is read per-invocation by the mount step (ADR-020).
- The LangGraph BaseStore is relevant for cross-thread vault sharing (future: multiple threads working on the same feature). Not required for v1.

**Pitfall confirmed:** Storing file content directly in `TeamState` would cause checkpoint bloat. The reference pattern (paths in state, content read per-invocation) is the correct LangGraph-idiomatic approach. This validates our ADR-019 `vault_index` design.

---

### 2.2 Google ADK — Artifact Handle Pattern and Context Compilation

**[Context Engineering: Google ADK Architecture](https://raphaelmansuy.github.io/adk_training/blog/2025/12/08/context-engineering-google-adk-architecture/)**

Google ADK implements a tiered context architecture with directly applicable patterns:

**Artifact Handle Pattern:**
- Large files stored in `ArtifactService` (GCS or local filesystem).
- Agents see only lightweight references (name + summary) by default.
- `LoadArtifactsTool` enables on-demand expansion into working context.
- Artifacts are ephemeral in context — loaded for specific reasoning, discarded after.

**Context as a compiled view:**
> "Context is a compiled view over a richer stateful system, rebuilt fresh each invocation."

ADK uses ordered processors (Identity → Instruction → ContextCache → Planning → CodeExecution → AgentTransfer) that each inject appropriate context for their stage.

**`include_contents` pattern:** Sub-agents receive scoped context. Each agent gets only the "mission-critical" context slice. This is implemented via `include_contents` knobs on sub-agent invocations, not via a shared global context.

**Tiered state:**
1. Working Context — immediate prompt, rebuilt each invocation
2. Session — durable chronological event log
3. Memory — long-lived, cross-session searchable knowledge
4. Artifacts — named, versioned, accessed by reference

**What we adopt:**
- The processor pipeline maps exactly to our worker node mount step: the "ContextCache" processor is equivalent to `_mount_blackboard()`.
- "Ephemeral expansion" validates per-invocation content mounting rather than persistent embedding in state.
- The tiered architecture (session/memory/artifacts) validates our three-layer design: preamble (session-level, ADR-014) + vault_index paths in TeamState (memory-level, ADR-019) + per-invocation content mount (artifact expansion, ADR-020).

**Pitfall from ADK:** Narrative reframing is needed during agent handoffs to prevent agents from misattributing prior system actions to themselves. Our `[BLACKBOARD: ...]` marker prefix serves this function — it labels the content origin so agents don't confuse vault documents with their own prior outputs.

---

## 3. Persistent Task Queue Schemas in Multi-Agent Orchestration

### 3.1 CrewAI — Task Output File Persistence

**[CrewAI Tasks Documentation](https://docs.crewai.com/en/concepts/tasks)**

CrewAI's task schema:

| Field | Type | Purpose |
|---|---|---|
| `description` | str | Human-readable task specification |
| `expected_output` | str | Success criteria |
| `agent` | Optional[BaseAgent] | Assigned executor |
| `context` | list[Task] | Explicit upstream dependencies |
| `output_file` | Optional[str] | Path to persist output |
| `async_execution` | bool | Non-blocking execution |
| `output_pydantic` | Optional[Type[BaseModel]] | Structured output schema |

**TaskOutput schema:**

| Field | Purpose |
|---|---|
| `description` | Task identifier (no formal task_id) |
| `raw` | Default string output |
| `pydantic` | Structured model instance |
| `json_dict` | Parsed JSON |
| `agent` | Executing agent name |
| `output_format` | RAW/JSON/Pydantic enum |
| `messages` | Full execution conversation history |

**Inter-task dependency:** Tasks establish dependencies via `context=[other_task]` — CrewAI ensures upstream outputs are available before downstream execution. No sequential ID system.

**Pitfalls from GitHub issues:**
- `output_file` path handling is buggy: path resolution was relative to project root rather than respecting absolute paths (Issue #1707). Fixed but still brittle.
- Pipeline mode assumes JSON output and fails on raw mode (Issue #1258).
- No formal task_id — tasks are identified by `description` string, which is fragile for programmatic state tracking.

**What we adopt:**
- The `context=[task]` dependency model validates our `active_task_id` concept — a task knows what came before it.
- `output_file` pattern validates `.vault/exec/` step file creation.
- **What we improve:** Introduce a formal `task_id` (e.g., `P1-S1`) rather than using description strings, addressing CrewAI's known fragility.

---

### 3.2 MetaGPT — Sequential Document Chain as Task Queue

MetaGPT's `FileRepository` (consolidated with `GitRepo`) acts as an implicit task queue through sequential document dependency:
- PRD must exist → System Design can be produced.
- System Design must exist → Task List can be produced.
- Task List must exist → Engineers can implement.

There is no explicit task queue schema. The "queue" is inferred from which document types are present in the shared repository. An agent's activation condition is whether its required input documents exist in the shared store.

**Pitfall:** No explicit task status tracking. Agents re-read and potentially re-execute if they cannot determine whether a task was already completed. MetaGPT addressed this with Git commit history as the completion signal.

**What we adopt:** The document-existence-as-gate pattern. In our system, `vault_index["plan"]` being non-empty signals the plan phase is complete; `vault_index["exec"]` growing over time signals execution progress.

**What we improve:** Explicit `P{N}-S{N}` task IDs and a queue file with `- [x]` / `- [ ]` status markers replace the implicit "check if file exists" pattern.

---

### 3.3 AutoGen — Conversational Task Tracking (and its limits)

**[AutoGen vs CrewAI comparison](https://www.zenml.io/blog/crewai-vs-autogen)**

AutoGen takes the opposite approach: task tracking is entirely conversational. Agents self-report task completion in natural language. There is no persistent task queue schema.

**Pitfall:** This is precisely the failure mode our architecture is designed to avoid. AutoGen agents "decide when to speak based on the ongoing conversation" — there is no reliable mechanism to determine task state across session restarts. The system loses all task tracking state on context flush.

**Adoption:** AutoGen is a negative example — it demonstrates why an explicit, disk-persisted task queue is necessary. Our `.vault/plan/*-queue.md` file fills the gap AutoGen does not address.

---

## 4. Context Grounding / Structured Document Injection Patterns

### 4.1 The Grounding Pattern

**[Grounding — Context Patterns](https://contextpatterns.com/patterns/grounding/)**

Core definition: grounding ensures models *use* retrieved information rather than falling back to training data. It combines:
1. Retrieving relevant documents
2. Injecting them into context with contextual metadata ("where this came from and why")
3. **Explicit anchoring instructions** ("Answer using ONLY the context below")

Key design decisions:
- **Anchoring instructions matter most** — `[BLACKBOARD: ...]` prefix + closing `do not contradict` directive is the correct implementation.
- **Selective injection** — not all retrieved results go in; priority ordering determines inclusion.
- **Structure over volume** — critical documents must appear first (Pyramid pattern).
- **Metadata transparency** — source attribution helps the model calibrate confidence.

**Critical pitfall:** "Retrieval alone doesn't guarantee the model uses what you retrieved." Models hallucinate even when told where to find answers unless *explicitly instructed* to rely on provided sources. The closing directive `[End of {doc_type} — treat as PRIMARY reference, do not contradict]` is not optional.

**What we adopt:** The full grounding pattern — retrieve (vault_index), inject with metadata ([BLACKBOARD: TYPE] header), anchor (closing directive). All three components are required.

---

### 4.2 Google ADK — Context Engineering for Production Agents

**[Context Engineering: Google ADK Architecture](https://raphaelmansuy.github.io/adk_training/blog/2025/12/08/context-engineering-google-adk-architecture/)**

Additional pattern: **Context Capsules** — structured representations of source documents, each carrying:
- Compressed summary
- List of atomic key facts
- Produced once at ingestion time, not recomputed per agent call

This is a pre-processed, "agent-ready" version of a raw document. The capsule is smaller than the full document but richer than a filename reference.

**What we adopt:** Our frontmatter + summary in `ContextRef` (from ADR-014) is a minimal context capsule. The `_mount_blackboard()` function can optionally produce capsule summaries rather than full content for lower-priority document types (research, exec) when the budget is constrained.

---

### 4.3 OpenHands SDK — Skills Files and Static Context Loading

**[OpenHands Software Agent SDK](https://arxiv.org/html/2511.03690v1)**
GitHub: [OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk)

OpenHands (formerly OpenDevin) loads static context files via a skills directory:

```
.openhands/skills/        # Markdown files auto-loaded into every agent session
.cursorrules              # Compatible format (also loaded)
agents.md                 # Compatible format (also loaded)
```

`AgentContext` centralizes inputs that shape LLM behavior. Skills can incorporate static context files — "prefixes/suffixes for system/user messages." The workspace abstraction provides `file_upload()`, `file_download()`, and command execution with an append-only EventLog tracking all operations.

**Key architectural decision:** Immutability + event sourcing. All components (agents, tools, LLMs) are immutable. A single `ConversationState` object records all mutable context as an append-only event log.

**What we adopt:**
- `.openhands/skills/` maps to our `.vaultspec/agents/` TOML files — workspace-local overrides for agent behavior, loaded at compile time.
- The append-only event log validates our `artifacts` reducer in `TeamState` (append-only, deduplicated by id) as the correct persistence strategy for completed work records.
- Immutable agent config + mutable state separation is exactly our architecture: `AgentConfig` (immutable TOML) + `TeamState` (mutable, checkpointed).

**Pitfall from OpenHands:** Checkpoints need to capture conversation context, tool outputs, and intermediate states that traditional version control doesn't track. Their solution (event-sourced state) is equivalent to our LangGraph SQLite checkpointer.

---

## 5. LangGraph + File-Based Artifact Store Bridges

### 5.1 No Direct Open-Source Precedent

A targeted search for open-source LangGraph projects that specifically bridge LangGraph's state machine to a file-based artifact repository (analogous to our `.vault/` integration) found no direct match. The closest pattern is the LangGraph BaseStore + reference-in-state approach (§2.1 above).

The absence of a direct precedent means our implementation is genuinely novel in the LangGraph ecosystem. This makes the ADRs more important — they establish the canonical pattern for this class of integration.

### 5.2 LangGraph `data-enrichment` Template

**[langchain-ai/data-enrichment](https://github.com/langchain-ai/data-enrichment)**

The official LangGraph data enrichment template uses an agent that:
1. Maintains a structured state with a `schema` field (the target data schema to fill).
2. Does web research to populate schema fields.
3. Uses a `BaseStore` for cross-invocation memory.

The pattern: **state-as-schema + store-as-knowledge-base + agent-as-filler**. The agent's job is to fill in structured fields by gathering information.

**What we adopt:** The state-as-schema pattern validates our `vault_index: dict[str, list[str]]` — the index is the schema of what the blackboard contains, and agents fill it in as they produce artifacts. The `_merge_vault_index` reducer (append, deduplicate) mirrors how new research fills in schema fields.

---

## 6. Summary Table: Pattern → Our Implementation

| Pattern | Source | Implementation in our system |
|---|---|---|
| Public blackboard namespace | arXiv 2507.01701 | `vault_index: dict[str, list[str]]` partitioned by doc-type |
| Phase gate / stopping condition | arXiv 2507.01701 | `pipeline_phase` field in `TeamState` |
| Document-as-communication | MetaGPT | `.vault/` markdown artifacts as agent outputs |
| Role-based subscription | MetaGPT | Mounting priority: ADR > plan > research > exec > audit |
| Reference-in-state, content-on-demand | LangGraph canonical | `vault_index` stores paths; `_mount_blackboard()` reads content per-invocation |
| Artifact handle pattern | Google ADK | Same — lightweight refs in state, ephemeral content expansion at invocation |
| Tiered context (hot/warm/cold) | arXiv 2602.20478 | ADR (hot, always mount) > Plan (warm) > Research (cold, budget-dependent) |
| Compiled context per invocation | Google ADK | `_mount_blackboard()` rebuilds grounding context fresh each worker call |
| Explicit anchoring directives | contextpatterns.com | `[BLACKBOARD: TYPE]` header + `[do not contradict]` closing in SystemMessage |
| Sequential doc chain as task queue | MetaGPT | `vault_index` presence gates: plan non-empty → plan phase done |
| Formal task_id (not description string) | Improves on CrewAI | `P{N}-S{N}` task IDs in `.vault/plan/*-queue.md` |
| Disk-persisted task state | Improves on AutoGen | `.vault/plan/*-queue.md` with `- [x]` / `- [ ]` status |
| Append-only artifact log | OpenHands EventLog | `artifacts` reducer in `TeamState` (append-only, deduped by id) |
| Immutable config + mutable state | OpenHands | `AgentConfig` TOML (immutable) + `TeamState` (mutable, SQLite checkpointed) |
| Validation / quality gate | MetaGPT runtime testing | `validation_errors` accumulator in `TeamState`; supervisor inspects before routing |
| Context capsule (summary + facts) | Google ADK | `ContextRef.summary` field; optional capsule mode for low-priority docs |

---

## 7. Key Pitfalls to Avoid (from Real-World Implementations)

1. **Direct content embedding in state** (LangGraph canonical anti-pattern): Storing document content in `TeamState` causes checkpoint bloat. Always store paths; read content per-invocation.

2. **No explicit stopping condition** (arXiv 2507.01701): Blackboard systems cycle indefinitely without a phase gate. `pipeline_phase` and `max_loops` are both required.

3. **Retrieval without anchoring directives** (contextpatterns.com): Injecting documents does not guarantee the model uses them. Explicit `[PRIMARY reference, do not contradict]` directives are mandatory.

4. **Path handling fragility in output_file** (CrewAI Issue #1707): File paths must be resolved to absolute paths before writing. The `.vault/` write step must use `workspace_root / rel_path` resolution, not relative paths.

5. **Task identity by description string** (CrewAI): Fragile for programmatic state tracking. Use structured `P{N}-S{N}` IDs.

6. **Implicit task completion via file existence** (MetaGPT): Checking "does the file exist?" is not sufficient. Agents may produce malformed artifacts. Frontmatter validation + `validation_errors` accumulation is required.

7. **Context window pollution from full execution history** (MetaGPT, AutoGen): Agents receive all prior outputs regardless of relevance. The mounting priority order (ADR > plan > research > exec) combined with the 30% token budget cap prevents context explosion.

8. **Agent self-misattribution on handoff** (Google ADK): Without source markers, agents confuse blackboard content with their own prior outputs. The `[BLACKBOARD: TYPE]` prefix prevents this.

---

## Sources

- [LLM-Based Multi-Agent Blackboard System (arXiv 2510.01285)](https://arxiv.org/abs/2510.01285)
- [Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture (arXiv 2507.01701)](https://arxiv.org/abs/2507.01701)
- [LLM-Based Multi-Agent Blackboard System — OpenReview](https://openreview.net/forum?id=egTQgf89Lm)
- [Collaborative Problem-Solving with Blackboard Architecture — Engineering Notes](https://notes.muthu.co/2025/10/collaborative-problem-solving-in-multi-agent-systems-with-the-blackboard-architecture/)
- [MetaGPT: Meta Programming for a Multi-Agent Collaborative Framework (arXiv 2308.00352)](https://arxiv.org/html/2308.00352v6)
- [FoundationAgents/MetaGPT — GitHub](https://github.com/FoundationAgents/MetaGPT)
- [Codified Context: Infrastructure for AI Agents in a Complex Codebase (arXiv 2602.20478)](https://arxiv.org/html/2602.20478v1)
- [LangGraph Persistence Guide — Fast.io](https://fast.io/resources/langgraph-persistence/)
- [External Persistent Memory for Agents with LangGraph — Medium](https://medium.com/@princekrampah/external-persistent-memory-for-agents-building-robust-applications-with-langgraph-8415b170beef)
- [langchain-ai/data-enrichment — GitHub](https://github.com/langchain-ai/data-enrichment)
- [Context Engineering: Google ADK Architecture](https://raphaelmansuy.github.io/adk_training/blog/2025/12/08/context-engineering-google-adk-architecture/)
- [Architecting Efficient Context-Aware Multi-Agent Framework — Google Developers Blog](https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/)
- [Grounding — Context Patterns](https://contextpatterns.com/patterns/grounding/)
- [CrewAI Tasks Documentation](https://docs.crewai.com/en/concepts/tasks)
- [CrewAI Issue #1707 — output_file path handling](https://github.com/crewAIInc/crewAI/issues/1707)
- [The OpenHands Software Agent SDK (arXiv 2511.03690)](https://arxiv.org/html/2511.03690v1)
- [OpenHands/software-agent-sdk — GitHub](https://github.com/OpenHands/software-agent-sdk)
- [Building an ADR Writer Agent — Medium](https://piethein.medium.com/building-an-architecture-decision-record-writer-agent-a74f8f739271)
- [Context Engineering for Multi-Agent Systems — Kudra.ai](https://kudra.ai/context-engineering-for-multi-agent-systems/)
- [Memory in LLM-based Multi-agent Systems Survey — TechRxiv](https://www.techrxiv.org/users/1007269/articles/1367390)
