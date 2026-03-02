---
adr_id: 018
title: "React + Tailwind + Figma Stack Migration"
date: 2026-02-28
status: Proposed
supersedes:
  - docs/adrs/005-frontend-rendering-stack.md
amends:
  - docs/adrs/007-tech-stack-deployment.md
  - docs/adrs/011-frontend-backend-contract.md
related:
  - docs/figma-integration/2026-28-02-figma-mcp-react-pivot-research.md
---

# ADR-018: React + Tailwind + Figma Stack Migration

**Date:** 2026-02-28
**Status:** Proposed

## 1. Context & Problem Statement

The Control Surface frontend was implemented in SvelteKit 5 (Runes) with
shadcn-svelte, as prescribed by ADR-005. While functional, this stack
creates a permanent translation layer between the authoritative design
source (Figma Make, which outputs React + Tailwind) and the codebase.

The Figma Make project (`EAs7Eh1lxKVzBqzke5HASU`) is the single source
of truth for the Control Surface UI. It outputs React + Tailwind v4 code
natively. Every design iteration in Figma Make produces React components
that must then be manually translated into Svelte 5 — a lossy,
time-consuming process that introduces drift between design and code.

Additionally, the Figma MCP server's `get_design_context` tool returns
React + Tailwind by default because "AI agents are commonly trained on
large amounts of web-based data" and this format preserves the highest
visual fidelity for LLM interpretation. The entire Figma toolchain
(Code Connect, MCP resources, design system rules) is optimized for
React-first workflows.

## 2. The Decision

**Deprecate the SvelteKit 5 frontend. Migrate to React + Tailwind v4
using the Figma MCP toolchain as the primary design-to-code pipeline.**

### 2.1 SvelteKit Deprecation

The existing SvelteKit 5 frontend at `src/ui/` (Runes stores, shadcn-svelte
components, layout system) is deprecated. No further development will
occur on the Svelte codebase. It will be removed once the React
implementation reaches feature parity.

### 2.2 New Frontend Stack

| Layer | Technology | Version | Purpose |
| ------- | ----------- | --------- | --------- |
| Framework | React | 18.3.x | UI rendering |
| Build | Vite | 6.x | Dev server + bundling |
| Styling | Tailwind CSS | 4.x (Oxide) | Utility-first CSS with OKLCH palette |
| Primitives | Radix UI | latest | Headless accessible components |
| Component Kit | shadcn/ui (React) | latest | Pre-built Radix + Tailwind components |
| Icons | Lucide React | 0.487+ | Icon system |
| Markdown | react-markdown + remark-gfm | 10.x | Streaming markdown rendering |
| Code Display | react-syntax-highlighter | 16.x | Code block highlighting |
| Routing | react-router | 7.x | Client-side SPA routing |
| Motion | motion (Framer) | 12.x | Animations and transitions |
| Server State | TanStack Query (React Query) | 5.x | REST caching, dedup, background refetch, mutations |
| Client State | Zustand | 5.x | WS-driven real-time state, UI state, chunk accumulation |
| Drag & Drop | react-dnd | 16.x | Tab reordering, panel resizing |
| Panels | react-resizable-panels | 2.x | Split-pane layout |
| Forms | react-hook-form | 7.x | Form state management |
| Toasts | sonner | 2.x | Notification system |

### 2.3 Design System

The design system is defined in `src/styles/theme.css` and sourced from
the Figma Make project. It uses:

- **OKLCH color space** with Tailwind v4 slate palette as the neutral scale
- **8-hue "Oxide" accent palette** (slate, sage, mauve, sand, copper, teal,
  sky, rose) with uniform L/C for terminal-consistent muted aesthetic
- **4 status colors** (success, warning, error, info) from Tailwind steps
  700 (light) / 400 (dark)
