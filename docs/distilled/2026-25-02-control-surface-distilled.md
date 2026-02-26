---
name: "Control Surface Domain - Distilled"
date: 2026-25-02
type: distilled
summary: "Consolidated rendering stack decisions: Tailwind v4 + shadcn-svelte, terminal emulation (xterm.js), syntax highlighting (Shiki + CodeMirror 6), streaming markdown (Incremark), diff rendering (diff2html). Memory budgets and architecture patterns from survey of 17 reference projects."
maturity: 45
sources:
  - docs/control-surface/2026-25-02-agent-ui-terminal-dashboard-research.md
  - docs/control-surface/2026-25-02-control-surface-rendering-research.md
---

# Control Surface Domain — Distilled

**Date**: 2026-02-25
**Status**: Distilled from agent UI survey + rendering stack research
**Scope**: Frontend rendering decisions, component choices, memory budgets.
Tech stack decisions (SvelteKit, FastAPI, etc.) are in the architecture
distilled doc.

---

## 1. UI Framework & Design System

### 1.1 Decision: shadcn-svelte + Tailwind CSS v4

The project explicitly deviates from the initial "Vanilla CSS" preference to adopt **Tailwind CSS v4** and **shadcn-svelte**.

- **Tailwind v4 (Oxide Engine):** Provides microsecond incremental builds via a Rust-based engine, eliminates `tailwind.config.js` in favor of CSS-first variables (`@theme`), and supports modern features like container queries natively.
- **shadcn-svelte + Bits UI:** Entirely Svelte 5 Runes-native. Provides the highly readable, data-dense "Vercel aesthetic" necessary for complex monitoring dashboards, without the overhead of monolithic libraries.

**Rationale:** The development velocity gained by using pre-built, accessible, keyboard-navigable primitives (Modals, Resizable Panes, Dropdowns) outweighs the benefits of strict Vanilla CSS. Carbon Components was evaluated but rejected due to its reliance on Svelte 4 legacy syntax (`on:click`, `bind:value`), which conflicts with the project's modern Svelte 5 Runes architecture.

---

## 2. Terminal Emulation

### 2.1 Decision: xterm.js v5

xterm.js (`@xterm/xterm`) is the only viable option. Used by VS Code, Theia,
code-server, JupyterLab, and every major web terminal project.

**Required addons:**

| Addon | Purpose |
|-------|---------|
| `@xterm/addon-fit` | Auto-resize terminal to container |
| `@xterm/addon-webgl` | GPU-accelerated rendering (WebGL2) |
| `@xterm/addon-search` | Text search in terminal buffer |
| `@xterm/addon-serialize` | Session persistence (serialize framebuffer) |
| `@xterm/addon-web-links` | Clickable URLs in output |

**SvelteKit integration**: `xterm-svelte` provides a maintained wrapper.

### 2.2 Memory Budget

| Metric | Value |
|--------|-------|
| Core bundle | ~265KB (v5, minified) |
| Memory per terminal (160x24, 5K scrollback) | ~34MB |
| Truecolor impact | Nearly doubles buffer consumption |
| Write buffer hard limit | 50MB |
| Serialization speed | ~25MB/s |

**Multi-agent impact**: 5 agents at 5K scrollback = ~170MB for terminals alone.

**Mitigation strategy**:

- Cap scrollback at 1–2K lines (not 5K)
- Use `@xterm/addon-serialize` to persist historical output to SQLite
- Lazy terminal creation (only instantiate when tab is active)
- Disable truecolor if memory is a concern

### 2.3 WebSocket Integration Pattern

```
Browser (xterm.js) ←—WebSocket—→ Backend Server ←—stdio—→ Agent Process
```

Each agent's stdout/stderr is relayed over the multiplexed WebSocket to its
xterm.js instance. The `@xterm/addon-attach` provides basic WebSocket
attachment but lacks flow control — custom implementation needed for production.

### 2.4 Session Reconnection

