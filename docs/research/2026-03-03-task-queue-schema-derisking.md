---
title: 'Derisking: Persistent Task Queue Schema'
date: 2026-03-03
type: research
feature: sdd-blackboard-integration
description: 'Implementation risk analysis for feature-derived sequential task IDs and a queue persisted to disk.'
---

## Derisking: Persistent Task Queue Schema

**Date:** 2026-03-03

## Summary

The planned task queue feature introduces feature-derived sequential task IDs
(e.g., `SBI-001`, `SBI-002`) stored to disk as a persistent queue. This document
surfaces key risks from prior art before an ADR is written.

## 1. Sequential Task ID Schemes in Production Systems

**MetaGPT (arXiv 2308.00352):** Uses role-scoped sequential identifiers. Each task is
assigned to exactly one role at creation time and carries a status field (`TODO`,
`IN_PROGRESS`, `DONE`). Tasks are stored in a shared `Environment` object (their
blackboard equivalent) and serialized to disk as JSON on each state transition.
**Key lesson:** MetaGPT never asks the LLM to update the task list in-place. The
orchestrator's Python code owns all mutations; the LLM only reads the queue and
emits a task ID in its output.

**SWE-agent:** Uses a flat list with a current-task pointer. The agent does not maintain
sequential IDs at all — it receives one task at a time and the harness advances the
pointer. **Key lesson:** the LLM does not need to see the full queue. Injecting only
the current task plus the next 1–2 pending tasks reduces hallucination risk around
"which task am I on."

**LangChain Deep Agents (2025):** The `write_todos` harness tool provides
`pending / in_progress / completed` statuses persisted in agent state. Summarization
fires at 85% of max input tokens and preserves a structured summary including
"artifacts created" and "next steps" — effectively a task snapshot used as a
summarization anchor. **Key lesson:** treat the queue document as a summarization
anchor, not as LLM-editable structured data.

## 2. Session Restart Persistence

**Risk:** A queue stored only in `TeamState` is lost when a new thread is created for
the same feature, or when the checkpointer is cleared.

**Recommended pattern:** The queue lives on disk at
`.vault/plan/{feature}-queue.md`. At graph compilation,
`_build_initial_vault_index` (ADR-019) already discovers `.vault/plan/` documents —
the queue file appears in `vault_index["plan"]` automatically with no additional
scanning logic. On session start, the mount step reads and injects the queue.
`TeamState` carries only a `current_task_id: NotRequired[str | None]` pointer, not
the full queue content.

This aligns with the LangGraph guidance on `BaseStore` vs state: cross-session
persistent data belongs on disk or in a store, not in per-thread checkpointed state.

## 3. Queue Document Format

**Risk:** LLM agents reliably corrupt structured formats when asked to edit them
in-place. YAML frontmatter suffers from hallucinated indentation, missing colons, and
duplicate keys. JSON inside markdown is worse — models introduce trailing commas,
unquoted keys, and comment syntax.

### Recommended mitigation — machine-writes, LLM-reads only

The queue file is written exclusively by Python code. The LLM's only interactions are:

1. Reading the current queue (injected as a `SystemMessage` by the mount step).
2. Emitting a task ID in its response (e.g., `TASK: SBI-003 — complete`).
3. The orchestrator parses the emitted ID, updates the in-memory queue object, and
   re-serializes to disk.

**Format recommendation:** A markdown table is LLM-readable and Python-parseable with
a simple `|`-split, more robust than YAML or JSON under generation pressure:

```markdown
## Task Queue — sdd-blackboard-integration

| ID      | Status      | Title                                 |
| ------- | ----------- | ------------------------------------- |
| SBI-001 | completed   | Add 4 new fields to TeamState         |
| SBI-002 | completed   | Implement \_build_initial_vault_index |
| SBI-003 | in_progress | Implement \_build_anchoring_context   |
| SBI-004 | pending     | Implement mount step node             |
```text

## 4. Key Risks Summary

| Risk                                          | Mitigation                                                                                         |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| LLM edits queue file directly and corrupts it | Queue writes are Python-only; LLM emits task ID only                                               |
| Queue diverges from TeamState across restarts | TeamState carries only `current_task_id`; queue file is ground truth                               |
| ID collisions across features                 | Feature prefix (e.g., `SBI-`) scopes IDs; counter derived from existing file row count at creation |
| Queue file grows unbounded                    | Archive completed tasks to `{feature}-queue-archive.md` after each phase                           |
| LLM loses track of current task mid-session   | Inject only current + next 1–2 pending tasks, not full queue                                       |

## 5. References

- MetaGPT arXiv 2308.00352 §3.3 — role-scoped sequential IDs, Python-owned mutations
- SWE-agent — single-task injection, harness advances pointer
- LangChain Deep Agents `write_todos` — `pending/in_progress/completed` schema, summarization anchor
- LangSmith Agent Server — PostgreSQL + Redis task queue for production persistence reference
- ADR-019 `vault_index` — queue file appears under `vault_index["plan"]` automatically
