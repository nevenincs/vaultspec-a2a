---
date: 2026-03-01
type: research
feature: figma-architecture
description: "Research into Figma design-system architecture and component pipeline."
---

# Figma Developer Ecosystem: Architecture Research

**Date:** 2026-03-01
**Feature:** figma-architecture
**Type:** research

---

## 1. Executive Summary

Figma's developer ecosystem consists of four interlocking surfaces that together
form a
design-to-code pipeline: **Figma Design / Dev Mode** (the design canvas and
handoff
workspace), the **Figma REST API** (programmatic file access), **Code Connect**
(the
codebase bridge), and the **Figma MCP Server** (the AI-agent interface). A
fifth,
tangential tool — **Figma Make** — handles AI-driven prototyping but is
React-only and
not directly relevant to this SvelteKit project.

The central insight of the ecosystem: **the design system is the shared source
of truth**.
Figma Variables hold design tokens; Code Connect maps Figma components to real
codebase
components; the MCP server carries both forms of data to AI agents in the IDE;
Dev Mode
surfaces both to the human developer. Every tool downstream improves in
proportion to the
rigour with which tokens and component mappings are maintained upstream.

### Applicability to VaultSpec

| Surface | Applicability | Key Constraint |
| --- | --- | --- |
| Figma Design / Dev Mode | Full | Requires Dev seat on paid plan |
| Figma REST API | Full (PAT auth) | Variables API requires Enterprise + Full seat |
| Code Connect CLI | Partial | **Svelte has no native parser** — template/no-parser mode required |
| Code Connect UI | N/A | GitHub-repo auto-mapping; less precise than CLI for Svelte |
| Figma MCP Server (desktop) | Full — **already configured** | Requires Figma desktop app running with Dev Mode active |
| Figma MCP Server (remote) | Partial | OAuth only (no PAT); `get_variable_defs` unavailable |
| Figma Make | N/A | React-only output |

---

## 2. The Four Surfaces

### Surface Map

```text
┌─────────────────────────────────────────────────────────────────────┐
│  FIGMA FILE (Variables / Styles / Components / Frames)              │
│                                                                     │
│  ┌─────────────┐   ┌─────────────────────────────────────────────┐ │
│  │  DESIGN     │   │  DEV MODE                                   │ │
│  │  CANVAS     │──▶│  - Inspect panel (token-precise CSS)        │ │
│  │             │   │  - Code Connect snippets                    │ │
│  │             │   │  - Asset downloads                          │ │
│  └─────────────┘   └─────────────────────────────────────────────┘ │
│         │                        │                                  │
│         │                        ▼                                  │
│  ┌──────▼──────────────────────────────────────────────────────┐   │
│  │  CODE CONNECT                                               │   │
│  │  CLI: writes .figma.js mappings → publishes to Figma        │   │
│  │  UI:  GitHub repo auto-scan → AI-generated suggestions      │   │
│  └──────────────────────────┬────────────────────────────────┘   │
└─────────────────────────────┼───────────────────────────────────────┘
                              │
         ┌────────────────────▼──────────────────────┐
         │  FIGMA MCP SERVER                         │
         │  Desktop: 127.0.0.1:3845/mcp              │
         │  Remote:  https://mcp.figma.com/mcp       │
         │                                           │
         │  Tools exposed to AI agents:              │
         │    get_design_context                     │
         │    get_variable_defs (desktop only)       │
         │    get_code_connect_map                   │
         │    get_screenshot                         │
         │    get_metadata                           │
         └──────────────────┬────────────────────────┘
                            │
                            ▼
         ┌──────────────────────────────────────────┐
         │  AI AGENT (Claude Code / Cursor / etc.)  │
         │  Receives: design context + tokens +     │
         │            Code Connect component refs   │
         │  Generates: Svelte/SvelteKit components  │
         └──────────────────────────────────────────┘
```

---

## 3. Figma Design and Dev Mode

### Design Canvas