The `@xterm/addon-serialize` can serialize terminal framebuffer (colors, flags,
content) to a string. On reconnect, feed serialized state into a new terminal
of the same dimensions. Performance: ~100K scrollback lines in ~1 second.
Still experimental.

---

## 3. Syntax Highlighting

### 3.1 Decision: Layered Approach

Three rendering contexts, each with its own highlighting strategy:

| Context | Library | Rationale |
|---------|---------|-----------|
| Terminal output | Native ANSI | xterm.js interprets ANSI codes natively. Tools like `bat` and `rich` emit highlighted output that renders correctly with no extra work. |
| Code blocks in agent messages | Shiki (lazy-loaded) | VS Code-grade highlighting via TextMate grammars + WASM. ~250KB + WASM, so must be lazy-loaded. |
| Code viewer / artifact inspector | CodeMirror 6 | 124KB bundle (vs Monaco's 2MB+). Read-only mode, efficient incremental updates via transactions. Supports search, folding. |

### 3.2 What Was Eliminated

| Library | Reason |
|---------|--------|
| Monaco Editor | 2MB+ bundle. Sourcegraph cut 43% of their JS by replacing it with CodeMirror. Only justified if full editing is needed. |
| Prism.js | No longer actively maintained. |
| Tree-sitter (browser) | Interesting for structural parsing but overkill for highlighting. Deferred to future. |

### 3.3 ANSI + Structured Highlighting Coexistence

Agent processes may emit ANSI-highlighted output (via `bat`, `rich`, or native
CLI formatting). This renders correctly in xterm.js. Structured markdown
content is rendered separately via the markdown pipeline. These are separate
rendering contexts — never mix ANSI codes into HTML rendering.

---

## 4. Streaming Markdown

### 4.1 The Core Problem

LLM output arrives as character/word chunks. Markdown syntax elements span
multiple chunks (e.g., code fence opens in one chunk, closes many chunks
later). Traditional parsers (marked, markdown-it) re-parse the entire
accumulated document on each chunk: O(n²) performance.

### 4.2 Decision: Incremark

| Criteria | Incremark | Streamdown |
|----------|-----------|------------|
| Performance | O(n) incremental, up to 65x faster | Better than naive, details unclear |
| Svelte support | Yes (`@incremark/svelte`) | React only |
| Maturity | Newer, less battle-tested | Vercel-backed, production use |
| Custom components | Supported | Supported (plugin architecture) |

**Incremark wins** for our SvelteKit frontend due to native Svelte support and
O(n) incremental parsing. Key property: once a block is marked complete, it is
never re-parsed.

If the project were React-based, Streamdown would be the alternative.

### 4.3 Chrome's Official Best Practices

1. Never use `textContent` (destroys/recreates all child nodes)
2. Use purpose-built streaming parsers (not marked/markdown-it)
3. Sanitize the combined result, not individual chunks (DOMPurify)
4. Batch DOM updates on natural boundaries (newlines, paragraph breaks)

---

## 5. Code Viewing

### 5.1 Decision: CodeMirror 6

For the artifact viewer / code review panel. Key properties:

- 124KB minified+gzipped (basic setup)
- Redux-esque unidirectional data flow
- `EditorState.readOnly` facet for trivial read-only mode
- Efficient incremental updates via transactions (good for streaming artifact
  content)
- Lazy-loadable language support
- Used by Replit (who chose it over Monaco for 40x smaller bundle)

---

## 6. Diff Rendering

### 6.1 Decision: diff2html

Framework-agnostic (works with Svelte). Converts git unified diff output to
HTML. Uses highlight.js for syntax highlighting within diffs. Side-by-side and
line-by-line views.

`react-diff-view` would be the alternative if using React. `react-diff-viewer`
is unmaintained (6 years since last publish).

---

## 7. Agent Output Rendering Architecture

```
Agent Backend (A2A protocol)
    |
    | WebSocket (multiplexed streams)
    |
    v
Control Surface Frontend
    |
    +-- Agent Message Renderer
    |     +-- Streaming Markdown (Incremark)
    |     +-- Code Blocks (Shiki, lazy-loaded)
    |     +-- Tool Call Components (custom, structured dispatch)
    |     +-- Thinking Block Components (collapsible)
    |     +-- Diff Viewer (diff2html)
    |
    +-- Terminal Emulator(s)
    |     +-- xterm.js v5 with WebGL addon
    |     +-- One instance per agent
    |     +-- Serialize addon for persistence
    |
    +-- Code Viewer
          +-- CodeMirror 6 (read-only)
          +-- For artifact inspection / code review
```

### 7.1 Content Type Dispatch

Agent events carry typed content. The renderer dispatches based on type:

- `text` → Streaming markdown (Incremark)
- `tool_result` → Tool call component (terminal-styled, monospace)
- `code_artifact` → CodeMirror 6 viewer
- `thinking` → Collapsible thinking panel
- `diff` → diff2html renderer

This mirrors how Open WebUI dispatches `MarkdownTokens.svelte` and how llm-ui
uses `useLLMOutput` pattern matching.

---

## 8. Reference Project Insights

### 8.1 Most Relevant References

| Project | Stars | Key Pattern Learned |
|---------|-------|-------------------|
| Open WebUI | ~45K | SvelteKit + FastAPI pairing; SSE + WebSocket hybrid |
| Grafana | ~66K | Single WebSocket with channel multiplexing (adopted) |
| Supervisor | — | Process state machine (STARTING → RUNNING → STOPPING → STOPPED) |
| Theia | ~20K | JSON-RPC over WebSocket for structured communication |
| AutoGen Studio | ~42K | Inner monologue rendering; cost tracking per task |
| Portainer | ~32K | Lightweight agent pattern for remote process management |

### 8.2 Patterns Not Adopted

| Pattern | Projects | Why Not |
|---------|----------|---------|
| React Flow visual editor | Dify, Langflow, Flowise | Not building a drag-and-drop workflow editor for v1 |
| Celery task queue | Dify | Overkill for local single-user tool |
| GraphQL API | CrewAI Visualizer | REST + WebSocket is simpler for our use case |
| AngularJS | Portainer (legacy) | Not relevant |
| Streamlit | CrewAI Studio | Not production-grade for rich UIs |

---

## 9. Open Contradictions

### C1: Redis Recommended by Survey, Rejected by Architecture

The UI survey recommends "Redis for PUB/SUB and session management" (proven
by Open WebUI, Dify). The architecture decision is SQLite-only for v1 with no
Redis.

**Resolution**: These are not strictly contradictory — Redis is recommended for
production horizontal scaling, while our v1 is a single-user local tool.
SQLite is correct for v1. Redis becomes relevant if/when multi-user or
multi-process deployment is needed.

### C2: Per-Terminal WebSocket vs Multiplexed

The survey notes Theia uses per-terminal WebSocket connections for isolation,
and suggests this might be "likely better" for agent terminals. The
architecture settles on a single multiplexed WebSocket (Grafana pattern).

**Partially resolved**: Multiplexing is chosen for connection efficiency and
simpler reconnection. Terminal data is tagged with `agent_id` for routing.
The trade-off is that a slow consumer on one terminal can theoretically affect
others — backpressure management in the multiplexer is needed.

---

## 10. Knowledge Gaps

### G1: xterm.js Flow Control for Production

The `@xterm/addon-attach` provides basic WebSocket attachment but "does not
handle flow control automatically — custom implementations are recommended for
production use." No specification for the custom flow control exists. This
matters when agents produce high-volume output (e.g., verbose build logs).

### G2: Streaming Markdown Library Maturity for Svelte

Incremark is "newer, less battle-tested" and its Svelte renderer is the least
documented of its framework bindings. If it has stability issues, the fallback
is `svelte-markdown` + `marked.js` with O(n²) performance.

### G3: Terminal Serialize/Reconnect in Production

The `@xterm/addon-serialize` is still experimental. No production reference
for using it in a multi-terminal reconnection flow exists. If it proves
unreliable, the fallback is replaying raw output from the SQLite event log
(slower, may lose formatting).
