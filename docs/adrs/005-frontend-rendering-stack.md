---
adr_id: 005
title: Frontend Rendering Stack
date: 2026-02-25
status: Proposed
related:
  - docs/distilled/2026-25-02-control-surface-distilled.md
  - docs/distilled/2026-25-02-control-surface-gaps-research.md
---

# ADR-005: Frontend Rendering Stack

**Date:** 2026-02-25  
**Status:** Proposed

## 1. Context & Problem Statement

The Control Surface frontend must provide a highly performant, responsive, and largely stateless projection of the backend's data streams. It needs to display massive volumes of streaming text (LLM outputs, terminal `stdout`) without freezing the UI, offer rich and accurate syntax highlighting for code, and provide robust terminal emulation with mechanisms to prevent browser out-of-memory (OOM) errors during high-volume event bursts. The core framework is SvelteKit (Svelte 5).

## 2. The Decision

1. **Core Framework & Reactivity:** **SvelteKit (Svelte 5)** will be the foundational frontend framework, leveraging its new **Runes** for fine-grained, highly performant reactivity.
2. **UI Component System:** **shadcn-svelte** will provide the design language and UI primitives, powered by **Tailwind CSS v4** (Oxide engine) and **Bits UI** for headless component logic.
3. **Terminal Emulation & Backpressure:** `xterm.js` (v5) with its `@xterm/addon-webgl` for GPU-accelerated rendering will be used. A **High/Low Watermark Backpressure system** will be implemented: the frontend monitors `term.write()` return values and emits JSON `{"action": "pause"}`/`{"action": "resume"}` commands over the WebSocket to signal the backend to throttle event transmission.
4. **Streaming Markdown & Syntax Rendering:**
    * **Markdown Parsing:** `@humanspeak/svelte-markdown` will be employed for O(n) streaming markdown rendering, utilizing **Intelligent Token Caching** to avoid performance bottlenecks.
    * **Syntax Highlighting:** Heavy, WASM-based syntax highlighting (using **shadcn's Shiki**) for code blocks will be **deferred**. Raw `<pre><code>` blocks will be displayed during active streaming, and highlighting will only be applied once `last_chunk: true` is received (indicating the code block is complete) or offloaded to a Web Worker.
5. **Read-Only Artifact Inspection:** Lightweight **CodeMirror 6** in read-only mode will be used for fast, transactional updates and display of generated code artifacts. `diff2html` will render worktree merges and code differences.

## 3. Rationale

* **Performance & Reactivity:** Svelte 5 Runes provide superior fine-grained reactivity, allowing for 60 FPS updates of streaming data even under heavy load, by precisely updating only the affected DOM nodes and avoiding virtual DOM overhead.
* **Development Velocity & Aesthetics:** The combination of shadcn-svelte and Tailwind CSS v4 offers a modern, high-readability aesthetic. It dramatically accelerates development through pre-built, accessible, and easily customizable UI primitives, while Tailwind v4's Rust-based engine ensures lightning-fast build times.
* **Browser Thread Safety:** The xterm.js backpressure system is crucial for explicitly preventing browser OOM errors during massive `stdout` bursts from agents. Deferred syntax highlighting ensures the main browser thread remains responsive during streaming of complex code, preventing UI freezes.
* **Robust Streaming Markdown:** `@humanspeak/svelte-markdown` specifically addresses the O(n²) re-render penalty of traditional markdown parsers, providing a robust and performant solution for streaming LLM output.

## 4. Rejected Alternatives

* **Monolithic UI Libraries (e.g., Carbon Components):** Rejected due to their reliance on legacy Svelte 4 compatibility, creating conflicts and complexities with the Svelte 5 Runes architecture.
* **Vanilla CSS for UI Components:** While initially preferred, it was rejected for UI components due to the significantly slower development velocity compared to shadcn-svelte, without offering proportional gains in performance or accessibility for this type of application.
* **Client-Side Terminal Serialization (`@xterm/addon-serialize`):** Rejected for terminal history reconstruction due to its experimental nature and documented unreliability in restoring complex terminal states.
* **Traditional Markdown Parsers (`marked.js` with full re-render):** Rejected due to their O(n²) performance characteristics, which would lead to unacceptable UI freezes during streaming LLM output.
* **`Incremark` for Streaming Markdown:** Rejected due to its experimental status, sparse Svelte documentation, and the robustness offered by `@humanspeak/svelte-markdown`'s token caching approach.

## 5. Implementation Constraints & Pitfalls

* **Tailwind v4 vs xterm.js Preflight Constraints:** Integrating Tailwind v4's global reset (`Preflight`) breaks xterm.js layout calculations. The application must explicitly use CSS `@layer` rules to override Tailwind's `box-sizing: border-box` inside the terminal container, and the WebGL addon is mandatory to bypass further DOM-styling issues.
* **Backpressure Protocol Reliability:** The `{"action": "pause"}`/`{"action": "resume"}` WebSocket protocol for xterm.js backpressure must be rigorously implemented and tested end-to-end between frontend and backend to prevent deadlocks or data loss during extreme event loads.
* **Shiki Bundle Size:** While Shiki will be lazy-loaded, its WASM-based nature and TextMate grammars can still contribute to initial bundle sizes and parsing overhead if not managed carefully. It must not block the main thread synchronously.

## 6. Negative Consequences

* **Tailwind Dependency:** Introducing Tailwind CSS, even v4, adds a conceptual and build-time dependency that represents a deviation from the initial "prefer Vanilla CSS" guideline.
* **Temporary Raw Code Display:** During the streaming of code blocks, users will temporarily see unhighlighted `<pre><code>` content until the entire block is received. This is a deliberate trade-off for UI responsiveness.
* **Limited Immediate History:** The Server-Side Replay's 2000-line limit for immediate terminal history means older terminal output is not instantly accessible on reconnect, requiring explicit user action for full history (deferred to v2).

## 7. References

### 7.1 Local Research & Distilled Docs
* [Control Surface Domain - Distilled](../distilled/2026-25-02-control-surface-distilled.md)
* [Control Surface Gaps Research](../distilled/2026-25-02-control-surface-gaps-research.md)

### 7.2 Codebase Modules & Patterns
* **xterm.js WebGL & Overrides:** CSS `@layer` patterns defined in Gap Research to isolate `.xterm-container` from Tailwind v4's `Preflight`.
* **Svelte 5 Reactivity:** Usage of Runes (`$state`, `$derived`, `$props`) for high-performance DOM updates.
* **WebSocket Flow Control:** Implementation pattern using `term.write()` return booleans mapped to `{"action": "pause"}` JSON payloads to manage browser backpressure.
* **Deferred Highlighting Pattern:** Emitting raw `<pre>` tags during SSE streaming, relying on an `IntersectionObserver` or `last_chunk: true` flag to trigger Shiki.

### 7.3 Online Reference Implementation
* **shadcn-svelte (Svelte 5):** [shadcn-svelte v1.0 Documentation](https://next.shadcn-svelte.com/) (referenced for Svelte 5 and Tailwind v4 compatibility).
* **@humanspeak/svelte-markdown:** [Intelligent Token Caching](https://github.com/humanspeak/svelte-markdown) (referenced for solving the $O(n^2)$ markdown re-render problem).
* **xterm.js Backpressure:** [xterm.js API Documentation](https://xtermjs.org/docs/api/terminal/classes/terminal/#write) (referenced for the `write()` boolean return and `onDrain` event pattern).