The canvas is the authoritative design artifact. Its nodes (frames, components,
instances, text layers, vectors) are the inputs to every downstream system.
Proper
structure is a prerequisite for high-quality downstream output:

- **Components** must be properly defined (not loose groups) for Code Connect
  and MCP to
  recognise them.
- **Variables** must be bound to nodes (not raw hex/px values) for Dev Mode and
  MCP to
  output token names.
- **Variants** must be defined on component sets for Code Connect prop mapping
  to work.
- **Layer names** must be meaningful (Code Connect uses layer name to resolve
  `figma.children()`and`figma.nestedProps()`calls).

### Dev Mode

Dev Mode is a developer-only inspection workspace (Shift+D or toolbar toggle).
It
provides:

### Inspect panel

- Pixel-precise layout: width, height, padding, gap, alignment
- Typography: font family, size, weight, line-height, letter-spacing
- Colors and fills resolved to **variable names** when variables are bound — not
  just
  raw hex values. A designer using`#0066CC`gets`color:
  var(--color-primary-500)`only
  if that color references a Figma Variable with code syntax set.
- Auto-generated code: CSS, SwiftUI, Jetpack Compose
- **Code Connect snippets** (when published): replaces auto-generated code with
  real
  production component code from the codebase

### Status workflow

- Designers mark frames "Ready for Dev" → developers filter to only those frames
- On Organization/Enterprise plans: "Completed" status
  triggers`DEV_MODE_STATUS_UPDATE`
  webhook — enables CI automation (e.g., auto-close Jira ticket)

**Suggested Variables:**
When a node has a raw pixel/color value but a matching Figma Variable exists,
Dev Mode
surfaces a suggestion to bind the variable. This prevents hard-coding.

**External resource links:**
Frames can be linked to GitHub PRs, Jira tickets, Storybook stories.

### Design Token Flow in Dev Mode

```text
Figma Variable
  name:        "color/primary/500"
  value:       #0066CC (light mode), #3399FF (dark mode)
  code syntax: "--color-primary-500"
       │
       ▼
Dev Mode Inspect Panel
  CSS output:  color: var(--color-primary-500);
       │
       ▼
MCP get_variable_defs
  Returns: { "--color-primary-500": { light: "#0066CC", dark: "#3399FF" } }
       │
       ▼
AI Agent generates code using token name, not raw value
```

The **code syntax** field on a Figma Variable is the CSS custom property name.
If it is
not set, Dev Mode outputs raw values and MCP cannot resolve token names. Setting
code
syntax on every variable is therefore a prerequisite for AI-assisted
development.

---

## 4. Figma REST API

### Base URL and Authentication

```text
Base: https://api.figma.com
Auth: X-Figma-Token: <PAT>   (for server-side / scripted access)
      OAuth 2.0              (for third-party registered apps)
```

### File Key and Node ID Extraction

Every Figma URL encodes both identifiers:

```text
https://www.figma.com/design/<fileKey>/Name?node-id=<nodeId>
                              ^^^^^^^^^              ^^^^^^^
```

- `fileKey`: path segment after file type (`/design/ABC123/`→`ABC123`)
- `nodeId`: `node-id`query parameter in`row-col` hyphen format; convert to colon
  for
  API calls (`1200-23`→`1200:23`)

### Key Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/files/:key` | Full file JSON (document tree, components, styles) |
| `GET /v1/files/:key/nodes?ids=:id` | Specific node subtrees |
| `GET /v1/images/:key?ids=:id&format=png` | Render nodes as images |
| `GET /v1/files/:key/images` | URLs for embedded raster assets |
| `GET /v1/files/:key/variables/local` | All local design tokens |
| `GET /v1/files/:key/variables/published` | Published (library) tokens |
| `POST /v1/files/:key/variables` | Create/update/delete tokens |
| `GET /v1/files/:key/components` | Published components in file |
| `GET /v1/files/:key/styles` | Published styles |
| `GET /v1/me` | Authenticated user info |