- **Inter** (sans) + **Cascadia Mono** / **JetBrains Mono** (mono) fonts
- **Component-specific radius tokens** (terminal, ui, bubble, control)
- **Full light/dark mode** via `.dark` class and `@custom-variant`
- **Oxide UI tokens** for sidebar, terminal, metadata, and icon surfaces
- **Keyboard-only focus rings** via `:focus-visible` with suppressed mouse
  outlines

All token values are derived from Tailwind CSS v4's OKLCH palette and
registered via `@theme inline` for Tailwind utility class generation.

## 3. Figma MCP Toolchain

The Figma MCP server is the bridge between design and code. It runs
locally via the Figma Desktop app at `http://127.0.0.1:3845/mcp`.

### 3.1 Make → MCP Resources

The Figma Make project exposes its entire source tree as MCP resources.
The agent calls `get_design_context` on a Make file to receive a file
index, then fetches individual files via `ReadMcpResourceTool` using
`file://figma/make/source/{fileKey}/{path}` URIs.

**File key:** `EAs7Eh1lxKVzBqzke5HASU`

This provides live access to:

- All React component source files (layout, stream, inspector, permission,
  ui primitives)
- CSS theme and style files
- TypeScript types and hooks
- Package manifest and build config
- Make guidelines

### 3.2 MCP Tools

| Tool | Works with Make | Purpose |
| ------ | ---------------- | --------- |
| `get_design_context` | Yes | Returns structured React + Tailwind code for a node/selection |
| `get_screenshot` | Yes | Visual reference capture |
| `get_metadata` | Design only | Sparse XML node map for large frame decomposition |
| `get_variable_defs` | Design only | Design token extraction |
| `get_code_connect_map` | Design only | Retrieves existing Code Connect mappings |
| `add_code_connect_map` | Design only | Creates node → component mappings |
| `create_design_system_rules` | N/A | Generates project rules file |
| `get_code_connect_suggestions` | Design only | Suggests component mappings |
| `send_code_connect_mappings` | Design only | Confirms suggested mappings |

### 3.3 Code Connect CLI

**Package:** `@figma/code-connect` (installed globally)

Code Connect maps Figma components to codebase components. When set up,
the MCP server's `get_design_context` output includes
`<CodeConnectSnippet>` wrappers with:

- Real import statements from the codebase
- Component usage snippets with prop mappings
- Custom implementation instructions

**CLI commands:**

```bash
# Interactive setup — scaffolds figma.config.json + .figma.tsx files
npx figma connect --token=$FIGMA_ACCESS_TOKEN

# Publish mappings to Figma (makes them visible in Dev Mode + MCP)
npx figma connect publish --token=$FIGMA_ACCESS_TOKEN

# Remove a specific mapping
npx figma connect unpublish --node=NODE_URL --label=React
```

**Configuration:** `figma.config.json` at project root defines:

- Component directory paths
- Figma Design library URL
- Import path mappings
- Code Connect file output directory

**Mapping files:** `*.figma.tsx` files that use `figma.connect()` to
declare prop mappings between Figma properties and React props:

```tsx
import figma from '@figma/code-connect'
import { Button } from '@/components/ui/button'

figma.connect(Button, 'https://figma.com/design/FILE?node-id=XX:YY', {
  props: {
    variant: figma.enum('Variant', {
      Primary: 'primary',
      Secondary: 'secondary',
    }),
    label: figma.string('Label'),
    disabled: figma.boolean('Disabled'),
  },
  example: (props) => (
    <Button variant={props.variant} disabled={props.disabled}>
      {props.label}
    </Button>
  ),
})
```

**Prop mapping functions:**

- `figma.string(prop)` — text → string
- `figma.boolean(prop)` — boolean toggle
- `figma.enum(prop, valueMap)` — variant → code values
- `figma.instance(prop)` — instance swap → nested component
- `figma.children(layerName)` — child layers
- `figma.className(parts[])` — Tailwind class concatenation

**Requirements:**

