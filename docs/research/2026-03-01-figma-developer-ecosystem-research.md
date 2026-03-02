---
name: "Figma Developer Ecosystem Research"
date: 2026-03-01
type: research
summary: >
  Comprehensive research into the Figma developer ecosystem: Code Connect (UI/CLI),
  Figma MCP Server (Remote/Desktop), Figma Make, Figma Design API, and their
  bidirectional workflows. Evaluated for React + TanStack + Tailwind CSS pivot
  from Svelte. Covers three bidirectional scenarios and architectural implications.
status: active
supersedes:
  - docs/adrs/005-frontend-rendering-stack.md (Svelte → React pivot)
companions:
  - docs/figma/2026-03-01-figma-make-research.md
  - docs/research/2026-03-01-figma-design-api-research.md
related:
  - docs/adrs/011-frontend-backend-contract.md
  - docs/plans/2026-02-26-frontend-ui-spec.md
  - docs/distilled/2026-25-02-control-surface-distilled.md
feature: figma-developer-ecosystem
---

# Figma Developer Ecosystem Research

**Date**: 2026-03-01
**Status**: Active Research
**Scope**: Code Connect, Figma MCP Server, Figma Make, Figma Design API,
bidirectional design ↔ code workflows. Framework pivot: Svelte → React +
TanStack + Tailwind CSS.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Figma Code Connect](#2-figma-code-connect)
3. [Figma MCP Server](#3-figma-mcp-server)
4. [Figma Make](#4-figma-make)
5. [Figma Design API & Variables](#5-figma-design-api--variables)
6. [Bidirectional Workflow Analysis](#6-bidirectional-workflow-analysis)
7. [React + TanStack + Tailwind Pivot](#7-react--tanstack--tailwind-pivot)
8. [shadcn/ui Figma Ecosystem](#8-shadcnui-figma-ecosystem)
9. [Dev Mode Codegen Plugins](#9-dev-mode-codegen-plugins)
10. [Architectural Implications](#10-architectural-implications)
11. [Plan & Access Requirements](#11-plan--access-requirements)
12. [Open Questions & Risks](#12-open-questions--risks)
13. [References](#13-references)

---

## 1. Executive Summary

Figma's developer ecosystem as of March 2026 consists of four interlocking
tools that form a bidirectional design-to-code pipeline:

| Tool | Direction | Purpose |
| ------ | ----------- | --------- |
| **Code Connect** (UI/CLI) | Code → Figma Dev Mode | Maps codebase components to Figma components, providing real code snippets in Dev Mode |
| **MCP Server** (Remote/Desktop) | Figma → Code (AI-mediated) | Exposes structured design context to AI coding agents for design-informed code generation |
| **Figma Make** | Prompt → Code/Prototype | AI-powered prompt-to-code capability generating working prototypes from designs or text |
| **Design API** (REST + Plugin) | Bidirectional (Enterprise) | Programmatic read/write access to files, components, variables, and styles |

The **canonical workflow loop** is:

```text
Figma Design → MCP Server → AI Agent → Local Code → Code Connect → Figma Dev Mode
       ↑                                                                    |
       └────────── generate_figma_design (code → canvas) ──────────────────┘
```

**Critical pivot**: This research evaluates the ecosystem for **React +
TanStack + Tailwind CSS** instead of Svelte. The MCP server's default output
is React + Tailwind, making this pivot naturally aligned with Figma's tooling.

---

## 2. Figma Code Connect

### 2.1 What It Is

Code Connect is a bridge between a codebase and Figma's Dev Mode. It connects
components in code repositories directly to components in Figma design files.
When a developer inspects a component in Dev Mode, they see the actual
production code snippet instead of auto-generated boilerplate.

Code Connect also **enhances the MCP server**: when mappings exist, the MCP
server provides AI agents with direct references to actual code implementations
rather than generic React + Tailwind output.

### 2.2 Two Implementation Methods

#### Code Connect UI (In-Figma)

- Runs entirely inside Figma
- Connects directly to GitHub repositories
- Language-agnostic
- Supports automated mapping suggestions (AI-assisted)
- Available on Organization and Enterprise plans (GA at Schema 2025)
- Ideal for teams wanting visual, low-friction setup

#### Code Connect CLI (Local)

- Runs locally in the developer's repository
- Interactive setup via `npx figma connect`
- Supports property mappings and dynamic code examples
- More precision and flexibility than UI approach
- Publishes mappings to Figma via `npx figma connect publish`

### 2.3 CLI Commands

```bash
# Install globally
npm install --global @figma/code-connect@latest

# Interactive setup (scaffolds .figma.tsx files)
npx figma connect --token=<PAT>

# Publish mappings to Figma Dev Mode
npx figma connect publish --token=<PAT>

# Remove published mappings
npx figma connect unpublish --node=<NODE_URL> --label=<LABEL>
```

**Authentication**: Personal Access Token with "Code Connect: Write" and
"File content: Read" scopes. Can use `FIGMA_ACCESS_TOKEN`env var.

**Requirements**: Node.js 18+, valid Figma PAT.

### 2.4 Configuration:`figma.config.json`

Generated during interactive setup. Contains `documentUrlSubstitutions`
mapping file keys to Figma file URLs.

### 2.5 React Code Connect Syntax

Code Connect files use `figma.connect()` with the following signature:

```tsx
import figma from "@figma/code-connect/react";
import { Button } from "./Button";

figma.connect(Button, "https://figma.com/design/<fileKey>?node-id=<nodeId>", {
  props: {
    label: figma.string("Text Content"),
    disabled: figma.boolean("Disabled"),
    variant: figma.enum("Type", {
      Primary: "primary",
      Secondary: "secondary",
    }),
    icon: figma.instance("Icon"),
    children: figma.children("*"),
  },
  example: ({ label, disabled, variant, icon }) => (
    <Button disabled={disabled} variant={variant} icon={icon}>
      {label}
    </Button>
  ),
});
```

**Arguments to `figma.connect()`**:

1. The imported component from the codebase
2. The Figma node URL
3. Configuration object with `props`mappings and`example`function

### 2.6 Property Mapping Helpers

| Helper | Purpose | Example |
| -------- | --------- | --------- |
| `figma.string("Prop")` | Map text content | Labels, titles |
| `figma.boolean("Prop")` | Map boolean toggle | `{true: <Icon/>, false: <Spacer/>}` |
| `figma.enum("Prop", {...})` | Map variant options | Figma variants → code values |
| `figma.instance("Prop")` | Map nested component swap | Returns JSX element |
| `figma.children("Name")` | Map nested instances | Supports wildcards`"*"` |
| `figma.nestedProps("Prop", {...})` | Map child instance properties at parent | Composition patterns |
| `figma.textContent("Layer")` | Extract text from child layer | Static text content |
| `figma.className([...])` | Concatenate CSS classes | Tailwind utility classes |

**Advanced**:`figma.instance("Prop").getProps<T>()` to access child props,
`figma.instance("Prop").render<T>(props => ...)` for conditional rendering.

### 2.7 Variant Restrictions

Different code components can be connected to specific Figma variants:

```tsx
figma.connect(PrimaryButton, "https://...", {
  variant: { Type: "Primary" },
  example: () => <PrimaryButton />,
});

figma.connect(SecondaryButton, "https://...", {
  variant: { Type: "Secondary" },
  example: () => <SecondaryButton />,
});
```

### 2.8 Key Constraint

**Code Connect files are NOT executed.** They are treated as string templates
by the Figma CLI. Ternaries, conditionals, and loops render verbatim rather
than being evaluated. No dynamic `figma.connect()`construction in loops.

### 2.9 File Naming Convention

Generated files follow:`component-name.figma.tsx`

### 2.10 Supported Frameworks

- React / React Native
- HTML (Web Components, Angular, Vue)
- SwiftUI
- Jetpack Compose
- Storybook integration
- Template files for non-parser approaches

---

## 3. Figma MCP Server

### 3.1 What It Is

The Figma MCP (Model Context Protocol) Server is a service that exposes
structured Figma design data to AI coding agents through the standardized MCP
interface. It brings design context directly into coding tools (Claude Code,
Cursor, VS Code Copilot, Windsurf, Codex).

### 3.2 Two Deployment Models

#### Remote MCP Server

- **Endpoint**: `https://mcp.figma.com/mcp`
- OAuth authentication via Figma login
- No desktop app required
- Available on all seats and plans (tiered rate limits)
- Supports `generate_figma_design` (code → canvas, Claude Code/Codex only)
- Link-based prompting (paste Figma URLs)

**Claude Code setup**:

```bash
claude mcp add --transport http figma https://mcp.figma.com/mcp
```

#### Desktop MCP Server

- **Endpoint**: `http://127.0.0.1:3845/mcp`
- Runs locally through Figma desktop app
- Requires Dev Mode (Shift+D to enable)
- Supports selection-based prompting (select layer → prompt)
- Requires Dev or Full seat on paid plans
- Better for interactive design-to-code workflows

### 3.3 Tool Inventory (13 Tools)

| Tool | Server | Purpose |
| ------ | -------- | --------- |
| `get_design_context` | Both | Structured React + Tailwind representation of selection. Customizable framework output. Works with Figma Design and Make files |
| `get_variable_defs` | Both | Extracts variables and styles (color, spacing, typography tokens) |
| `get_code_connect_map` | Both | Retrieves Code Connect mappings (returns`codeConnectSrc`and`codeConnectName`) |
| `add_code_connect_map` | Both | Adds a mapping between Figma node ID and code component |
| `get_code_connect_suggestions` | Both | AI-detects and suggests Code Connect mappings |
| `send_code_connect_mappings` | Both | Confirms Code Connect mappings after review |
| `get_screenshot` | Both | Takes screenshot of selection for visual reference |
| `get_metadata` | Both | Sparse XML representation (layer IDs, names, types, positions, sizes) for large designs |
| `create_design_system_rules` | Both | Creates rule files for design-to-code translation guidance |
| `get_figjam` | Both | Converts FigJam diagrams to XML with screenshots |
| `generate_diagram` | Both | Generates FigJam diagrams from Mermaid syntax |
| `generate_figma_design` | Remote only | **Code → Canvas**: captures live UI and creates editable Figma layers. Claude Code and Codex only |
| `whoami` | Remote only | Returns authenticated user identity and plan info |

### 3.4 Default Output & Code Connect Enhancement

`get_design_context`returns **React + Tailwind** by default. This is
critical for our pivot: the MCP server natively speaks our target stack.

When Code Connect mappings exist, the MCP server **replaces generic output**
with references to actual codebase components. This means:

- Without Code Connect: generic`<div className="...">`output
- With Code Connect:`<Button variant="primary">`using your actual components

The Desktop MCP server uses the Code Connect mapping selected in Dev Mode.
The Remote MCP server accepts a`clientFrameworks`parameter to specify which
Code Connect label to use (e.g., "React").

### 3.5 Rate Limits

| Plan | Limit |
| ------ | ------- |
| Starter / View / Collab seats | 6 tool calls per month |
| Dev / Full seat (Professional+) | Per-minute limits (Tier 1 Figma REST API) |

### 3.6 Skills (Agent Guidance)

The MCP server also provides "Skills" — agent-level guidance documents for
workflows including:

- Design-to-code translation
- Design system alignment
- Component connection

Skills provide context without replacing MCP tool functionality.

---

## 4. Figma Make

### 4.1 What It Is

Figma Make is an AI-powered prompt-to-code capability announced at Config 2025
(May 2025) and GA as of August 2025. Powered by Anthropic's Claude, it
generates working code from natural language prompts and/or Figma design frames.

### 4.2 Core Capabilities

- **Prompt-to-code**: Natural language → working prototype
- **Design-to-code**: Select a Figma frame → generate code
- **Visual context support**: Accepts screenshots, Figma frames, or images
- **Chat-based iteration**: Conversational refinement with AI
- **Built-in code editor**: Inspect, tweak, and export generated code
- **NPM package imports**: Import production React design systems (Schema 2025)
- **Design library import**: Bring Figma libraries for consistent look/feel
- **Supabase integration**: Connect to backend database
- **Publish to Figma Sites**: Ship prototypes live

### 4.3 Code Output

Figma Make primarily generates **HTML/CSS/JS** and **React** code. It uses
React as its internal code generation framework. The output is designed for
prototyping rather than production code, though with NPM imports and design
system integration, the fidelity is increasing.

### 4.4 Design System Integration (Schema 2025)

- **Make Kits** (Early Access): Import Figma Design libraries into Make to
  generate high-quality prototypes and React code using design system components
- **NPM Package Imports**: Bring production React design systems into Make
  prototypes, ensuring code uses the same components as production
- **MCP Context**: The MCP server can gather code resources from Make files
  and provide them as context to coding agents

### 4.5 Make → MCP → Code Pipeline

Make prototypes can be consumed by the MCP server as context. When a developer
works with the MCP server in their IDE, Make files provide additional context
about intended behavior and interactions that pure static designs don't capture.

### 4.6 Limitations

- Output optimized for prototyping, not production architecture
- No direct TanStack Router/Query integration
- Chat-based iteration can be slow for precise changes
- Generated code may not follow existing codebase conventions without
  Code Connect context

---

## 5. Figma Design API & Variables

### 5.1 REST API Overview

The Figma REST API provides programmatic access to Figma files, components,
styles, variables, and more. Key endpoint categories:

| Category | Endpoints | Access |
| ---------- | ----------- | -------- |
| Files | GET file, GET file nodes, GET images | All plans |
| Components | GET team components, GET file components | All plans |
| Styles | GET team styles, GET file styles | All plans |
| Variables | GET/POST/DELETE local variables | **Enterprise only** |
| Comments | GET/POST comments | All plans |
| Webhooks | POST/GET/DELETE webhooks | All plans |
| Version history | GET file versions | All plans |

### 5.2 Variables API (Enterprise Only)

### This is the most critical API for bidirectional token sync

The Variables REST API supports full CRUD:

- **GET**`/v1/files/:file_key/variables/local`— Read all variables
- **POST**`/v1/files/:file_key/variables`— Create/update/delete variables

Variable types:`BOOLEAN`, `FLOAT`, `STRING`, `COLOR`

Supports:

- Variable aliases (referencing other variables)
- Mode values (light/dark/brand variants)
- Extended collections (Schema 2025: child collections inheriting from parent)
- Scoping (which properties a variable can be applied to)

**Critical limitation**: Variables REST API requires **Enterprise plan**.
This is a major pain point in the community. Non-Enterprise users must use
plugin-based workarounds (Figma Token Exporter, Tokens Studio).

### 5.3 Plugin API vs REST API

| Aspect | Plugin API | REST API |
| -------- | ----------- | ---------- |
| Runs in | Figma browser/desktop | External servers/CI |
| Authentication | Plugin sandbox | Personal Access Token |
| Variables | All plans | Enterprise only |
| Write access | Full (within plugin) | Full (Enterprise) |
| Real-time | Yes | No (polling/webhooks) |
| Automation | Manual trigger | CI/CD compatible |

### 5.4 Design Token Sync Workflow

For bidirectional variable/token synchronization:

```text
Figma Variables ←→ REST API ←→ Token Transform ←→ CSS Custom Properties / Tailwind Config
```

Figma provides a GitHub Action example for automated sync:

1. Figma variables change → webhook fires
2. CI reads variables via REST API
3. Transform to CSS custom properties or `tailwind.config.ts`tokens
4. Commit to repository
5. (Reverse) Code tokens change → CI writes to Figma via REST API

### 5.5 Webhooks

Figma webhooks notify external systems of changes:

-`FILE_UPDATE`— File saved
-`FILE_VERSION_UPDATE`— New version created
-`FILE_COMMENT`— Comment added
-`LIBRARY_PUBLISH`— Library published

Useful for triggering CI/CD pipelines when designs change.

### 5.6 Schema 2025 Variables Updates

- **Extended collections**: Parent-child inheritance for multi-brand systems
- **Increased mode limits**: Professional 10/collection, Organization
  20/collection
- **Check Designs linter**: Auto-surfaces raw values and suggests variable
  substitutions
- **Performance**: Variable updates 30-60% faster, heavy state swaps 3500ms →
  350ms
- **Deleted variable tracking**: API marks`deletedButReferenced` variables

---

## 6. Bidirectional Workflow Analysis

### 6.1 Scenario 1: Figma Make → Local Code → Figma Design

**Flow**:

```text
Figma Make (prototype) → MCP Server → AI Agent (Claude Code) → Local React Code
                                                                       ↓
                                                              Code Connect publish
                                                                       ↓
                                                              Figma Dev Mode (snippets)
```

**Steps**:

1. Designer creates interactive prototype in **Figma Make** using prompts
   and/or design frames
2. Developer opens IDE with **MCP Server** configured (remote + desktop)
3. Developer pastes Make file URL → `get_design_context`returns React +
   Tailwind representation
4. AI agent generates production React components using actual codebase
   conventions (enhanced by existing Code Connect mappings)
5. Developer refines code locally
6.`npx figma connect publish`pushes Code Connect mappings back to Figma
6. In Figma Dev Mode, designers and other developers see the actual
   production code snippets

**Bidirectionality assessment**:

- **Make → Code**: Strong. MCP server natively outputs React + Tailwind.
  Make files are consumable as MCP context.
- **Code → Figma Dev Mode**: Strong via Code Connect CLI publish.
- **Code → Figma Canvas**: Possible via`generate_figma_design` (Remote MCP,
  Claude Code/Codex only). Captures live UI as editable Figma layers.
- **Gap**: Make prototypes and final production code will diverge. Make is
  optimized for prototyping, not production architecture. The divergence
  grows with application complexity.

### 6.2 Scenario 2: Figma Design → Local Code

**Flow**:

```text
Figma Design (components, variables, auto-layout)
       ↓
MCP Server: get_design_context + get_variable_defs + get_code_connect_map
       ↓
AI Agent (Claude Code / Cursor / VS Code Copilot)
       ↓
Local React + TanStack + Tailwind Code
       ↓
Code Connect publish → Figma Dev Mode
```

**Steps**:

1. Designer marks component/frame "Ready for dev" in Figma Design
2. Developer selects frame in Figma (Desktop MCP) or pastes URL (Remote MCP)
3. AI agent calls `get_design_context`→ receives React + Tailwind
   representation
4. AI agent calls`get_variable_defs`→ receives design tokens
   (color, spacing, typography)
5. AI agent calls`get_code_connect_map`→ checks for existing mappings
6. Agent generates code using actual codebase components and design tokens
7. Developer reviews, refines, commits
8.`npx figma connect publish`updates Dev Mode snippets
8. Optional:`create_design_system_rules`to persist agent guidance

**Bidirectionality assessment**:

- **Design → Code**: Very strong. This is the primary supported workflow.
  The MCP server's native React + Tailwind output aligns perfectly with
  our stack.
- **Code → Dev Mode**: Strong via Code Connect.
- **Tokens → Code**: Strong via`get_variable_defs`. Can map directly to
  Tailwind CSS variables.
- **Code → Tokens**: Requires Enterprise plan (Variables REST API) for
  automated sync. Non-Enterprise must use plugin workarounds.
- **Gap**: `get_design_context` output is a starting point, not production
  code. Complex state management (TanStack Query), routing (TanStack Router),
  and business logic must be added manually.

### 6.3 Scenario 3: Local Code → Figma Design → Changes → Figma → Local Code

**Flow**:

```text
Local React Code (production)
       ↓
generate_figma_design (Remote MCP, Claude Code)
       ↓
Figma Canvas (editable layers with auto-layout)
       ↓
Designer modifies (spacing, colors, layout, new elements)
       ↓
MCP Server: get_design_context (captures modifications)
       ↓
AI Agent generates updated code reflecting design changes
       ↓
Developer merges updates into codebase
```

**Steps**:

1. Developer has working React code with browser preview
2. In Claude Code: "Send this to Figma" → `generate_figma_design`
   captures live UI as editable Figma layers
3. Designer receives editable Figma frames: text is editable, buttons are
   components, layout uses auto-layout
4. Designer makes modifications (recolor, respace, add elements, rearrange)
5. Developer re-fetches via MCP: `get_design_context`on modified frames
6. AI agent generates diff/patch reflecting design changes
7. Developer reviews and merges

**Bidirectionality assessment**:

- **Code → Canvas**: Available via`generate_figma_design`, but
  **Claude Code and Codex only** (Remote MCP). Captures visual layers,
  not code logic.
- **Canvas → Code (round-trip)**: Functional but lossy. Figma layers
  don't carry business logic, event handlers, or state management. The AI
  must re-translate visual changes into implementation.
- **Key friction**: Each handoff loses information. Five context switches
  minimum (Code → Browser → Figma → Browser → Code). Figma captures
  structure and styling but not React component boundaries, props, or
  state.
- **Gap**: This is the weakest bidirectional link. Without Code Connect
  context, the round-trip produces generic code. With Code Connect,
  quality improves significantly but still requires manual reconciliation.

### 6.4 Bidirectionality Matrix

| Direction | Mechanism | Strength | Plan Requirement |
| ----------- | ----------- | ---------- | ----------------- |
| Figma Design → Code | MCP `get_design_context` | **Strong** | Dev/Full seat |
| Figma Design → Tokens | MCP`get_variable_defs` | **Strong** | Dev/Full seat |
| Code → Figma Dev Mode | Code Connect CLI`publish` | **Strong** | Org/Enterprise |
| Code → Figma Canvas | MCP`generate_figma_design` | **Moderate** (lossy) | Remote MCP + Claude Code/Codex |
| Tokens → Figma Variables | REST API POST variables | **Strong** (full CRUD) | **Enterprise only** |
| Figma Make → Code | MCP (Make files as context) | **Moderate** | Make plan |
| Code → Code Connect mappings | MCP`add_code_connect_map` | **Strong** | Org/Enterprise |
| Design changes → Code update | MCP round-trip | **Weak** (manual reconciliation) | Dev/Full seat |

---

## 7. React + TanStack + Tailwind Pivot

### 7.1 Why This Pivot Aligns with Figma

The pivot from Svelte to React + TanStack + Tailwind is **naturally aligned**
with Figma's developer ecosystem:

1. **MCP default output is React + Tailwind**:`get_design_context` natively
   returns React + Tailwind code. No framework translation needed.
2. **Code Connect has first-class React support**: React is the primary
   supported framework with the richest property mapping API.
3. **Figma Make uses React internally**: Make generates React code, making
   Make → production code transitions smoother.
4. **shadcn/ui has extensive Figma ecosystem**: Multiple maintained Figma
   kits with 1:1 component mapping (see §8).
5. **Community momentum**: The vast majority of Figma-to-code tooling
   targets React + Tailwind.

### 7.2 TanStack Integration Considerations

TanStack libraries (Router, Query, Table, Form) operate at the **data and
routing layer**, not the component rendering layer. This means:

- **TanStack Router**: Not visible to Figma. Routes and navigation are code
  concerns. Figma designs map to route components/pages.
- **TanStack Query**: Not visible to Figma. Data fetching and caching are
  code concerns. Figma designs define the UI that displays fetched data.
- **TanStack Table**: Partially visible. Table layouts in Figma can map to
  TanStack Table column definitions via Code Connect.
- **TanStack Form**: Partially visible. Form layouts in Figma can map to
  TanStack Form field configurations via Code Connect.

The MCP server generates the **visual component layer**. TanStack concerns
are added during the developer refinement step after initial code generation.

### 7.3 Updated Frontend Loop

The previous loop was: Figma → shadcn-ui → Svelte MCP → implement → browser

The new loop is:

```text
Figma Design/Make
       ↓
MCP Server (get_design_context → React + Tailwind)
       ↓
Code Connect (check existing mappings)
       ↓
shadcn/ui (verify component library alignment)
       ↓
Implement (React + TanStack + Tailwind)
       ↓
Browser verification (Playwright / Chrome DevTools)
       ↓
Code Connect publish (back to Figma)
```

### 7.4 Impact on Existing ADRs

| ADR | Impact |
| ----- | -------- |
| ADR-005 (Frontend Rendering Stack) | **Superseded**: SvelteKit → React + TanStack. shadcn-svelte → shadcn/ui. Svelte Runes → React hooks/signals |
| ADR-009 (Module Hierarchy) | **Update needed**: `src/ui/` structure changes from SvelteKit to React project |
| ADR-011 (Wire Contract) | **Minimal impact**: TypeScript types remain the same. WebSocket client unchanged. REST client unchanged |
| Frontend UI Spec | **No impact**: Layout, components, interactions are framework-agnostic. Only implementation details change |

### 7.5 Equivalent Library Mapping

| Svelte Ecosystem | React + TanStack Ecosystem |
| ----------------- | --------------------------- |
| SvelteKit | TanStack Router + Vite |
| Svelte 5 Runes (`$state`, `$derived`, `$effect`) | React hooks (`useState`, `useMemo`, `useEffect`) or signals library |
| shadcn-svelte | shadcn/ui (React) |
| Bits UI | Radix UI |
| `@humanspeak/svelte-markdown` | `react-markdown`+`remark-gfm` |
| Svelte stores | TanStack Query (server state) + Zustand/Jotai (client state) |
| SvelteKit adapter-static | Vite build (SPA) |

---

## 8. shadcn/ui Figma Ecosystem

### 8.1 Available Figma Kits

The shadcn/ui React library has a rich Figma ecosystem:

| Kit | Maintainer | Components | License | Notes |
| ----- | ----------- | ------------ | --------- | ------- |
| **shadcn/ui Design System** (Community) | Pietro Schirano | All core | Free | Mirrors code implementation exactly |
| **Obra shadcn/ui** | Obra Studio | All core | MIT | Maintained team, design-to-code plugin |
| **shadcndesign.com** | Matt Wierzbicki | 2000+ | Premium | Auto-layout, variants, Tailwind CSS variables |
| **Shadcraft** | Shadcraft | 28 Pro + 25 blocks | Premium | Theme swapping plugin, tweakcn integration |
| **Shadcn Studio** | Shadcn Studio | 1000+ variants | Premium | Motion, theme generator, MCP integration, Figma-to-code plugin |
| **Shadcnblocks** | Shadcnblocks | Block designs | Premium | Tailwind palette, component tokens |

### 8.2 Design Token Alignment

shadcn/ui Figma kits typically provide:

- Tailwind color palette as Figma variables
- shadcn theme variables (CSS custom properties)
- Typography scale
- Spacing system
- Component-level tokens

These map directly to`tailwind.config.ts`and CSS custom properties in code,
enabling the`get_variable_defs`MCP tool to return tokens that are 1:1 with
the codebase's token system.

### 8.3 Recommended Setup

For our project, the recommended approach is:

1. **Start with the free Pietro Schirano design system** on Figma Community
   (exact mirror of shadcn/ui code)
2. **Set up Code Connect mappings** from our codebase to the Figma components
3. **Map Figma variables** to our Tailwind CSS custom properties
4. **Publish Code Connect** so MCP returns our actual components

---

## 9. Dev Mode Codegen Plugins

### 9.1 How Codegen Plugins Work

Figma Dev Mode supports "codegen" plugins that appear in the native language
dropdown in the Inspect panel. When a user selects a layer, the plugin
generates code and renders it alongside Figma's native code snippets.

Plugin manifest requirements:

-`"editorType": ["dev"]`

- `"capabilities": ["codegen"]`
- `"codegenLanguages"`to specify supported output (e.g., React)
-`"codegenPreferences"`for user customization options

### 9.2 Relevant React Codegen Plugins

| Plugin | Output | Notes |
| -------- | -------- | ------- |
| **Anima** | React + Tailwind/CSS/SCSS | Variant/props support, interactive components, responsive flexbox |
| **Builder.io** | React + Tailwind | AI-powered, trains on codebase style, chat refinement |
| **Locofy.ai** | React / Next.js / Gatsby | Pixel-perfect, component-based, 240K+ users |
| **Figroot** | React + Tailwind | Free, no special design file setup required |
| **DhiWise** | React / Next.js / React Native | Auto-layout aware, variant support |
| **Replit** | React | Direct iteration with natural language prompts |

### 9.3 Codegen Plugins vs MCP Server vs Code Connect

| Aspect | Codegen Plugin | MCP Server | Code Connect |
| -------- | --------------- | ------------ | -------------- |
| Runs in | Figma Dev Mode (Inspect panel) | AI coding agent (IDE) | CLI / Figma UI |
| Trigger | Layer selection | Agent prompt / URL | `npx figma connect publish` |
| Output | Framework-specific code | React + Tailwind (default) | Code snippets in Dev Mode |
| Customization | Plugin preferences | Prompt engineering | Property mappings |
| Codebase awareness | Limited (some train on style) | Via Code Connect mappings | Direct codebase reference |
| Direction | Design → Code | Design → Code | Code → Design (Dev Mode) |
| AI-powered | Some (Builder.io, Anima) | Yes (agent-mediated) | No (deterministic) |

**Recommendation**: Codegen plugins are useful for quick one-off conversions
but lack the codebase awareness that MCP + Code Connect provides. For our
workflow, the MCP server is the primary tool with Code Connect providing the
bridge back to Figma. Codegen plugins are supplementary.

---

## 10. Architectural Implications

### 10.1 Dual MCP Server Configuration

For the full bidirectional experience, configure **both** servers:

```json
{
  "mcpServers": {
    "figma-remote": {
      "url": "https://mcp.figma.com/mcp",
      "type": "http"
    },
    "figma-desktop": {
      "url": "http://127.0.0.1:3845/mcp",
      "type": "http"
    }
  }
}
```

- **Remote**: For `generate_figma_design` (code → canvas), link-based prompting
- **Desktop**: For selection-based prompting, real-time design inspection

### 10.2 Code Connect Directory Structure

```text
src/ui/
├── components/
│   ├── ui/                          # shadcn/ui primitives
│   │   ├── button.tsx
│   │   ├── button.figma.tsx         # Code Connect mapping
│   │   ├── card.tsx
│   │   ├── card.figma.tsx
│   │   └── ...
│   ├── chat/                        # Domain components
│   │   ├── ChatBubble.tsx
│   │   ├── ChatBubble.figma.tsx
│   │   └── ...
│   └── ...
├── figma.config.json                # Code Connect configuration
└── ...
```

### 10.3 Design Token Pipeline

```text
Figma Variables (source of truth)
       ↓ get_variable_defs (MCP)
       ↓ or REST API (Enterprise)
Token Transformation
       ↓
CSS Custom Properties (globals.css)
       ↓
Tailwind CSS v4 (@theme directive)
       ↓
Component Styles
```

For non-Enterprise plans, token sync is manual or plugin-assisted rather
than automated via REST API.

### 10.4 CI/CD Integration

```text
Developer pushes code
       ↓
CI runs: npx figma connect publish
       ↓
Figma Dev Mode updated with latest code snippets
       ↓
(Enterprise) CI reads Figma variables → generates tokens → commits
```

---

## 11. Plan & Access Requirements

| Feature | Minimum Plan | Notes |
| --------- | ------------- | ------- |
| MCP Remote Server | All plans | 6 calls/month on Starter; per-minute on paid |
| MCP Desktop Server | Dev/Full seat (paid) | Requires Figma desktop app |
| Code Connect CLI | All plans (publish) | Publish to Dev Mode |
| Code Connect UI | Organization/Enterprise | In-Figma mapping experience |
| `generate_figma_design` | Remote MCP | Claude Code / Codex only |
| Variables REST API | **Enterprise** | Full CRUD for token sync |
| Figma Make | Make plan | NPM imports at Schema 2025 |
| Extended Collections | Enterprise Full seat | Multi-brand inheritance |
| Make Kits | Early Access (waitlist) | Design library → Make |
| Check Designs linter | Early Access (waitlist) | Variable alignment audit |

**Recommendation**: For our workflow, minimum **Professional plan with Dev
seats** gives access to MCP (both servers), Code Connect CLI, and reasonable
rate limits. Enterprise unlocks automated token sync via Variables API.

---

## 12. Open Questions & Risks

### 12.1 Open Questions

1. **Token sync without Enterprise**: What's the best plugin-based workaround
   for automated Figma Variables → Tailwind token sync on Professional plan?
   Candidates: Tokens Studio, Figma Token Exporter, custom plugin.

1. **Code Connect at scale**: How does Code Connect perform with 100+
   component mappings? What's the publish time? Are there practical limits?

1. **MCP token budget**: The MCP server's`get_design_context` returns a
   React + Tailwind representation. For complex pages, this may exceed the
   AI agent's context window. The ~12,000 token sweet spot per component
   needs validation with our design system.

1. **`generate_figma_design`maturity**: This tool is new and currently
   limited to Claude Code and Codex. How reliable is the live UI capture?
   How well do captured layers preserve component structure?

1. **Make Kits availability**: Make Kits (importing design libraries into
   Make) is still Early Access. When will it be GA?

1. **shadcn/ui Figma kit selection**: Which community kit should we adopt?
   Need to evaluate 1:1 accuracy with latest shadcn/ui components.

### 12.2 Risks

| Risk | Severity | Mitigation |
| ------ | ---------- | ------------ |
| Enterprise plan required for token automation | HIGH | Use plugin workaround; manual sync for MVP |
| `generate_figma_design` Claude Code/Codex lock-in | MEDIUM | This is supplementary; core flow is Design → Code |
| MCP rate limits on non-Enterprise plans | MEDIUM | Batch MCP calls; cache responses locally |
| Code Connect mapping drift | MEDIUM | CI integration: publish on every deploy |
| Round-trip information loss (Scenario 3) | HIGH | Treat code → canvas as reference, not source of truth |
| Figma Make output quality for production use | LOW | Make is for prototyping; production code via MCP + manual |

---

## 13. References

### Official Figma Documentation

- [Code Connect Introduction](https://developers.figma.com/docs/code-connect/)
- [Code Connect React
  Guide](https://developers.figma.com/docs/code-connect/react/)
- [Code Connect CLI
  Quickstart](https://developers.figma.com/docs/code-connect/quickstart-guide/)
- [Figma MCP Server
  Introduction](https://developers.figma.com/docs/figma-mcp-server/)
- [MCP Server Tools &
Prompts](https://developers.figma.com/docs/figma-mcp-server/tools-and-prompts/)
- [MCP Server Remote
Installation](https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/)
- [MCP Server Desktop
Installation](https://developers.figma.com/docs/figma-mcp-server/local-server-installation/)
- [Trigger Specific MCP
Tools](https://developers.figma.com/docs/figma-mcp-server/trigger-specific-tools/)
- [Figma REST API Introduction](https://developers.figma.com/docs/rest-api/)
- [Code Connect Help
  Center](https://help.figma.com/hc/en-us/articles/23920389749655-Code-Connect)
- [MCP Server Help Center
Guide](https://help.figma.com/hc/en-us/articles/32132100833559-Guide-to-the-Figma-MCP-server)
- [What's New from Schema
2025](https://help.figma.com/hc/en-us/articles/35794667554839-What-s-new-from-Schema-2025)

### Figma Blog

- [Introducing our MCP
  Server](https://www.figma.com/blog/introducing-figma-mcp-server/)
- [Config 2025 Recap](https://www.figma.com/blog/config-2025-recap/)
- [Figma Make General
  Availability](https://www.figma.com/blog/figma-make-general-availability/)
- [Schema 2025: Design Systems for a New
  Era](https://www.figma.com/blog/schema-2025-design-systems-recap/)
- [The Future of Design Systems is
Semantic](https://www.figma.com/blog/the-future-of-design-systems-is-semantic/)
- [Design Context, Everywhere You
  Build](https://www.figma.com/blog/design-context-everywhere-you-build/)

### GitHub Repositories

- [figma/code-connect](https://github.com/figma/code-connect)
- [figma/mcp-server-guide](https://github.com/figma/mcp-server-guide)
- [@figma/code-connect npm](https://www.npmjs.com/package/@figma/code-connect)

### Dev Mode Codegen Plugins

- [Codegen Plugins
  Guide](https://developers.figma.com/docs/plugins/codegen-plugins/)
- [Codegen Plugins Blog
  Post](https://www.figma.com/blog/figma-dev-mode-codegen-plugins/)
- [figma.codegen API
  Reference](https://developers.figma.com/docs/plugins/api/figma-codegen/)
- [Working in Dev Mode (Plugin
  Docs)](https://developers.figma.com/docs/plugins/working-in-dev-mode/)
- [Plugin Samples Repository](https://github.com/figma/plugin-samples)

### Community & Third-Party

- [shadcn/ui Figma Page](https://ui.shadcn.com/docs/figma)
- [shadcn/ui Design System (Figma
Community)](https://www.figma.com/community/file/1203061493325953101/shadcn-ui-design-system)
- [Figma-Context-MCP (Community)](https://github.com/GLips/Figma-Context-MCP)
- [Builder.io: Claude Code to Figma
  Tutorial](https://www.builder.io/blog/claude-code-to-figma)
- [Builder.io: Figma MCP Server](https://www.builder.io/blog/figma-mcp-server)
- [Figma Developer Workflows (MCP
  Collection)](https://help.figma.com/hc/en-us/articles/36189347137047)