### Variables API (Design Tokens)

The Variables API maps directly onto the design token concept:

- A **Variable** is one named, reusable value (e.g.,`color/primary/500`)
- A **VariableCollection** groups variables with **modes** (e.g., light / dark)
- Variables can hold: `COLOR`, `FLOAT`(spacing, sizing,
  radius),`STRING`(typography),
 `BOOLEAN`

**Requirements:** Enterprise plan + Full seat + `file_variables:read` scope on
PAT.

Primary integration pattern: CI/CD pipeline syncs Figma variables to a token
JSON
file → Style Dictionary transforms to CSS custom properties, Tailwind tokens,
etc.

### Webhooks

```text
POST /v2/webhooks          # Create subscription
GET  /v2/webhooks/:id/requests  # Inspect delivery history (7 days)
```

Key events:

- `FILE_UPDATE`: content changed
- `LIBRARY_PUBLISH`: library (components, variables) published → trigger token
  sync
- `DEV_MODE_STATUS_UPDATE`: designer marks a frame ready/completed → trigger CI
  workflow

---

## 5. Code Connect

### Purpose

Code Connect creates a **bidirectional link** between Figma component
definitions and
their production codebase implementations. Without it, Dev Mode shows
autogenerated
approximations. With it, Dev Mode shows the actual import statement, real prop
names,
and conditional logic from your component.

It also feeds the **MCP server**: when an AI agent calls `get_design_context`,
Code
Connect snippets are injected directly into the response, enabling the agent to
use real
codebase components rather than generating synthetic ones.

### Two Implementation Paths

#### Code Connect CLI (the authoritative path)

Developer-written mapping files published to Figma via the `figma` CLI.

```bash
npm install @figma/code-connect
npx figma connect publish --token $FIGMA_ACCESS_TOKEN
```

**Authentication:** PAT with `Code Connect: Write`+`File content: Read`scopes.

**Plan requirement:** Organization or Enterprise.

#### Code Connect UI (the auto-mapping path)

Browser-based, GitHub-repo connected, AI-generated suggestions. Introduced in
2025.
Less precise than CLI. Not the recommended path for a design system with
non-React
framework.

### CLI Commands

| Command | Description |
| --- | --- |
| `figma connect` | Interactive wizard — detects components, suggests mappings |
| `figma connect publish` | Uploads all mapping files to Figma |
| `figma connect unpublish` | Removes published connections |
| `figma connect create <url>` | Generates boilerplate for a specific node URL |
| `figma connect parse` | Outputs parsed JSON to stdout (dry-run inspection) |

### `figma.config.json`

Placed at project root:

```json
{
  "codeConnect": {
    "include": ["src/**/*.figma.js"],
    "exclude": ["test/**", "build/**"],
    "label": "Svelte",
    "language": "html",
    "documentUrlSubstitutions": {
      "https://www.figma.com/design/STAGING_FILE": "https://www.figma.com/design/PROD_FILE"
    }
  }
}
```

### Framework Support and File Formats

| Framework | Parser | File extension | Import |
| --- | --- | --- | --- |
| React | `react`(native) | `.figma.tsx` | `@figma/code-connect` |
| HTML / Web Components | `html`(native) | `.figma.ts` | `@figma/code-connect/html` |
| Angular | `html`(auto-detect) | `.figma.ts` | `@figma/code-connect/html` |
| Vue | `html`(auto-detect) | `.figma.ts` | `@figma/code-connect/html` |
| **Svelte** | **No native parser** | `.figma.js` | Template API |
| SwiftUI | `swift` | `.figma.swift` | Swift package |
| Jetpack Compose | `compose` | `.figma.kt` | Gradle plugin |
| Storybook | `react`(stories) | `.stories.tsx` | `@figma/code-connect` |

### Svelte: Template / No-Parser Mode

Svelte requires the no-parser (template file) approach. The mapping file is a
plain
`.js` file with metadata comments:

