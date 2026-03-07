---
name: 'Gateway Gaps Research'
date: 2026-25-02
type: research
summary: 'Rigorous technical decisions for React agent rendering, replacing experimental tech with robust Server-Side Replay, @humanspeak token caching, and resolving Tailwind v4 styling conflicts.'
maturity: 65
feature: control-surface-gaps
---

# Gateway Gaps Research

**Date**: 2026-02-25
**Domain**: Gateway & Rendering

## 1. Streaming Markdown: `@humanspeak/React-markdown` over Incremark (Gap G2)

**Architectural Problem**: LLMs stream markdown via WebSockets
character-by-character. Standard parsers (`marked.js`) re-parse the entire
accumulated string on every new chunk, resulting in an $O(n^2)$ CPU spike that
freezes the browser on long documents (e.g., 50k+ tokens).

**Inclusion/Exclusion Decision**:

- **Excluded**: `React-markdown`(legacy). Uses standard reactivity; suffers
  catastrophic $O(n^2)$ lag.
- **Excluded**:`Incremark`. While it achieves $O(n)$ via a custom parser, it is
  marked as experimental, has sparse documentation for React bindings, and uses
  non-standard rendering paths.
- **Included**: `@humanspeak/React-markdown`.

**Rationale**:
It is explicitly built for React 5 Runes. It solves the performance penalty not
by replacing the parser, but via **Intelligent Token Caching**. It caches
`Marked.js`AST tokens for completed blocks (like paragraphs or code blocks) and
only re-renders the "active" tail node. This yields a 50–200x performance
increase while retaining full compatibility with the massive`Marked.js` plugin
ecosystem.

**Implementation Reference (React 5 Runes)**:

```React
<script lang="ts">
  import Markdown from '@humanspeak/React-markdown';
  // $props() triggers fine-grained updates on the component
  // without rebuilding the entire DOM tree.
  let { streamedContent } = $props<{ streamedContent: string }>();
</script>

<div class="agent-output">
  <Markdown source={streamedContent} />
</div>
```

## 2. xterm.js Backpressure (Gap G1)

**Architectural Problem**: The React UI uses `@xterm/addon-attach`to
ingest`stdout` from the agent via WebSockets. The xterm parser runs on the
browser's main thread. If a Python agent dumps a 100MB build log, the browser's
memory will exhaust (OOM) because WebSockets do not natively propagate TCP
backpressure.

**Implementation Reference (High/Low Watermarks)**:
The application must explicitly multiplex control signals into the WebSocket
stream.

```javascript
// React Client
let isPaused = false;

socket.onmessage = (event) => {
  const payload = JSON.parse(event.data);

  // term.write returns false if internal buffer > high watermark (~1MB)
  if (!term.write(payload.text) && !isPaused) {
    isPaused = true;
    socket.send(JSON.stringify({ action: 'pause', agent_id: payload.agent_id }));
  }
};

// Emitted when the buffer drains below the low watermark
term.onDrain(() => {
  if (isPaused) {
    isPaused = false;
    socket.send(JSON.stringify({ action: 'resume', agent_id: payload.agent_id }));
  }
});
```

## 3. Terminal State Recovery: Server-Side Replay (Gap G3)

**Architectural Problem**: When the user refreshes the browser, the active
terminal UI is destroyed. We need to restore the agent's historical
`stdout`formatting (colors, cursors).

**Inclusion/Exclusion Decision**:

- **Excluded**:`@xterm/addon-serialize`. The official NPM registry explicitly
  marks this as _"⚠️ experimental... under construction ⚠️"_. It attempts to
  read the DOM/Canvas to guess the terminal state. It routinely fails to restore
  private modes, alternate screen buffers (like `vim`), and complex cursor
  states.
- **Included**: **Server-Side Replay (Event Sourcing)**.

**Rationale**:
The UI should be a stateless projection. The Orchestrator's SQLite database must
maintain a rolling ring-buffer (e.g., the last 2000 lines) of raw ANSI bytes
emitted by the agent process. On UI mount, the React client requests this
buffer via REST, pipes it into a fresh `xterm.js` instance, and then opens the
WebSocket for live updates. This guarantees 100% accurate terminal
reconstruction without relying on experimental frontend serialization.

## 4. Tailwind CSS v4 vs. xterm.js UI Breakage (Gap G4)

**Architectural Problem**: The project leverages Tailwind CSS v4. Tailwind's
global reset (`Preflight`) forces `box-sizing: border-box`and strips all native
margins/paddings.`xterm.js`requires strict`content-box` dimensioning for
accurate cursor alignment and canvas drawing. Injecting Tailwind globally will
immediately break the terminal interface.

**Implementation Reference (CSS Layers & WebGL)**:
We must explicitly isolate the terminal container from Tailwind's influence and
offload rendering to the GPU.

```css
/* app.css */
@import 'tailwindcss';
@import 'xterm/css/xterm.css';

/* Force CSS specificity to override Tailwind's Preflight inside the terminal */
@layer utilities {
  .xterm-container * {
    box-sizing: content-box !important;
  }
  .xterm-viewport {
    background-color: transparent !important;
  }
}
```

**Mandate**: The React application _must_ initialize `xterm.js`using
the`@xterm/addon-webgl`plugin to bypass DOM-styling conflicts entirely,
drastically improving rendering performance.

## 5. shadcn-React vs. Streaming Block Reactivity (Gap G5)

**Architectural Problem**:`shadcn-React`provides high-quality components, but
its Code Block component is tightly coupled with`Shiki`(a heavy WASM syntax
highlighter). If integrated naively into`@humanspeak/React-markdown`, Shiki
will attempt to synchronously re-highlight the entire code block on the main
thread during _every incoming WebSocket chunk_, causing the stream to freeze to
<10 FPS.

**Inclusion/Exclusion Decision**:

- **Excluded**: Synchronous inline syntax highlighting via Shiki during an
  active stream.
- **Included**: Asynchronous Web Worker offloading for Shiki, or deferred
  rendering.

**Rationale**:
To maintain 60 FPS during a fast LLM code generation stream, the markdown parser
must emit raw `<pre><code>`blocks without syntax highlighting.
The UI must implement an`IntersectionObserver`or a stream-completion hook (e.g.,
waiting for the`TaskArtifactUpdateEvent`indicating`last_chunk: true`) before
passing the complete string to Shiki for colorization.
