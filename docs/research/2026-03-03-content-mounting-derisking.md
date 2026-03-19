---
title: 'Derisking: Blackboard Content Mounting'
date: 2026-03-03
type: research
feature: sdd-blackboard-integration
description: 'Implementation risk analysis for reading .vault/ file content and injecting it into worker context per-invocation.'
---

## Derisking: Blackboard Content Mounting

**Date:** 2026-03-03

## Summary

The planned content mounting feature reads actual `.vault/` document content and
injects it into the worker context window per-invocation. This document identifies
the key risks and recommended LangGraph patterns before an ADR is written.

## 1. Token Budget

**Risk:** Uncapped document injection overflows model context windows. A single ADR
is typically 2,000–8,000 tokens; a research document can exceed 15,000. Injecting
3–4 documents without a ceiling easily exhausts the practical input budget shared
with history, system prompts, and output generation headroom.

**Recommended ceiling:** Reserve a fixed block for mounted content — 20,000 tokens is
a defensible default for models with 100k+ context windows. This leaves budget for
the system prompt (~2,000), anchoring summary (~400, per ADR-022), compacted
conversation history (~10,000), and output generation (~8,000).

**LangGraph pattern:** `trim_messages` with `token_counter=count_tokens_approximately`
(from `langchain_core.messages.utils`) is the canonical in-node approach. For mounted
documents, a simpler per-document truncation before `SystemMessage` construction is
more predictable: read the file, slice to a token cap, then build the message. This
avoids mid-sentence truncation across multiple concatenated documents.

**Production precedent:** LangChain's `ContextEditingMiddleware` with `ClearToolUsesEdit`
fires at 100,000 tokens by default to evict old tool outputs — confirming that
production systems use explicit ceiling checks rather than relying on context fitting.

## 2. Async File I/O

**Risk:** Blocking file I/O inside an async LangGraph node stalls the event loop,
blocking all concurrent graph invocations sharing that thread.

**Correct pattern:** Use `asyncio.to_thread` for all `.vault/` reads inside async nodes:

```python
import asyncio
from pathlib import Path

async def _read_vault_doc(path: Path) -> str:
    return await asyncio.to_thread(path.read_text, encoding="utf-8")
```text

`asyncio.to_thread` is stdlib since Python 3.9, requires no new dependency, and is
consistent with the existing codebase's pattern for blocking I/O offloading.

**Per-invocation cache:** A `(path, mtime)` keyed in-memory cache in the node closure
prevents redundant reads within a single supervisor cycle without polluting `TeamState`.
This cache must not be stored in state — doing so causes checkpoint bloat (per ADR-019
§1.2, the reference-in-state principle: paths only in state, content ephemeral).

## 3. Mount Step Node Pattern

**Risk:** Embedding mount logic directly inside `worker_node` conflates file I/O and
LLM invocation, making both harder to test and reason about independently.

**Recommended pattern:** A dedicated `mount_node` runs before each worker node and
writes prepared content into a transient state field (e.g.,
`mounted_context: NotRequired[str | None]`). The worker reads
`state.get("mounted_context")` and prepends it as a `SystemMessage`. After the worker
completes, the next graph step clears `mounted_context` by returning
`{"mounted_context": None}`.

This follows LangGraph's subgraph/state-transformation pattern: a preprocessing node
transforms state before the main node consumes it. It makes the mount step
independently testable without invoking the LLM.

**Graph wiring:** `mount_node` is inserted between the supervisor routing edge and each
worker node. In a star topology (ADR-013), each worker gets its own mount edge:
`supervisor → mount_node → worker_node`. The mount node uses
`state.get("active_feature")` and `state.get("vault_index")` (ADR-019) to determine
which documents to load.

## 4. References

- arXiv 2507.01701 §4.2 — blackboard content injection, "context window as scratch pad"
- Google ADK artifact handle pattern — content read per-invocation outside state
- LangGraph `trim_messages` / `count_tokens_approximately` — `langchain_core.messages.utils`
- LangChain `ContextEditingMiddleware` — production token ceiling precedent (100k default)
- ADR-019 §1.2 — reference-in-state principle (paths only in state, content never stored)
- ADR-022 — anchoring summary token budget (~400 tokens, already reserved)