```js
// Button.figma.js
// @url https://www.figma.com/design/FILE_ID/Name?node-id=X%3AY
// @source src/lib/components/ui/button/button.svelte
// @component Button

export default {
  imports: ['import { Button } from "$lib/components/ui/button"'],
  example: (figma) => {
    const variant = figma.selectedInstance.getEnum('Variant', {
      Default:     'default',
      Secondary:   'secondary',
      Destructive: 'destructive',
      Outline:     'outline',
      Ghost:       'ghost',
    })
    const size = figma.selectedInstance.getEnum('Size', {
      Default: 'default',
      Small:   'sm',
      Large:   'lg',
      Icon:    'icon',
    })
    const label = figma.selectedInstance.getString('Label')
    const disabled = figma.selectedInstance.getBoolean('Disabled')

    return figma.code`<Button variant="${variant}" size="${size}" ${disabled ? 'disabled' : ''}>
  ${label}
</Button>`
  },
}
```

`figma.config.json` for this project:

```json
{
  "codeConnect": {
    "include": ["src/ui/**/*.figma.js"],
    "label": "Svelte",
    "language": "html"
  }
}
```

### The `figma`Property Mapping API (React/HTML parsers)

When using the native React or HTML parsers, a richer type-safe API is
available:

| Helper | Figma property type | Returns |
| --- | --- | --- |
| `figma.string('Prop')` | Text / string property | String value |
| `figma.boolean('Prop')` | Boolean property | `true`/`false`(or mapped values) |
| `figma.enum('Prop', map)` | Variant / string enum | Mapped code value |
| `figma.instance('Prop')` | Instance-swap property | Nested component snippet |
| `figma.children('Layer')` | Child layer by name | Nested child snippet |
| `figma.nestedProps('Layer', map)` | Properties of a nested layer | Object of mapped props |
| `figma.textContent('Layer')` | Text content of a named layer | String |
| `figma.className(arr)` | — | CSS class string (filters undefined) |

### Variant Restrictions

Multiple`figma.connect()` calls on the same URL, each scoped to a variant combo:

```tsx
figma.connect(PrimaryButton, URL, { variant: { Type: 'Primary' }, example: ... })
figma.connect(DangerButton,  URL, { variant: { Type: 'Danger'  }, example: ... })
```

### How Code Connect Appears in Dev Mode and MCP

In Dev Mode: the Code snippet panel shows the real component code, replacing
auto-generated approximations. Multiple `label`tabs coexist (e.g., "Svelte",
"React").

In MCP`get_design_context`response:`<CodeConnectSnippet>`wrappers are injected
containing the import statement and usage snippet from the mapping file. The AI
agent
sees the real component, not a fabricated one.

---

## 6. Figma MCP Server

### Purpose (2)

The MCP Server exposes structured Figma design data to AI coding agents running
in
editors (Claude Code, Cursor, VS Code). Instead of agents interpreting
screenshots, they
receive machine-readable node trees, layout constraints, design tokens by name,
and Code
Connect component references.

### Two Deployment Modes

| | Desktop Server | Remote Server |
| --- | --- | --- |
| **Endpoint** | `http://127.0.0.1:3845/mcp` | `https://mcp.figma.com/mcp` |
| **Auth** | None (localhost trust) | OAuth 2.0 only (no PAT) |
| **Requires** | Figma desktop app + Dev Mode enabled | Any browser |
| **Selection** | From current desktop selection | From fileKey + nodeId params |
| **`get_variable_defs`** | ✅ Available | ❌ Not available |
| **`get_code_connect_map`** | ✅ Works without publishing | ⚠️ Requires library publish |
| **Asset server** | `localhost:3845/assets/*` | CDN URLs |

**This project uses the desktop server** (`127.0.0.1:3845/mcp`), already
declared in
`.mcp.json`. This is the correct configuration: no OAuth complexity, full tool
surface.

### Enabling the Desktop Server

