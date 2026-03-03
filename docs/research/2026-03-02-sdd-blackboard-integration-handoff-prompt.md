# Handoff Prompt: VaultSpec SDD Blackboard Integration

**To:** Architecture & Planning Team (e.g., `vaultspec-architect` / `vaultspec-writer`)
**Reference Document:** `[[docs/research/2026-03-02-sdd-blackboard-architecture-research.md]]`
**Feature Tag:** `#sdd-blackboard-integration`

## Objective
Develop a comprehensive technical implementation plan to bridge the gap between our current A2A LangGraph orchestration engine (`lib/core/graph.py`, `lib/core/state.py`) and the `.vaultspec` file-system-as-a-blackboard mandates.

## The Problem
Our current A2A implementation operates as a "chat router" rather than a "State Machine," leading to critical enrichment gaps:
1. **State Disconnect:** The LangGraph `TeamState` relies on in-memory message histories and plan dictionaries, completely ignoring the physical `.vault/` artifacts and the central **Feature Tag** (e.g., `#{feature}`) that binds the VaultSpec system together.
2. **Context Dilution:** Worker nodes concatenate entire message histories into the LLM context. This buries the architectural ground truth (ADRs, Plans) under conversational noise, increasing the risk of sycophancy and logic loops.
3. **Contextual Anchoring:** Supervisors route based on chat history rather than proactively anchoring the team to the active feature's existing `.vault/` documentation.
4. **Task Tracking:** We lack a formalized, persistent task queue schema. The system currently relies on agents implicitly tracking their place in unstructured markdown lists, blurring the line between a logical "Task" and a physical "Execution Step."

## The Mandate
Review the referenced research document and draft a detailed execution plan following the standard `.vault/plan/yyyy-mm-dd-{feature}-{phase}-plan.md` template. Your plan must outline the technical implementation for the following areas:

1. **TeamState Enrichment:** Define how `lib/core/state.py` will be expanded to track the `active_feature` tag, `pipeline_phase`, and a `vault_index` (mapping wikilinks to physical file paths).
2. **Blackboard Context Mounting:** Specify the logic for `lib/core/nodes/worker.py` to automatically resolve the `active_feature`, scan `.vault/` for relevant grounding documents (Research, ADRs, Plans), and inject them as high-priority, read-only System Messages while aggressively compacting the raw chat history.
3. **Persistent Task Queue Schema:** Propose a concrete tracking mechanism using feature-derived sequential task tags (e.g., `SBI-001`, `SBI-002`) and define how this queue will be persisted to disk so the orchestrator can reliably track state across session restarts.
4. **Contextual Anchoring:** Outline how the engine will ensure that every agent invocation is explicitly anchored to the established architectural truth of the feature.

## Expected Output
A structured implementation plan (`#plan`, `#sdd-blackboard-integration`) broken down into numbered execution phases and discrete, sequential tasks ready for the implementation team.