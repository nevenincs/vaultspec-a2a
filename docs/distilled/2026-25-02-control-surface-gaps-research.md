---
name: "Control Surface Gaps Research"
date: 2026-25-02
type: research
summary: "Rigorous technical decisions for SvelteKit agent rendering, replacing experimental tech with robust Server-Side Replay and @humanspeak token caching."
---

# Control Surface Gaps Research

**Date**: 2026-02-25
**Domain**: Control Surface & Rendering

## 1. Streaming Markdown: `@humanspeak/svelte-markdown` over Incremark (Gap G2)

**Architectural Problem**: LLMs stream markdown via WebSockets character-by-character. Standard parsers (`marked.js`) re-parse the entire accumulated string on every new chunk, resulting in an $O(n^2)$ CPU spike that freezes the browser on long documents (e.g., 50k+ tokens).

**Inclusion/Exclusion Decision**:
- **Excluded**: `svelte-markdown` (legacy). Uses standard reactivity; suffers catastrophic $O(n^2)$ lag.
- **Excluded**: `Incremark`. While it achieves $O(n)$ via a custom parser, it is marked as experimental, has sparse documentation for Svelte bindings, and uses non-standard rendering paths.
- **Included**: `@humanspeak/svelte-markdown`. 

**Rationale**:
It is explicitly built for Svelte 5 Runes. It solves the performance penalty not by replacing the parser, but via **Intelligent Token Caching**. It caches `Marked.js` AST tokens for completed blocks (like paragraphs or code blocks) and only re-renders the "active" tail node. This yields a 50–200x performance increase while retaining full compatibility with the massive `Marked.js` plugin ecosystem.

**Implementation Reference (Svelte 5 Runes)**:
```svelte
<script lang="ts">
  import Markdown from '@humanspeak/svelte-markdown';
  // $props() triggers fine-grained updates on the component 
  // without rebuilding the entire DOM tree.
  let { streamedContent } = $props<{ streamedContent: string }>();
</script>

<div class="agent-output">
  <Markdown source={streamedContent} />
</div>
```

## 2. xterm.js Backpressure (Gap G1)

**Architectural Problem**: The Svelte UI uses `@xterm/addon-attach` to ingest `stdout` from the agent via WebSockets. The xterm parser runs on the browser's main thread. If a Python agent dumps a 100MB build log, the browser's memory will exhaust (OOM) because WebSockets do not natively propagate TCP backpressure.

**Implementation Reference (High/Low Watermarks)**:
The application must explicitly multiplex control signals into the WebSocket stream.

```javascript
// Svelte Client
let isPaused = false;

socket.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    
    // term.write returns false if internal buffer > high watermark (~1MB)
    if (!term.write(payload.text) && !isPaused) {
        isPaused = true;
        socket.send(JSON.stringify({ action: "pause", agent_id: payload.agent_id }));
    }
};

// Emitted when the buffer drains below the low watermark
term.onDrain(() => {
    if (isPaused) {
        isPaused = false;
        socket.send(JSON.stringify({ action: "resume", agent_id: payload.agent_id }));
    }
});
```

## 3. Terminal State Recovery: Server-Side Replay (Gap G3)

**Architectural Problem**: When the user refreshes the browser, the active terminal UI is destroyed. We need to restore the agent's historical `stdout` formatting (colors, cursors).

**Inclusion/Exclusion Decision**:
- **Excluded**: `@xterm/addon-serialize`. The official NPM registry explicitly marks this as *"⚠️ experimental... under construction ⚠️"*. It attempts to read the DOM/Canvas to guess the terminal state. It routinely fails to restore private modes, alternate screen buffers (like `vim`), and complex cursor states.
- **Included**: **Server-Side Replay (Event Sourcing)**.

**Rationale**:
The UI should be a stateless projection. The Orchestrator's SQLite database must maintain a rolling ring-buffer (e.g., the last 2000 lines) of raw ANSI bytes emitted by the agent process. On UI mount, the Svelte client requests this buffer via REST, pipes it into a fresh `xterm.js` instance, and then opens the WebSocket for live updates. This guarantees 100% accurate terminal reconstruction without relying on experimental frontend serialization.