1. Open Figma file in desktop app
2. Enable Dev Mode (Shift+D)
3. Inspect panel → MCP Server section → "Enable desktop MCP server"
4. Persists across sessions; auto-starts on next Dev Mode launch

### Tools Reference

#### `get_design_context`

The primary tool. Fetches the full structured representation of a selected node
or
frame. Returns:

- Node hierarchy with component type and parent/child structure
- Layout: Auto Layout direction, gap, padding, alignment; absolute size/position
- Typography: font, size, weight, line-height, letter-spacing — as token names
  where
  variables are bound
- Colors and fills: resolved to token names where variables are bound
- Variant properties: active variant, property values
- Asset URLs (`localhost:3845/assets/<hash>` for desktop)
- **`<CodeConnectSnippet>`blocks** where Code Connect mappings exist

Output format: pseudo-code optimised for LLM context windows (not raw Figma
JSON).

#### `get_metadata`

Sparse XML layer outline: IDs, names, types, positions, sizes. Used as a
precursor when
the full design context would be too large (high node count). The response
itself
instructs the agent to call `get_design_context`next on specific nodes.

#### `get_screenshot`

Captures an image of the current selection. Use for:

- Visual fidelity verification
- Designs containing imagery the node tree cannot describe (maps, video embeds)
- Final check before committing generated code

#### `get_variable_defs` *(desktop only)*

Returns all variables and styles used in the selected nodes:

```json
{
  "--color-primary-500": { "light": "#0066CC", "dark": "#3399FF" },
  "--spacing-4":         { "value": "16px" },
  "--radius-md":         { "value": "6px" }
}
```

Enables the agent to use token names in generated Tailwind/CSS rather than
hard-coded
values.

#### `get_code_connect_map`

Returns the mapping from Figma node IDs to codebase component paths:

```json
{
  "1:234": {
    "codeConnectSrc":  "src/lib/components/ui/button/button.svelte",
    "codeConnectName": "Button"
  },
  "1:567": {
    "codeConnectSrc":  "src/lib/components/ui/card/card.svelte",
    "codeConnectName": "Card"
  }
}
```

Without this, the agent invents components. With it, it uses the real ones.

#### `get_figjam`

Converts a FigJam diagram to XML + screenshots. Useful for providing AI agents
architecture context from FigJam system diagrams.

#### `generate_diagram`

Creates a FigJam diagram from Mermaid syntax or natural language. Useful for
persisting
AI-generated architecture diagrams back to Figma.

#### `create_design_system_rules`

Generates a rules file encoding this design system's conventions for AI agents:
framework preferences, token usage expectations, component naming. Runs once per
project, persists as a project-level rules file.

### Asset URL Pattern (Desktop)

Images served by the desktop server are content-addressed:

```text
http://localhost:3845/assets/89f254d1a998c9a6d1d324d43c73539c3993b16e.png
```

Use these URLs directly in generated code during development. They are stable
for the
session.

### Canonical Agent Workflow

```text
1. User provides Figma URL (or has node selected in desktop app)
2. Agent extracts fileKey + nodeId from URL
3. get_metadata         → layer outline for large selections
4. get_design_context   → full layout + style + Code Connect data
5. get_screenshot       → visual reference image
6. get_variable_defs    → token name → value map (desktop only)
7. get_code_connect_map → node ID → real component path
8. Agent generates code:
     - Uses Code Connect components where mapped
     - Generates new components where not mapped
     - Applies token names from variable defs
     - Validates against screenshot
```

### Rate Limits

| Seat type | Limit |
| --- | --- |
| Starter / View-Collab | 6 tool calls/month (remote) |
| Dev / Full seat on paid plan | REST API Tier 1 per-minute limits |
| Desktop server | No MCP-level limit (desktop app session) |

### Relationship to Figma REST API

The MCP server is a **transformation middleware** above the REST API:

