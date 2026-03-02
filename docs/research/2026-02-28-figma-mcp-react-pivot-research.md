---
date: 2026-02-28
type: research
feature: figma-mcp-react-pivot
description: "Research into Figma MCP server and the React + Tailwind frontend pivot strategy."
---

# Figma MCP + React Pivot — Research

**Date**: 2026-02-28
**Status**: Active
**Scope**: Figma MCP integration, Code Connect setup, SvelteKit → React pivot

---

## 1. Current State

### What We Have

- **Figma Make project**:
`https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface`
  - File key: `EAs7Eh1lxKVzBqzke5HASU`
  - This is an AI-generated React+Tailwind v4 app (not a traditional Figma
    Design file)
- **Exported React code**: `knowledge/repositories/VaultSpec-A2A Control
  Surface/src/`
  - 23+ React components (layout, stream, inspector, permission, ui primitives)
  - Tailwind v4 styling, shadcn/ui (radix-ui) primitives
  - Material UI icons
- **Existing SvelteKit 5 frontend**: `src/ui/` — full port of the above, 140+
  component files
- **Backend**: FastAPI + LangGraph, 702 tests passing, fully operational
- **`FIGMA_ACCESS_TOKEN`**: Already in `.env`
- **Desktop MCP server**: Registered in `.mcp.json`at`http://127.0.0.1:3845/mcp`

### Decision: Pivot to React+Tailwind

- The Figma Make export is React+Tailwind natively
- `get_design_context`defaults to React+Tailwind output
- Code Connect has the richest support for React (AI prop mapping, interactive
  setup)
- Eliminates the React→Svelte translation layer entirely

---

## 2. Figma MCP Server

### Desktop Server (Chosen)

- **URL**:`http://127.0.0.1:3845/mcp`
- **Activation**: Figma Desktop → Dev Mode (`Shift+D`) → Enable desktop MCP
  server
- **Capabilities**: Selection-based prompting, link-based prompting, Code
  Connect, Make resources
- **Limitation**: No `generate_figma_design`, no `whoami`

### Tools Reference

| Tool | File Types | Purpose |
| ------ | ----------- | --------- |
| `get_design_context` | Design, Make | Returns structured code (React+Tailwind default) for a layer/selection |
| `get_screenshot` | Design, FigJam | Visual capture of a selection |
| `get_variable_defs` | Design | Design tokens (colors, spacing, typography) |
| `get_metadata` | Design | Sparse XML node map (IDs, names, types, positions) |
| `get_code_connect_map` | Design | Maps Figma node IDs → code components |
| `add_code_connect_map` | Design | Registers a node→component mapping |
| `create_design_system_rules` | N/A | Generates rules file for agent context |
| `get_figjam` | FigJam | FigJam metadata + screenshots |
| `generate_diagram` | N/A | Mermaid → FigJam diagram |

### Parameters

-`fileKey`(string): From URL path segment after`/design/`or`/make/`

- `nodeId`(string): From URL`node-id=`query param (hyphen format OK)
-`depth`(number, optional): Node tree traversal depth
-`clientFrameworks`(string, optional): Code Connect label filter (e.g., "React")

### Desktop-Specific Behavior

- Selection-based: No URL needed — uses currently selected node in Figma
-`fileKey`auto-detected from open file
-`nodeId`optional if something is selected

---

## 3. Make → MCP Resources

The **Resources (Make → MCP)** feature lets agents fetch code files from a Make
project:

1. Share Make project link with agent
2. Agent receives list of available files
3. Agent downloads selected files as context

**Critical**: Uses MCP`resources`capability — only works on clients that support
it.

**Workflow**: Share link → agent fetches file list → download files → use as
implementation context

---

## 4. Code Connect

### What It Does

Maps Figma components to codebase components. When MCP processes a frame with
Code Connect mappings, it generates`<CodeConnectSnippet>` wrappers containing:

- Design properties (variant values, booleans, text content)
- Import statements
- Component usage snippets
- Custom instructions

### CLI Setup

```bash
npm install --global @figma/code-connect@latest
npx figma connect --token=$FIGMA_ACCESS_TOKEN
```

### Interactive Setup Flow

