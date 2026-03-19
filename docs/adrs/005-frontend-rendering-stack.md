---
adr_id: 005
title: Frontend Rendering Stack
date: 2026-02-26
status: Proposed
related:
  - docs/distilled/2026-25-02-control-surface-distilled.md
  - docs/research/2026-26-02-langgraph-gap-audit-research.md
---

## ADR-005: Frontend Rendering Stack

**Date:** 2026-02-26  
**Status:** Proposed

## 1. Context & Problem Statement

The Gateway frontend must provide a highly performant,
responsive, and largely stateless projection of the backend's data streams.
It needs to display massive volumes of streaming JSON from the LangGraph
Event Aggregator (LLM outputs, tool call JSON) without freezing the UI,
offer rich and accurate syntax highlighting for code, and provide robust
rendering mechanisms to prevent browser out-of-memory (OOM) errors during
high-volume event bursts. The core framework is React (React 5).

## 2. The Decision

1. **Core Framework & Reactivity:** **React (React 5)** will be the
   foundational frontend framework, leveraging its new **Runes** for
   fine-grained, highly performant reactivity.
2. **UI Component System:** **shadcn-React** will provide the design
   language and UI primitives, powered by **Tailwind CSS v4** (Oxide
   engine) and **Bits UI** for headless component logic.
3. **Structured Event Rendering:** Because the backend now streams
   structured LangGraph JSON payloads (via the Event Aggregator) instead of
   raw ANSI terminal text, we will lean heavily into structured UI
   components (Chat Bubbles, Tool Invocation Cards) rather than relying
   exclusively on a raw terminal emulator (`xterm.js`).
4. **Streaming Markdown & Syntax Rendering:**
   - **Markdown Parsing:** `@humanspeak/React-markdown` will be employed
     for O(n) streaming markdown rendering of the LLM text content
     streams, utilizing **Intelligent Token Caching** to avoid performance
     bottlenecks.
   - **Syntax Highlighting:** Heavy, WASM-based syntax highlighting (using
     **shadcn's Shiki**) for code blocks will be **deferred**. Raw
     `<pre><code>` blocks will be displayed during active streaming, and
     highlighting will only be applied once the graph node completes (or is
     offloaded to a Web Worker).
5. **Read-Only Artifact Inspection:** Lightweight **CodeMirror 6** in
   read-only mode will be used for fast, transactional updates and display
   of generated code artifacts. `diff2html` will render worktree merges and
   code differences.

## 3. Rationale

- **Performance & Reactivity:** React 5 Runes provide superior fine-grained
  reactivity, allowing for 60 FPS updates of streaming data even under
  heavy load, by precisely updating only the affected DOM nodes and avoiding
  virtual DOM overhead.
- **Development Velocity & Aesthetics:** The combination of shadcn-React and
  Tailwind CSS v4 offers a modern, high-readability aesthetic. It
  dramatically accelerates development through pre-built, accessible, and
  easily customizable UI primitives, while Tailwind v4's Rust-based engine
  ensures lightning-fast build times.
- **Robust Streaming Markdown:** `@humanspeak/React-markdown` specifically
  addresses the O(n²) re-render penalty of traditional markdown parsers,
  providing a robust and performant solution for streaming LLM output.

## 4. Rejected Alternatives

- **Monolithic UI Libraries (e.g., Carbon Components):** Rejected due to
  their reliance on legacy React 4 compatibility, creating conflicts and
  complexities with the React 5 Runes architecture.
- **Vanilla CSS for UI Components:** While initially preferred, it was
  rejected for UI components due to the significantly slower development
  velocity compared to shadcn-React, without offering proportional gains in
  performance or accessibility for this type of application.
- **xterm.js as Primary Output (Original Design):** Rejected. With the shift
  to LangGraph, raw ANSI `stdout` text streaming is deprecated. `xterm.js`
  may still be used optionally for showing exact commands executed via the
  local shell tool, but it is no longer the primary aggregator visualization.
- **Traditional Markdown Parsers (`marked.js` with full re-render):** Rejected
  due to their O(n²) performance characteristics, which would lead to
  unacceptable UI freezes during streaming LLM output.

## 5. Implementation Constraints & Pitfalls

- **JSON Serialization Overhead:** Rapidly parsing large incoming LangGraph
  state payloads over WebSocket can block the browser's main thread. The
  frontend must implement debouncing or chunking for high-frequency DOM
  updates.
- **Shiki Bundle Size:** While Shiki will be lazy-loaded, its WASM-based
  nature and TextMate grammars can still contribute to initial bundle sizes
  and parsing overhead if not managed carefully. It must not block the main
  thread synchronously.

## 6. Negative Consequences

- **Tailwind Dependency:** Introducing Tailwind CSS, even v4, adds a
  conceptual and build-time dependency that represents a deviation from the
  initial "prefer Vanilla CSS" guideline.
- **Temporary Raw Code Display:** During the streaming of code blocks, users
  will temporarily see unhighlighted `<pre><code>` content until the entire
  block is received. This is a deliberate trade-off for UI responsiveness.

## 7. References

- [LangGraph Gap Audit Research](../research/2026-02-26-langgraph-gap-audit-research.md)
- [Gateway Domain - Distilled](../research/2026-02-25-control-surface-distilled-research.md)