- Node.js 18+
- Personal access token with Code Connect: Write and File content: Read
- `FIGMA_ACCESS_TOKEN` environment variable (already in `.env`)

**Limitation:** Code Connect CLI mappings require a Figma Design file
with published library components (Organization/Enterprise plan). For
Make-only projects, use `add_code_connect_map` via the MCP server or
create a Design file from the Make project.

### 3.4 Design-to-Code Workflow

The canonical workflow for implementing or modifying any component:

```text
1. Figma Make (design source)
   │
   ├─► get_design_context → structured React + Tailwind reference code
   ├─► get_screenshot → visual reference
   ├─► ReadMcpResourceTool → fetch source files from Make project
   │
2. Implement in project
   │
   ├─► Use shadcn/ui primitives from src/components/ui/
   ├─► Apply project design tokens from theme.css
   ├─► Wire to real backend (WebSocket events, REST endpoints)
   │
3. Code Connect (feedback loop)
   │
   ├─► Create .figma.tsx mapping file
   ├─► npx figma connect publish
   └─► Now get_design_context returns YOUR component code
       for future iterations
```

### 3.5 Figma Skills (Claude Code Plugin)

Three skills are installed via the `figma@claude-plugins-official` plugin:

| Skill | Trigger | Purpose |
| ------- | --------- | --------- |
| `figma:implement-design` | Figma URLs, "implement design" | 7-step workflow: parse URL → get context → screenshot → assets → translate → validate |
| `figma:code-connect-components` | "code connect", "map component" | Scan codebase → match to Figma nodes → create mappings |
| `figma:create-design-system-rules` | "create design system rules" | Analyze codebase → generate CLAUDE.md rules |

### 3.6 CLAUDE.md Integration Rules

The following rules must be added to CLAUDE.md for all Figma-driven work:

```markdown
## Figma MCP Server Rules

- The Figma MCP server provides an assets endpoint serving images and SVGs
- IMPORTANT: If the server returns a localhost source for an image/SVG,
  use that source directly
- IMPORTANT: DO NOT import/add new icon packages — all assets come from
  the Figma payload
- IMPORTANT: DO NOT use or create placeholders if a localhost source is
  provided

## Figma Implementation Flow (mandatory, do not skip)

1. Run get_design_context first for the target node(s)
2. If response is too large, run get_metadata for the node map, then
   re-fetch only needed nodes with get_design_context
3. Run get_screenshot for visual reference
4. After both context + screenshot, download assets and implement
5. Translate React + Tailwind output to project conventions
6. Validate 1:1 against Figma screenshot before marking complete
```

## 4. Rationale

### 4.1 Why Deprecate SvelteKit

- **Translation overhead**: Every Figma Make iteration produces React code
  that must be manually translated to Svelte 5 Runes syntax. This is the
  dominant source of development friction.
- **Ecosystem alignment**: The Figma MCP toolchain (Code Connect, design
  system rules, implement-design skill) is React-first. Svelte support
  exists but is secondary.
- **Code Connect**: The CLI's interactive setup, AI prop mapping, and
  richest `<CodeConnectSnippet>` output target React. Svelte Code Connect
  exists but has fewer features.
- **Make Resources**: The Make project outputs React components directly.
  Using React eliminates the translation step entirely — components can be
  adapted rather than rewritten.
- **LLM affinity**: `get_design_context` returns React + Tailwind by
  default because this format is best understood by LLMs. Working in React
  means the MCP output is directly usable.

### 4.2 Why This Stack Specifically

- **Vite**: Already used by Figma Make. Same build tooling = zero config
  drift.
- **Tailwind v4 (Oxide)**: Already used by Figma Make. The design tokens
  in `theme.css` are defined using Tailwind v4's `@theme inline` and
  `@custom-variant`. No translation needed.
- **Radix UI + shadcn/ui**: Already used by Figma Make. The Make project
  ships 47 shadcn/ui primitives. These are drop-in.
- **React 18**: Figma Make targets React 18.3.1. Moving to 19 later is a
  separate decision.