1. Set top-level component directory (e.g., `./src/components`)
2. Provide Figma design system library URL
3. Creates `figma.config.json`
4. AI or manual prop mapping (AI = React only)
5. Component matching (Figma → code)
6. Generates `*.figma.tsx`files

### Configuration:`figma.config.json`

```json
{
  "codeConnect": {
    "parser": "react",
    "include": ["src/components/**/*.figma.tsx"],
    "exclude": ["test/**", "build/**"],
    "importPaths": {
      "src/components/*": "@/components"
    }
  }
}
```

### CLI Commands

| Command | Purpose |
| --------- | --------- |
| `npx figma connect` | Interactive setup wizard |
| `npx figma connect publish` | Publish mappings to Figma |
| `npx figma connect unpublish --node=URL --label=React` | Remove mapping |
| `npx figma connect create "FIGMA_URL"` | Create mapping for specific node |

### Code Connect File Example (React)

```tsx
import figma from '@figma/code-connect'
import { Button } from './Button'

figma.connect(Button, 'https://figma.com/design/FILE?node-id=XX:YY', {
  props: {
    variant: figma.enum('Variant', {
      Primary: 'primary',
      Secondary: 'secondary',
    }),
    label: figma.string('Label'),
    disabled: figma.boolean('Disabled'),
    icon: figma.instance('Icon'),
  },
  example: (props) => (
    <Button variant={props.variant} disabled={props.disabled}>
      {props.icon}
      {props.label}
    </Button>
  ),
})
```

### Prop Mapping Functions

- `figma.string(prop)`— text property → string
-`figma.boolean(prop, valueMap?)`— boolean property, optional true/false mapping
-`figma.enum(prop, valueMap)`— variant → code values
-`figma.instance(prop)`— instance swap → nested component
-`figma.children(layerName)`— child layers by name
-`figma.nestedProps(layer, propMap)`— properties from nested instance
-`figma.textContent(layer)`— text from child layer
-`figma.className(parts[])`— concatenate Tailwind classes

---

## 5. Make vs Design File Nuances

| Aspect | Figma Design | Figma Make |
| -------- | ------------- | ------------ |
| `get_design_context` | Yes | Yes |
| `get_screenshot` | Yes | ? |
| `get_variable_defs` | Yes | No (Design only) |
| `get_code_connect_map` | Yes | No (Design only) |
| Code Connect | Full support | Limited |
| MCP Resources | N/A | Yes (fetches code files) |

**Key insight**: Make is best used via the Resources capability (download code
files)
rather than via design tools. For full Code Connect + design token support, we'd
need a **Figma Design file** with the components.

**Options**:

1. Use Make Resources to extract code → implement directly
2. Create a proper Figma Design file from the Make project (copy layers)
3. Use`get_design_context`on Make for layout reference, build React components
   independently

---

## 6. Rate Limits

| Plan | Seat | Limit |
| ------ | ------ | ------- |
| Enterprise | Full/Dev | 600/day |
| Organization/Pro | Full/Dev | 200/day |
| Starter | Any | 6/month |

---

## 7. Known Issues & Gotchas

1. Default output is React+Tailwind — perfect for our pivot
2.`get_screenshot`may report incorrect MIME type (jpeg for PNG)
2. Desktop MCP requires Figma Desktop open with server enabled
3. Large frames may exceed token limits — use`get_metadata`first, then
   selective`get_design_context`
4. Code Connect files are statically analyzed, not executed — no runtime logic
5. Make files can't be brought back into Figma Design; copy snapshot as layers
   instead
6. `FIGMA_ACCESS_TOKEN`env var works with both MCP server and Code Connect CLI

---

## 8. Recommended Workflow

### For Each Component

1. **Figma Desktop**: Select component in Make project (or use link)
2. **MCP**:`get_design_context`→ get React+Tailwind code structure
3. **MCP**:`get_screenshot`→ visual reference
4. **Code Connect**: Check`get_code_connect_map`for existing mappings
5. **Implement**: Build React component using shadcn/ui primitives + Tailwind
6. **Map**: Create`.figma.tsx`Code Connect file
7. **Publish**:`npx figma connect publish`
8. **Verify**: Browser test with Playwright/DevTools
