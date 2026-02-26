---
name: "Control Surface Rendering"
date: 2026-25-02
type: research
summary: "Deep analysis of xterm.js terminal emulation, syntax highlighting options, streaming markdown renderers, and diff rendering for agent output."
maturity: 25
---

# Research Phase 2: Terminal Emulation, Syntax Highlighting, and Agent Output Rendering

**Date**: 2026-02-25
**Status**: Research Complete
**Scope**: Web-based control surface rendering stack

---

## Table of Contents

1. [Part 1: xterm.js Ecosystem](#part-1-xtermjs-ecosystem)
2. [Part 2: Syntax Highlighting in Web Context](#part-2-syntax-highlighting-in-web-context)
3. [Part 3: Agent Output Rendering](#part-3-agent-output-rendering)
4. [Comparative Analysis and Recommendations](#comparative-analysis-and-recommendations)

---

## Part 1: xterm.js Ecosystem

### 1.1 Architecture Overview

xterm.js is the dominant web-based terminal emulator, powering VS Code's integrated
terminal, Hyper, code-server, and numerous cloud IDE products.

**Repository**: <https://github.com/xtermjs/xterm.js>
**Current Version**: v5.x (scoped as `@xterm/xterm` on npm)
**License**: MIT

#### Core Architecture

xterm.js uses a **service-oriented architecture** with dependency injection. The
core is split into:

- **Core module** (`@xterm/xterm`): Parser, buffer management, input handling,
  base rendering. In v5 the core was reduced from 379KB to 265KB (30% reduction)
  by extracting the canvas renderer into an addon.
- **Services layer**: Window/document management, character sizing, theming,
  rendering coordination, mouse/selection handling, link detection, decoration
  management.
- **Renderer abstraction**: The renderer is pluggable. The core ships with a DOM
  renderer fallback; GPU-accelerated rendering is provided via addons.

#### Rendering Pipeline

The rendering pipeline operates in layers (bottom to top):

1. **TextRenderLayer** - Background and foreground content
2. **SelectionRenderLayer** - Selected region overlay
3. **LinkRenderLayer** - Hyperlink coloring and text decoration
4. **CursorRenderLayer** - Cursor blinking and styles

Only changed layers are repainted, avoiding full-canvas redraws. The WebGL
renderer uses a **texture atlas** strategy with multiple active rows, packing
glyphs by pixel height for efficient GPU texture uploads.

### 1.2 Addon Ecosystem

All addons are scoped under `@xterm/` since v5.4.0:

| Addon | Package | Purpose |
|-------|---------|---------|
| **Fit** | `@xterm/addon-fit` | Auto-resize terminal to container element |
| **WebGL** | `@xterm/addon-webgl` | GPU-accelerated rendering via WebGL2 context |
| **Canvas** | `@xterm/addon-canvas` | Canvas-based renderer (fallback for WebGL) |
| **Search** | `@xterm/addon-search` | Text search within terminal buffer |
| **Web Links** | `@xterm/addon-web-links` | Clickable URL detection |
| **Unicode11** | `@xterm/addon-unicode11` | Correct character widths for Unicode 11 |
| **Image** | `@xterm/addon-image` | Inline image display (sixel, iTerm2 protocol) |
| **Serialize** | `@xterm/addon-serialize` | Serialize terminal state to string/HTML |
| **Attach** | `@xterm/addon-attach` | WebSocket attachment to backend process |
| **Clipboard** | `@xterm/addon-clipboard` | Browser clipboard access |

Custom addons can be written by exporting an object with `activate()` and
`dispose()` methods.

### 1.3 WebSocket Integration Patterns

The standard backend integration pattern follows this flow:

```
Browser (xterm.js) <--WebSocket--> Backend Server <--PTY--> Shell Process
```

**Common implementation stacks**:

- **Node.js**: `node-pty` spawns the shell; data piped via `ws` or `socket.io`
  WebSocket to xterm.js frontend. `ptyProcess.write()` sends input,
  `ptyProcess.onData` emits output.
- **Python**: `pyxtermjs` uses Flask + `flask-socketio` + `pty` module.
- **Go**: SSH-to-WebSocket bridges for remote terminal access.

**Session management**: Each WebSocket connection spawns a new shell instance.
The shell is destroyed when the WebSocket closes, preventing zombie processes.

**Flow control**: WebSocket message delivery is non-blocking, requiring
additional flow control logic. xterm.js has a hardcoded **50MB write buffer
limit** to prevent out-of-memory conditions. The `@xterm/addon-attach` addon
provides basic WebSocket attachment but does not handle flow control
automatically -- custom implementations are recommended for production use.

**Serialize/Reconnect pattern**: The `@xterm/addon-serialize` addon can serialize
the terminal framebuffer (colors, flags, content) into a string. On reconnect,
this string is fed back into a new terminal instance of the same dimensions.
Serialization performance is approximately **25MB/s**, handling 100K scrollback
lines in roughly 1 second. This is still experimental.

### 1.4 VS Code's Terminal Implementation

VS Code's integrated terminal is the reference implementation for xterm.js
integration:

- Uses **ConPTY** on Windows 10+ (build 18309+), falling back to **winpty** on
  older versions.
- Supports two terminal locations: **Terminal Panel** (bottom) and **Terminal
  Editors** (editor area), with tab groups and split panes.
- Constructs a **global atlas generator** shared between terminals with the same
  configuration, reducing duplicate glyph rendering across multiple instances.
- Uses the WebGL renderer by default with canvas fallback.

### 1.5 code-server Implementation

code-server (VS Code in the browser) reuses VS Code's terminal infrastructure
largely unchanged. The key difference is the transport layer: instead of
local IPC to a PTY, the terminal data flows over WebSocket to the server process
which manages the PTY. The xterm.js instance in the browser is identical to what
VS Code uses natively.

### 1.6 Performance Characteristics

| Metric | Value |
|--------|-------|
| **Bundle size (core)** | ~265KB (v5, minified) |
| **Memory (160x24, 5K scrollback)** | ~34MB |
| **Memory impact of truecolor** | Nearly doubles buffer consumption |
| **Buffer copy (160x24, 5K scrollback)** | 30-60ms |
| **Write buffer hard limit** | 50MB |
| **Serialization speed** | ~25MB/s |
| **Infinite scrollback** | Not supported; must set explicit max |

**Key concern for control surface**: Running multiple terminal instances (one per
agent) with large scrollback buffers will consume significant memory. A 5-agent
setup with 5K scrollback each would consume ~170MB just for terminal buffers.
Recommend capping scrollback at 1-2K lines and using the serialize addon to
persist historical output to disk/database.

### 1.7 v5 Breaking Changes from v4

- **Package scope migration**: `xterm` -> `@xterm/xterm`, all addons from
  `xterm-addon-*` -> `@xterm/addon-*`. Old packages are deprecated.
- **Canvas renderer extracted**: No longer bundled in core; available as
  `@xterm/addon-canvas`. WebGL addon is the recommended renderer.
- **30% bundle size reduction**: From 379KB to 265KB.
- **New features**: Underline style/color support, hyperlink escape sequences,
  new `linkHandler` option for hover/leave/activate events.
- **Texture atlas improvements**: Multiple active rows, deferred warm-up to idle
  callbacks, optimized canvas contexts, multi-page texture atlas support.

---

## Part 2: Syntax Highlighting in Web Context

### 2.1 Shiki

**Repository**: <https://github.com/shikijs/shiki>
**Website**: <https://shiki.style>
**Current Version**: v1.x (complete rewrite from v0.x)

#### Architecture

Shiki uses **VS Code's TextMate grammar engine** (Oniguruma) compiled to
**WebAssembly** for tokenization. This gives it the exact same highlighting
quality as VS Code.

- **WASM-based**: Oniguruma (C library) compiled to WASM. Uses
  `WebAssembly.instantiateStreaming()` for parallel download/compilation.
- **ESM distribution**: All grammars, themes, and WASM are served as ESM, lazy-
  loaded on demand. Can be imported from CDN with a single line.
- **WASM binary embedded as base64**: Shipped as an ES module to avoid dangling
  promises and complex loading.
- **Multi-theme support**: Breaks down common tokens and merges themes as inlined
  CSS variables for efficient output.

#### Streaming Capability

Shiki is designed for **build-time / server-side** highlighting. It does NOT have
native streaming support for incremental token-by-token highlighting. Each call
to `shiki.codeToHtml()` processes the entire code block.

#### Performance Trade-offs

- **Quality**: Identical to VS Code. Best-in-class accuracy.
- **Speed**: 7x slower than Prism.js in benchmarks.
- **Bundle size**: ~250KB + WASM dependency. Not ideal for client-side
  real-time rendering.
- **Best use case**: Pre-rendering code blocks in markdown, build-time
  highlighting, or lazy-loaded client-side for code blocks that appear after
  page load.

#### Adoption

Used by Nuxt Content, VitePress, Astro, and the llm-ui React library for code
block rendering.

### 2.2 Prism.js

**Website**: <https://prismjs.com>
**Bundle size**: ~2KB core + per-language plugins

- Fastest of the three major highlighters (benchmark leader).
- Modular architecture: include only needed languages.
- Pure JavaScript, no WASM dependency.
- Plugin ecosystem for line numbers, line highlighting, etc.
- **Not actively maintained** -- last major release was several years ago.
- Quality is lower than Shiki (simpler regex-based tokenization).

### 2.3 highlight.js

**Website**: <https://highlightjs.org>
**Bundle size**: ~30KB core

- About half the speed of Prism.js.
- Auto-detection of languages.
- 190+ languages supported.
- Used by diff2html for diff syntax highlighting.
- Simpler API than Prism.js.
- Still actively maintained.

### 2.4 Comparative Summary: Syntax Highlighters

| Feature | Shiki | Prism.js | highlight.js |
|---------|-------|----------|-------------|
| **Quality** | VS Code-grade | Good | Good |
| **Speed** | Slowest (7x Prism) | Fastest | 2x slower than Prism |
| **Bundle** | ~250KB + WASM | ~2KB core | ~30KB core |
| **Streaming** | No | No | No |
| **Maintenance** | Active | Stale | Active |
| **Best for** | Build-time, code blocks | Real-time, lightweight | General purpose |

### 2.5 Monaco Editor as Read-Only Viewer

**Repository**: <https://github.com/microsoft/monaco-editor>
**Website**: <https://microsoft.github.io/monaco-editor>

Monaco IS the VS Code editor extracted as a library. It provides the best
possible code editing and viewing experience, but at significant cost:

- **Bundle size**: 2-10MB uncompressed, >2MB minified + gzipped.
- **Read-only mode**: Fully supported via `readOnly: true` option. Can also
  constrain specific regions.
- **React integration**: `@monaco-editor/react` provides clean component API.

**Verdict for dashboard use**: Too heavyweight. Sourcegraph reduced their JS
bundle by 43% (from 5.8MB to 3.4MB) just by replacing Monaco with CodeMirror.
Monaco is appropriate only if the control surface needs full editor capabilities
(e.g., editing agent prompts). For read-only code display, use CodeMirror 6 or
Shiki.

### 2.6 CodeMirror 6

**Website**: <https://codemirror.net>
**Current Version**: v6
**Bundle size**: ~124KB minified + gzipped (basic setup); ~300KB with common
extensions

#### Architecture

CodeMirror 6 uses a **Redux-esque unidirectional data flow** architecture:

- State and view are completely separate.
- Changes are applied via "transactions".
- Extension-based composition: functionality is assembled from independent
  extensions (language support, keymaps, theming, etc.).
- Language support uses **lazy loading**: core languages (HTML, CSS, JS, JSON)
  bundled directly; others loaded on demand.

#### Read-Only Viewer Use

- `EditorState.readOnly` facet makes it trivially read-only.
- SSR support: can render on the server via JSDOM for read-only code blocks.
- Replit chose CodeMirror 6 for their entire editor, citing the modular
  architecture and 40x smaller bundle vs Monaco.

#### Streaming / Live Updates

CodeMirror 6 supports efficient document updates via transactions. A
`StreamParser` shim exists for porting CM5 modes. For live-updating content
(e.g., streaming agent code output), you can dispatch transactions to append
content without re-rendering the entire document.

**Verdict**: Best choice for embedded code viewing in a dashboard. Lightweight,
modular, high-quality highlighting, and supports efficient incremental updates.

### 2.7 ANSI + Syntax Highlighting Coexistence

Terminal tools like `bat` and `rich` produce syntax-highlighted output using
**ANSI escape codes**. This is fundamentally different from HTML-based
highlighting:

- **bat** (Rust): Uses syntect (Sublime Text syntax definitions) to tokenize,
  then emits ANSI color codes. The `as_terminal_escaped` function combines
  color + font styling into ANSI strings. Problem: if input already contains
  ANSI codes, syntax highlighting can produce garbled output (`--strip-ansi=auto`
  mitigates this).

- **rich** (Python): Similar approach -- tokenizes source code and emits ANSI
  sequences for the terminal.

**For xterm.js**: ANSI-highlighted output from tools like `bat` or `rich` renders
correctly in xterm.js with no additional work -- xterm.js is a full terminal
emulator that interprets ANSI escape sequences natively. This means agent
processes that use `bat` or `rich` for output will display correctly.

**Coexistence pattern**: Use xterm.js for raw terminal output (which may contain
ANSI-highlighted code from tools), and use Shiki/CodeMirror for structured code
blocks in the agent message rendering layer. These are separate rendering
contexts and do not conflict.

### 2.8 Tree-sitter WASM

**Repository**: <https://github.com/tree-sitter/tree-sitter>
**Browser Package**: `web-tree-sitter`

#### Architecture

Tree-sitter is an **incremental parsing** system:

- Written in C, compiled to WASM for browser use.
- Parses source code into a concrete syntax tree.
- When edits occur, produces a new tree sharing unchanged subtrees with the old
  one -- fast and memory-efficient.
- Each language has its own `.wasm` grammar file.
- Used by GitHub.com for syntax highlighting.

#### Browser Integration

- Download `web-tree-sitter.js` and `web-tree-sitter.wasm` from GitHub releases.
- Load language grammars as separate `.wasm` files on demand.
- Supports incremental re-parsing: ideal for streaming content where code is
  appended character by character.

#### Trade-offs

- **Pro**: True incremental parsing (O(edit size), not O(document size)).
- **Pro**: Used by GitHub for production highlighting.
- **Pro**: Structural understanding of code (not just tokens) enables features
  beyond highlighting.
- **Con**: Each language grammar is a separate WASM file (50-200KB each).
- **Con**: More complex API than Shiki or highlight.js.
- **Con**: Syntax highlighting requires separate "highlight queries" per
  language, which are less mature than TextMate grammars.

**Verdict**: Interesting for future use if we need incremental code parsing for
features beyond highlighting (e.g., code folding, structural navigation). For
pure highlighting, Shiki or CodeMirror 6 are more practical today.

---

## Part 3: Agent Output Rendering

### 3.1 How Claude Code CLI Renders Output

Claude Code is built with **React + Ink** (React for the terminal):

- **React 18.2.0** for component model and state management.
- **Ink 3.2.0** for rendering React components to terminal output.
- **Yoga 2.0.0-beta.1** (Meta's WASM-based flexbox layout engine) for
  terminal layout.
- **Bun** for building and packaging.

#### Rendering Pipeline

Every UI update goes through React's reconciliation/diffing algorithm, then Yoga
calculates optimal terminal character positions. This is declarative -- unlike
traditional CLIs that manage output imperatively.

#### Content Types

- **Markdown**: Currently renders as raw markdown syntax in the terminal (literal
  `**bold**`, `# Header`, etc.). A feature request exists for proper terminal
  markdown rendering.
- **Thinking blocks**: Displayed as gray italic text. Toggled via Ctrl+O
  (verbose mode). Extended thinking is enabled by default.
- **Tool calls**: Shown/hidden via `--show-tools` / `--no-tools` flags.
- **Code blocks**: Rendered as terminal text with syntax highlighting via ANSI
  codes.

#### Implications for Web Control Surface

Since Claude Code renders to terminal via Ink/React, the raw terminal output
stream is ANSI-encoded text. A web control surface could:

1. **Option A**: Capture the raw PTY output and render it in xterm.js (faithful
   terminal reproduction).
2. **Option B**: Intercept the structured data (before Ink rendering) and render
   it with web-native components (richer, more interactive).
3. **Option C**: Hybrid -- xterm.js for command execution output, structured
   components for agent messages and tool calls.

### 3.2 Open WebUI Rendering Architecture

Open WebUI is the most mature open-source LLM chat interface and provides an
excellent reference implementation.

**Stack**: Svelte (frontend) + FastAPI (backend) + Socket.IO (real-time)

#### Content Rendering Pipeline (3 stages)

1. **Preprocessing**: Raw message content is cleaned and prepared.
2. **Token generation**: `marked.js` with custom extensions lexes content into
   tokens. Extensions handle: math formulas, citations, footnotes, mentions,
   specialized formatting.
3. **Recursive rendering**: `MarkdownTokens.svelte` dispatches each token type
   to its handler component.

#### Component Hierarchy

```
ContentRenderer.svelte (entry point)
  -> Markdown.svelte (configures marked.js, lexes tokens)
    -> MarkdownTokens.svelte (recursive token dispatcher)
      -> MarkdownInlineTokens.svelte (links, emphasis, strong, code, images)
      -> CodeBlock.svelte (syntax highlighted code with execution support)
      -> KaTeX (math formulas, inline + block)
      -> DOMPurify (HTML sanitization for XSS prevention)
```

#### Streaming Architecture

- **Backend**: Dual-proxy architecture for Ollama and OpenAI-compatible APIs.
  FastAPI async handlers stream responses. BackgroundTask ensures cleanup of
  aiohttp sessions after streaming.
- **Frontend**: Socket.IO delivers chunks in real-time. Markdown is re-parsed
  on each chunk (performance concern for large responses).

### 3.3 LLM Streaming Response Rendering (General Patterns)

#### The Core Challenge

Streaming markdown from an LLM arrives as character-by-character or word-by-word
chunks. Markdown syntax elements can span multiple chunks (e.g., a code fence
opening ` ``` ` in one chunk, content in subsequent chunks, closing ` ``` ` much
later). This makes naive per-chunk parsing impossible.

#### Chrome's Official Best Practices

Source: <https://developer.chrome.com/docs/ai/render-llm-responses>

1. **Do not use `textContent`**: Setting `textContent` destroys and recreates all
   child nodes on every update.
2. **Use streaming markdown parsers**: Common parsers (marked, markdown-it)
   assume complete documents. Use purpose-built streaming parsers.
3. **Sanitize the combined result, not individual chunks**: Dangerous code can be
   split across chunks. Use DOMPurify on the accumulated output.
4. **Batch DOM updates**: Accumulate chunks and flush on natural boundaries
   (newlines, paragraph breaks).

#### Streaming Modes

- **Full streaming**: Each event contains the entire response so far (wasteful
  for rendering but simpler to handle).
- **Incremental streaming**: Each event contains only the new delta (more
  efficient but requires accumulation logic).

### 3.4 Streaming Markdown Libraries

#### Streamdown (Vercel)

**Repository**: <https://github.com/vercel/streamdown>
**Website**: <https://streamdown.ai>
**Version**: v2

- Drop-in replacement for `react-markdown`, designed for AI streaming.
- Handles unterminated chunks, interactive code blocks, math.
- Plugin-based architecture in v2.
- Built-in caret/cursor indicators during streaming.
- Supports GFM, math (KaTeX), code highlighting, diagrams.
- **React only**.

#### Incremark

**Website**: <https://www.incremark.com>
**Packages**: `@incremark/core`, `@incremark/react`, `@incremark/vue`,
`@incremark/svelte`, `@incremark/solid`

- **O(n) incremental parsing** vs O(n^2) for traditional re-parse-everything
  approach.
- Key invariant: once a block is marked complete, it is never re-parsed.
- Up to **65x faster** on longer documents.
- Framework-agnostic core with framework-specific renderers.
- Supports GFM, Math, Mermaid, custom components.
- SSR support with Nuxt, Next.js, SvelteKit.

#### marked.js

**Repository**: <https://github.com/markedjs/marked>
**Website**: <https://marked.js.org>

- "Built for speed" -- fast one-shot parsing.
- Used by Open WebUI as the base parser.
- **No native streaming support**. Must re-parse entire accumulated content on
  each chunk, leading to O(n^2) behavior.
- Extensible via custom tokenizers and renderers.

#### markdown-it

**Repository**: <https://github.com/markdown-it/markdown-it>

- Consistent performance for 5K-100K character documents.
- Plugin ecosystem for math, footnotes, etc.
- `markdown-it-ts` variant shows strong one-shot parse latency.
- No native streaming support, but streaming path keeps append latency lower
  than full re-parse.

### 3.5 Component-Based Markdown Rendering

#### react-markdown

- Most popular React markdown component.
- Uses remark/rehype ecosystem under the hood.
- Supports custom component overrides for each element type.
- **No streaming optimization** -- re-renders entire tree on each update.
- Can be extended with MDX for embedding React components in markdown.

#### svelte-markdown

**Repository**: <https://github.com/pablo-abc/svelte-markdown>

- Inspired by react-markdown.
- Accepts `source` prop (string or pre-parsed tokens).
- Custom `renderers` prop maps node types to Svelte components.
- No streaming optimization.

#### llm-ui (React)

**Repository**: <https://github.com/richardgill/llm-ui>
**Website**: <https://llm-ui.com>

Purpose-built React library for rendering LLM output:

- **Throttled rendering**: Smooths out pauses by rendering at native frame rate.
- **Code blocks**: Uses Shiki for highlighting. Has `findCompleteCodeBlock()`,
  `findPartialCodeBlock()`, and `codeBlockLookBack()` for handling incomplete
  streaming code blocks.
- **Block pattern matching**: `useLLMOutput` hook matches patterns in streaming
  text and dispatches to appropriate block components.
- **Extensible**: Custom block types for tool calls, structured data (JSON, CSV).
- **Markdown + code blocks + custom components** all handled.

### 3.6 Diff Rendering

#### react-diff-view

**Repository**: <https://github.com/otakustay/react-diff-view>
**Version**: v3.3.2 (actively maintained)

- Consumes git unified diff output.
- Optimized for large diffs.
- React component API.
- Best choice for React-based dashboards.

#### diff2html

**Website**: <https://diff2html.xyz>

- Framework-agnostic: converts diff output to HTML.
- Uses highlight.js for syntax highlighting within diffs.
- Can be integrated into any framework.
- Side-by-side and line-by-line views.

#### react-diff-viewer

**Repository**: <https://github.com/praneshr/react-diff-viewer>
**Version**: v3.1.1 (last published 6 years ago -- effectively unmaintained)

- Simple API but abandoned.
- Use `react-diff-viewer-continued` fork or `react-diff-view` instead.

### 3.7 Distinguishing Agent Text vs Command Output

This is a UX design challenge, not purely a technical one. Approaches observed
in the wild:

1. **Visual framing**: Agent text in message bubbles, command output in terminal-
   styled containers (dark background, monospace font). Claude Code uses
   different styling for thinking, tool calls, and output.

2. **Structured protocol**: The agent sends structured events indicating content
   type (e.g., `{"type": "text", "content": "..."}` vs
   `{"type": "tool_result", "tool": "bash", "output": "..."}`). The renderer
   dispatches to different components based on type.

3. **Dual-channel rendering**: Agent reasoning/text rendered via markdown
   components; command/terminal output rendered via xterm.js or a terminal-styled
   component. Open WebUI uses `isMeta` flag on messages -- visible in transcript
   vs API-only context.

4. **Stream multiplexing**: Multiple named streams (stdout, stderr, agent_text,
   thinking) over a single WebSocket connection, each rendered to its appropriate
   container.

---

## Comparative Analysis and Recommendations

### Terminal Emulation

**Recommendation: xterm.js v5 (`@xterm/xterm`)**

No real alternatives exist at this quality level. Key addons to include:

- `@xterm/addon-fit` (required -- auto-resize)
- `@xterm/addon-webgl` (required -- GPU rendering)
- `@xterm/addon-search` (useful for agent output search)
- `@xterm/addon-serialize` (useful for session persistence)
- `@xterm/addon-web-links` (clickable URLs in output)

**Memory budget concern**: Plan for ~34MB per terminal instance at 5K scrollback.
For a multi-agent dashboard, cap scrollback at 1-2K lines and implement
persistence-to-storage for historical output.

### Syntax Highlighting

**Recommendation: Layered approach**

1. **Terminal context** (xterm.js): Let ANSI escape codes from tools like `bat`,
   `rich`, and agent CLI tools handle highlighting natively. No additional work
   needed.
2. **Code blocks in agent messages**: Use **Shiki** for high-quality VS Code-
   grade highlighting. Lazy-load it -- do not include in the initial bundle. The
   llm-ui library already integrates Shiki for this purpose.
3. **Embedded code viewers** (if needed): Use **CodeMirror 6** for interactive
   read-only code display with search, folding, and efficient updates. Avoid
   Monaco unless full editing is required.

### Agent Output / Markdown Streaming

**Recommendation: Incremark or Streamdown**

| Criteria | Incremark | Streamdown |
|----------|-----------|------------|
| **Performance** | O(n) incremental, 65x faster | Better than naive, details unclear |
| **Framework support** | React, Vue, Svelte, Solid | React only |
| **Maturity** | Newer, less battle-tested | Vercel-backed, production at scale |
| **Bundle size** | Small (core is framework-agnostic) | Smaller in v2 |
| **Custom components** | Supported | Supported (plugin architecture) |

If the control surface uses **Svelte** (like Open WebUI), choose **Incremark**
for its Svelte support and O(n) performance. If using **React**, either works,
but Streamdown has stronger production backing.

For **tool calls and structured output**, supplement with a pattern-matching
approach similar to llm-ui's `useLLMOutput` hook: detect structured blocks in
the stream (tool invocations, code blocks, thinking blocks) and dispatch them to
specialized components.

### Diff Rendering

**Recommendation: diff2html** for framework flexibility, or **react-diff-view**
if committed to React. Both are actively maintained and handle large diffs well.

### Overall Architecture Pattern

```
Agent Backend (A2A protocol)
    |
    | WebSocket (multiplexed streams)
    |
    v
Control Surface Frontend
    |
    +-- Agent Message Renderer
    |     +-- Streaming Markdown (Incremark/Streamdown)
    |     +-- Code Blocks (Shiki, lazy-loaded)
    |     +-- Tool Call Components (custom)
    |     +-- Thinking Block Components (collapsible)
    |     +-- Diff Viewer (diff2html)
    |
    +-- Terminal Emulator(s)
    |     +-- xterm.js with WebGL addon
    |     +-- One instance per agent terminal session
    |     +-- Serialize addon for session persistence
    |
    +-- Code Viewer (optional)
          +-- CodeMirror 6 (read-only mode)
          +-- For file inspection / code review features
```

### Key Risks and Mitigations

1. **Memory pressure from multiple xterm.js instances**: Mitigate with low
   scrollback limits, serialize-to-storage for history, and lazy terminal
   creation (only create when tab is active).

2. **Streaming markdown performance**: Traditional parsers (marked, markdown-it)
   degrade to O(n^2). Use Incremark or Streamdown to maintain O(n) rendering.

3. **Bundle size bloat**: Monaco alone is 2MB+ gzipped. Shiki adds 250KB+ WASM.
   Lazy-load everything that is not needed for initial render. CodeMirror 6 at
   124KB gzipped is the right trade-off for embedded code viewing.

4. **ANSI vs structured rendering conflict**: Solved by separating concerns --
   xterm.js handles ANSI natively, markdown renderer handles structured content.
   Never try to mix ANSI codes into HTML rendering.

---

## Sources

### xterm.js

- [xterm.js GitHub Repository](https://github.com/xtermjs/xterm.js)
- [xterm.js Official Site](https://xtermjs.org/)
- [xterm.js Addon Guide](https://xtermjs.org/docs/guides/using-addons/)
- [xterm.js Flow Control Guide](https://xtermjs.org/docs/guides/flowcontrol/)
- [xterm.js Releases](https://github.com/xtermjs/xterm.js/releases)
- [VS Code Terminal UI and Layout (DeepWiki)](https://deepwiki.com/microsoft/vscode/9.6-terminal-ui-and-layout)
- [VS Code Working with xterm.js Wiki](https://github.com/microsoft/vscode/wiki/Working-with-xterm.js/)
- [VS Code Terminal Advanced Docs](https://code.visualstudio.com/docs/terminal/advanced)
- [xterm.js Buffer Performance (GitHub Issue #791)](https://github.com/xtermjs/xterm.js/issues/791)
- [xterm.js Scrollback (GitHub Issue #518)](https://github.com/xtermjs/xterm.js/issues/518)
- [xterm.js Package Migration (GitHub Issue #4859)](https://github.com/xtermjs/xterm.js/issues/4859)
- [xterm.js Serialize Addon](https://github.com/xtermjs/xterm.js/tree/master/addons/addon-serialize)

### Syntax Highlighting

- [Shiki GitHub Repository](https://github.com/shikijs/shiki)
- [Shiki Documentation](https://shiki.style/guide/)
- [Shiki v1.0 Evolution (Nuxt Blog)](https://nuxt.com/blog/shiki-v1)
- [Comparing Web Code Highlighters (2025)](https://chsm.dev/blog/2025/01/08/comparing-web-code-highlighters)
- [npm Trends: highlight.js vs prismjs vs shiki](https://npmtrends.com/highlight.js-vs-prismjs-vs-shiki)
- [Tree-sitter GitHub Repository](https://github.com/tree-sitter/tree-sitter)
- [Tree-sitter WASM Integration (DeepWiki)](https://deepwiki.com/tree-sitter/tree-sitter/6-code-tags-system)
- [Monaco Editor GitHub](https://github.com/microsoft/monaco-editor)
- [Sourcegraph: Migrating from Monaco to CodeMirror](https://sourcegraph.com/blog/migrating-monaco-codemirror)
- [Replit: Betting on CodeMirror](https://blog.replit.com/codemirror)
- [bat Terminal Output (DeepWiki)](https://deepwiki.com/sharkdp/bat/5.3-terminal-output-and-ansi-processing)

### Agent Output Rendering

- [How Claude Code is Built (Pragmatic Engineer)](https://newsletter.pragmaticengineer.com/p/how-claude-code-is-built)
- [Claude Code Dependencies Analysis](https://www.southbridge.ai/blog/claude-code-an-analysis-dependencies)
- [Open WebUI Content Rendering Pipeline (DeepWiki)](https://deepwiki.com/open-webui/open-webui/5.2-application-layout)
- [Open WebUI Markdown System (DeepWiki)](https://deepwiki.com/open-webui/open-webui/4.1-request-processing-flow)
- [Chrome: Best Practices for Rendering Streamed LLM Responses](https://developer.chrome.com/docs/ai/render-llm-responses)
- [Streamdown GitHub (Vercel)](https://github.com/vercel/streamdown)
- [Streamdown Documentation](https://streamdown.ai/docs)
- [Incremark Website](https://www.incremark.com/)
- [Incremark: From O(n^2) to O(n)](https://dev.to/kingshuaishuai/from-on2-to-on-building-a-streaming-markdown-renderer-for-the-ai-era-3k0f)
- [llm-ui Website](https://llm-ui.com/)
- [llm-ui Code Block Docs](https://llm-ui.com/docs/blocks/code/)
- [react-diff-view GitHub](https://github.com/otakustay/react-diff-view)
- [diff2html Website](https://diff2html.xyz/)
- [Ink GitHub (React for CLI)](https://github.com/vadimdemedes/ink)