- **TanStack Query v5**: Industry-standard server-state library for React
  (12M weekly npm downloads, 48K GitHub stars). Handles REST data fetching
  with automatic caching, request deduplication, background refetching,
  and stale-while-revalidate semantics. Experimental `streamedQuery` API
  supports chunk accumulation via custom reducers. ~16 KB gzipped.
- **Zustand v5**: Minimal hook-based client-state management (19M weekly
  npm downloads, 57K GitHub stars, ~1 KB gzipped). Its vanilla store API
  (`createStore` from `zustand/vanilla`) operates outside React — critical
  for the WebSocket event handler which dispatches high-frequency chunk
  events without React context. Selective subscriptions prevent render
  storms when one thread's stream updates. Immer middleware enables
  readable mutable-style chunk accumulation. Persist middleware handles
  theme/sidebar preferences across sessions.

#### State Management Split

The monolithic `use-app-state.ts` hook decomposes into two categories:

| Category | Owner | Examples |
| ---------- | ------- | --------- |
| **Server state** (REST) | TanStack Query | Thread list, team presets, team status, thread snapshots |
| **Client + real-time state** (WS) | Zustand | Stream events (chunk accumulation), tab system, theme, sidebar, inspector, permission queue, WS connection state |

The boundary is clean: TanStack Query caches REST responses and manages
mutations; Zustand holds the real-time event stream and all UI state.
The WebSocket event callback calls directly into the Zustand store via
`store.getState().handleWireEvent()` — no React dependency in the
dispatch path.

#### Rejected State Management Alternatives

- **RTK Query (Redux Toolkit)**: Requires buying into the full Redux
  ecosystem (~41 KB). Its streaming model assumes per-query WebSocket
  connections, but our architecture uses a single global WebSocket with
  per-thread subscriptions. Redux is declining in new React projects.
- **SWR (Vercel)**: Strictly less capable than TanStack Query — no
  mutations API, weaker cache control, no devtools. Optimized for
  Next.js, not SPA.
- **Jotai**: Atomic state model is a poor fit for array-of-events-per-
  thread data shapes. No vanilla store API for non-React WS handlers.
- **react-use-websocket**: Our custom `WebSocketClient` (243 lines)
  already handles reconnection, heartbeat, ping, sequence tracking, and
  our subscribe/unsubscribe protocol. The library adds a single-
  maintainer dependency without solving any unsolved problem.
- **Raw React hooks + context** (original ADR-018 §2.2): Works for
  prototyping but collapses into a monolithic 530-line hook. No caching,
  no dedup, no background refetch, no selective subscriptions.

### 4.3 Why Code Connect Matters

Without Code Connect, `get_design_context` returns generic React +
Tailwind that uses Figma's default component representations. With Code
Connect mappings published, the same tool returns `<CodeConnectSnippet>`
wrappers that include:

- Your actual import paths (`from '@/components/ui/button'`)
- Your actual prop interfaces and enum values
- Your actual usage patterns as the code example
- Custom instructions for edge cases

This closes the loop: Figma knows about your components, and generates
code that uses them.

## 5. Migration Plan

### Phase 1: Scaffold (immediate)

- Initialize React + Vite + Tailwind v4 project
- Pull `theme.css`, `tailwind.css`, `fonts.css`, `index.css` from Make
  via MCP resources
- Pull `package.json` dependencies from Make
- Set up shadcn/ui primitives (pull all 47 `ui/*.tsx` from Make)
- Run `create-design-system-rules` skill to generate CLAUDE.md rules

### Phase 2: Implement Components

- Pull each domain component from Make via MCP resources
- Adapt to project conventions (wire to real backend, replace mock data)
- Components: layout (AppShell, Sidebar, TabBar, StatusBar), stream
  (MessageStream, MessageBubble, ThoughtBlock, ToolCallCard, ArtifactCard,
  PlanUpdateCard, ErrorAlert, InputBar, MarkdownEditor), inspector
  (InspectorPanel), permission (PermissionModal)