```text
AI Agent
   │ MCP tool call
   ▼
MCP Server  ────► REST API calls (nodes, images, variables)
   │                    ▼
   │              Raw verbose JSON
   │
   └── LLM-optimized structured output:
         - strips irrelevant internal props
         - flattens node hierarchies
         - resolves token refs to names
         - injects Code Connect snippets
         → returned as pseudo-code to agent
```

Teams without the MCP server can replicate this with the REST API directly, but
the
transformation layer is non-trivial to implement.

---

## 7. Figma Make

### What It Is

Figma Make is an AI-powered **prompt-to-app prototyping tool** (GA July 2025).
It
accepts text prompts, images, or existing Figma frames and generates interactive
React

- CSS prototypes. It runs on Anthropic's Claude 3.7 Sonnet.

### Make Kits (Design System Integration)

Make kits allow a production npm package (a React design system) to be
registered in
Figma Make. The AI then generates prototypes using your actual components, not
synthetic
ones. Setup:

1. Package the design system as a public/private npm package
2. Add markdown guidelines describing component selection logic
3. Register in Figma Make (via org admin for private registries)

### Applicability to VaultSpec (2)

**Figma Make is React-only.** This project's frontend is SvelteKit. Make kits
only
support React npm packages. Figma Make is therefore **not applicable** to this
project.

Make may be useful for designer/PM rapid prototyping (exploring UI concepts
quickly)
but its output cannot be directly integrated into the SvelteKit codebase.

---

## 8. Complete Integration Architecture

### The Data Flow

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│  FIGMA FILE                                                                  │
│                                                                              │
│  Variables (tokens)          Components (design system)                     │
│  ┌─────────────────────┐    ┌─────────────────────────┐                    │
│  │ color/primary/500   │    │ ButtonComponent          │                    │
│  │ spacing/4           │    │   Variant: Primary/Danger│                    │
│  │ radius/md           │    │   Size: sm/md/lg         │                    │
│  │ [code syntax set]   │    │   Boolean: Disabled      │                    │
│  └─────────────────────┘    └─────────────────────────┘                    │
│              │                           │                                   │
└──────────────┼───────────────────────────┼───────────────────────────────────┘
               │                           │
               ▼                           ▼
  ┌────────────────────┐      ┌────────────────────────────────────┐
  │  Figma REST API    │      │  Code Connect CLI                  │
  │  /variables/local  │      │  Button.figma.js                   │
  │  → token JSON      │      │  variant → prop mapping            │
  │  → Style Dictionary│      │  figma connect publish             │
  │  → Tailwind tokens │      └─────────────┬──────────────────────┘
  └────────────────────┘                    │ published to Figma
                                            ▼
                         ┌──────────────────────────────────────────┐
                         │  Dev Mode (developer handoff)            │
                         │  - Inspect: token-precise CSS            │
                         │  - Code panel: real Svelte snippet       │
                         │  - Asset download                        │
                         └────────────────┬─────────────────────────┘
                                          │
                                          ▼
                         ┌──────────────────────────────────────────┐
                         │  Figma MCP Server (desktop:3845)         │
                         │  ┌──────────────────────────────────┐   │
                         │  │ get_design_context               │   │
                         │  │  → layout + <CodeConnectSnippet> │   │
                         │  │ get_variable_defs                │   │
                         │  │  → token names + values          │   │
                         │  │ get_code_connect_map             │   │
                         │  │  → nodeId → .svelte file path    │   │
                         │  │ get_screenshot                   │   │
                         │  └──────────────────────────────────┘   │
                         └────────────────┬─────────────────────────┘
                                          │
                                          ▼
                         ┌──────────────────────────────────────────┐
                         │  Claude Code (AI agent in IDE)           │
                         │  - Receives: design context, tokens,     │
                         │    Code Connect component refs           │
                         │  - Generates: SvelteKit components       │
                         │    using shadcn-svelte primitives        │
                         │    with Tailwind token classes           │
                         └──────────────────────────────────────────┘