- Types and hooks: adapt Make's `types.ts`, `use-app-state.ts` etc. to
  match the wire contract from ADR-011

### Phase 3: Code Connect

- Create `figma.config.json` pointing at component directory
- Generate `.figma.tsx` mapping files for all implemented components
- Publish via `npx figma connect publish`
- Verify `get_design_context` now returns project-specific snippets

### Phase 4: Cleanup

- Remove SvelteKit 5 codebase (`src/ui/` Svelte files, stores, routes)
- Remove Svelte-specific dependencies (shadcn-svelte, bits-ui, melt-ui,
  @humanspeak/svelte-markdown, etc.)
- Remove `svelte` MCP server from `.mcp.json`
- Update ADR-007 deployment section (static SPA build remains the same
  pattern, just React instead of SvelteKit)
- Update ADR-011 TypeScript type generation (still via openapi-typescript,
  consumed by React instead of Svelte stores)

## 6. Rejected Alternatives

- **Keep SvelteKit + translate from Figma**: Rejected. The translation
  layer is the core problem. Every Figma iteration requires manual Svelte
  conversion, creating permanent drift and slowing velocity.
- **Next.js / Remix**: Rejected. The deployment model (ADR-007) requires
  a static SPA bundled into a Python package. Server-side rendering is
  irrelevant — FastAPI serves the static build. Vite SPA is simpler and
  matches what Figma Make already produces.
- **Vue + Tailwind**: Rejected. Figma's MCP output defaults to React.
  Code Connect has the richest React support. The Make project outputs
  React. Choosing Vue would reintroduce a translation layer.
- **Remote MCP server instead of Desktop**: Rejected for now. Desktop
  server supports selection-based prompting (select a node in Figma, no
  URL needed) which is faster for iterative work. Remote server can be
  added later if needed.

## 7. Negative Consequences

- **Migration effort**: The existing SvelteKit frontend represents
  significant work (23 component files, 7 stores, full layout system).
  This work is not wasted — the component architecture and backend
  integration patterns carry over — but the Svelte-specific code must be
  rewritten.
- **Svelte expertise**: Any team Svelte expertise becomes less relevant
  for this project.
- **React bundle size**: React's runtime (~40KB gzipped) is larger than
  Svelte's compiled output. Acceptable for a developer tool SPA.
- **Two UI frameworks temporarily**: During migration, both Svelte and
  React code will coexist. The Svelte code is frozen (no new work) but
  remains until React reaches parity.

## 8. Rate Limits

Figma MCP server tool calls are rate-limited:

| Plan | Seat | Daily Limit | Per-Minute |
| ------ | ------ | ------------- | ------------ |
| Enterprise | Full/Dev | 600/day | 20/min |
| Organization/Pro | Full/Dev | 200/day | 15/min |
| Starter | Any | 6/month | — |

Exempt tools (no rate limit): `add_code_connect_map`,
`generate_figma_design`, `whoami`.

## 9. Environment Variables

| Variable | Purpose |
| ---------- | --------- |
| `FIGMA_ACCESS_TOKEN` | Authenticates Code Connect CLI and MCP tools. Stored in `.env`. Requires Code Connect: Write + File content: Read scopes. |

## 10. References

- [Figma MCP Server Docs](https://developers.figma.com/docs/figma-mcp-server/)
- [Make → MCP Resources](https://developers.figma.com/docs/figma-mcp-server/bringing-make-context-to-your-agent/)
- [Code Connect Integration](https://developers.figma.com/docs/figma-mcp-server/code-connect-integration/)
- [Code Connect CLI Quickstart](https://developers.figma.com/docs/code-connect/quickstart-guide/)
- [Figma MCP Server Guide (GitHub)](https://github.com/figma/mcp-server-guide)
- Figma Make project: `https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface`