```

### The Canonical Implementation Loop (from CLAUDE.md)

The project CLAUDE.md already mandates this exact pipeline:

```text
Figma (get_design_context)
  → shadcn-ui (list/get components)
  → Svelte MCP (verify Svelte 5 syntax)
  → implement
  → browser verification (Playwright/Chrome DevTools)
```

Code Connect is the missing piece that elevates step 1 from "approximate layout
from
raw node data" to "receive real shadcn-svelte component references with Tailwind
token
names".

---

## 9. Critical Constraints and Gotchas

### Plan Requirements

| Feature | Min Plan |
| --- | --- |
| Dev Mode access | Paid (Full or Dev seat) |
| Code Connect CLI publish | **Organization or Enterprise** |
| Code Connect UI | Organization or Enterprise |
| Variables API (REST) | **Enterprise + Full seat** |
| MCP desktop server | Any paid (Full or Dev seat) |
| MCP remote server | Any paid (6 calls/month on Starter) |
| `DEV_MODE_STATUS_UPDATE`webhook | Organization or Enterprise |

### Svelte-Specific Constraints

1. **No native Code Connect parser for Svelte.** Use`.figma.js` template files
   with the
   no-parser API (`figma.selectedInstance.getEnum(...)`, `figma.code\`...\``).
2. **`"language": "html"`in config** — Code Connect will syntax-highlight the
   snippet
   as HTML. This is the closest available option; Svelte is not a language
   option.
3. **Storybook integration is React-only.** Not applicable.
4. **Make is React-only.** Not applicable.

### MCP Desktop Server Constraints

1. Figma desktop app must be running with a file open in Dev Mode.
2. Port 3845 must be free.
3.`get_variable_defs`only works on the desktop server, not the remote server.
4.`get_code_connect_map`returns`{}` on the remote server unless the component
library
   is published in Figma.
3. Code Connect mapping files must be published (`figma connect publish`) before
   the MCP
   server returns `<CodeConnectSnippet>`content.

### Code Connect File Execution Model

Code Connect files are **not executed at runtime.** The`example`function body is
parsed as an AST and treated as a string template:

- Ternaries and conditionals output verbatim (not resolved)
-`Array.map()`calls inside`example`do not execute
-`figma.*` helper calls **do resolve** against live Figma property values
- The file is safe to import — it has no runtime behaviour

### Rate Limits (2)

The Figma REST API uses three rate limit tiers:

- Tier 1 (60 req/min): files, nodes, images, components, styles
- Tier 2 (30 req/min): comments, webhooks
- Tier 3 (200 req/hour): team/project listing

The MCP desktop server is bound by the desktop app's session, not REST API
tiers.

---

## 10. References

- [Figma Developer Docs](https://developers.figma.com/docs/)
- [Code Connect Docs](https://developers.figma.com/docs/code-connect/)
- [Code Connect: No-Parser (Template)
  Mode](https://developers.figma.com/docs/code-connect/no-parser/)
- [Figma MCP Server Docs](https://developers.figma.com/docs/figma-mcp-server/)
- [MCP Server Tools
Reference](https://developers.figma.com/docs/figma-mcp-server/tools-and-prompts/)
- [MCP Desktop Server
Installation](https://developers.figma.com/docs/figma-mcp-server/local-server-installation/)
- [REST API File
  Endpoints](https://developers.figma.com/docs/rest-api/file-endpoints/)
- [REST API Variables
  Endpoints](https://developers.figma.com/docs/rest-api/variables/)
- [REST API Webhooks V2](https://developers.figma.com/docs/rest-api/webhooks/)
- [figma/code-connect GitHub](https://github.com/figma/code-connect)
- [figma/mcp-server-guide GitHub](https://github.com/figma/mcp-server-guide)
- [Figma Make](https://www.figma.com/make/)
- [Config 2025 Press
  Release](https://www.figma.com/blog/config-2025-press-release/)
- [Comparing Code Connect UI and
  CLI](https://developers.figma.com/docs/code-connect/comparing-cc/)
