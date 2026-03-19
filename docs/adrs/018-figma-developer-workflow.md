---
adr_id: 018
title: Figma Developer Workflow — Code Connect, MCP Server, and Design Token Pipeline
date: 2026-03-01
status: Proposed
related:
  - docs/adrs/005-frontend-rendering-stack.md
  - docs/adrs/011-frontend-backend-contract.md
  - docs/figma/2026-01-03-figma-architecture-research.md
---

## ADR-018: Figma Developer Workflow

**Date:** 2026-03-01
**Status:** Proposed

---

## 1. Context and Problem Statement

The VaultSpec Gateway frontend (React / React 5 / shadcn-React /
Tailwind
CSS v4) is authored against a Figma design file. The CLAUDE.md workflow mandate
already
requires calling the Figma MCP server before writing or modifying any UI
component.
However, without Code Connect and a design token pipeline in place:

- The MCP server returns raw node layout data and invented component code rather
  than
  production-ready React snippets referencing real shadcn-React components.
- AI agents hard-code pixel values instead of Tailwind token classes because
  `get_variable_defs` cannot resolve token names from unbound variables.
- Dev Mode shows auto-generated CSS approximations instead of real React
  component
  usage, slowing designer–developer handoff.
- There is no machine-readable link between Figma component nodes and their
  `.React`
  source files.

This ADR decides how the Figma developer ecosystem surfaces (Code Connect CLI,
MCP
server, Dev Mode, REST API) are adopted and integrated for this project.

---

## 2. Decisions

### 2.1 MCP Server: Desktop Mode Only

The project will use **exclusively the Figma desktop MCP server** at
`http://127.0.0.1:3845/mcp`. This is already declared in `.mcp.json`.

The remote MCP server (`https://mcp.figma.com/mcp`) is **rejected** for primary
development use because:

- It requires OAuth 2.0 (no PAT support); more complex to configure.
- `get_variable_defs` is unavailable on the remote server — this is the tool
  that maps
  design values to token names.
- `get_code_connect_map` on the remote server requires the component library to
  be
  published in Figma before returning non-empty results.

The desktop server provides the full tool surface, requires no additional
authentication, and works directly from the developer's running Figma session.

**Mandatory prerequisite for UI work:** The Figma desktop app must be open with
the
design file loaded and Dev Mode active before any AI-assisted UI implementation
session.

### 2.2 Code Connect: CLI with Template/No-Parser Mode

Code Connect will be adopted via the **CLI approach** using **template
(no-parser)
files** (`.figma.js`), because React has no native Code Connect parser.

The CLI approach is chosen over the Code Connect UI because:

- CLI files are developer-authored and version-controlled: explicit, reviewable,
  reusable.
- CLI produces true-to-production snippets; UI auto-generation is approximate.
- CLI supports the full `figma.selectedInstance.*` property mapping API.

Each shadcn-React component used in `src/ui/` that has a corresponding Figma
component
node **must have** a sibling `.figma.js` Code Connect file. Publishing is done
via:

```bash
npx figma connect publish --token $FIGMA_ACCESS_TOKEN
```text

The `figma.config.json` at project root governs inclusion, label, and language:

```json
{
  "codeConnect": {
    "include": ["src/ui/**/*.figma.js"],
    "label": "React",
    "language": "html"
  }
}
```text

**Plan requirement:** Code Connect CLI publishing requires a Figma
**Organization or
Enterprise** plan. This must be confirmed against the team's Figma subscription
before
the CLI workflow can be enabled.

### 2.3 Design Token Pipeline: Variables → Code Syntax → Tailwind

All Figma Variables used in the design file must have their **code syntax field
set**
to the corresponding CSS custom property name. This is the prerequisite for:

- Dev Mode outputting `var(--color-primary-500)` instead of `#0066CC`
- MCP `get_variable_defs` returning token names instead of raw values
- AI agents writing `text-primary` (Tailwind) instead of hardcoded hex

The token sync pipeline:

```text
Figma Variables (code syntax set)
       │
       ▼ (REST API: GET /v1/files/:key/variables/local)
Token JSON file (or Style Dictionary input)
       │
       ▼ (Style Dictionary / custom transform)
CSS Custom Properties (src/ui/tokens.css)
Tailwind v4 token config
```typescript

The REST API call for token extraction requires a PAT with `file_variables:read`
scope.
The Variables API (write access, token create/update) requires Enterprise + Full
seat;
read access is available on lower plan tiers.

For the initial phase, tokens will be manually maintained in sync. A CI webhook
trigger
(`LIBRARY_PUBLISH` event) for automated sync is deferred until Enterprise plan
is
confirmed.

### 2.4 Figma Make: Not Adopted

Figma Make is **not adopted** for this project. It is React-only and produces
React +
CSS prototypes. The VaultSpec frontend is React. Make kits (the design
system
integration mechanism) only support React npm packages.

Make may be used by designers for rapid concept prototyping but its output
cannot be
directly integrated into the codebase.

### 2.5 MCP Mandatory Call Sequence

The CLAUDE.md workflow mandate is refined as follows. For every UI
implementation task
touching `src/ui/`:

1. **`get_design_context`** — primary layout and component data including Code
   Connect
   snippets
2. **`get_screenshot`** — visual reference (unless token budget is extremely
   tight)
3. **`get_variable_defs`** — resolve design values to token names
4. **`get_code_connect_map`** — discover real component paths for all node IDs
5. Implement using shadcn-React primitives with Tailwind token classes
6. Verify with Playwright or Chrome DevTools before committing

Steps 3 and 4 are only meaningful after Code Connect mappings have been
published and
Figma Variables have code syntax set. Until that infrastructure is in place, the
agent
must flag missing token/component data rather than inventing values.

---

## 3. Rationale

### Why Code Connect over manual description

Without Code Connect, the MCP server has no knowledge of the mapping between a
Figma
node and the corresponding `.React` file. The agent must infer from component
names
alone, which produces incorrect imports, wrong prop names, and invented
components that
duplicate existing ones. Code Connect provides a machine-readable ground truth.

### Why desktop server over remote

The `get_variable_defs` tool is unavailable on the remote server. This tool is
the
primary mechanism by which the agent learns to write `text-primary-500` instead
of
`color: #0066CC`. Without it, the agent cannot reliably respect the token
system.

### Why template/no-parser over Code Connect UI for React

The Code Connect UI (GitHub repo auto-mapping) generates approximated snippets
from
component names and AI inference. It does not support React-specific prop
conventions
(`bind:`, `$props()`, slot-based composition). The CLI template approach allows
explicit,
hand-authored prop mappings that precisely encode the React component's API.

### Why token code syntax is a blocker

`get_variable_defs` resolves token names only when the corresponding Figma
Variable has
its code syntax field populated. If this field is empty, the API returns the raw
numeric
or hex value with no name. Agents will hard-code values. Developers will
hard-code
values. The design system connection breaks.

---

## 4. Implementation Plan

The full implementation plan lives at:
`docs/figma/2026-01-03-figma-architecture-plan.md`

High-level phases:

| Phase | Description                                                                                        | Blocker                  |
| ----- | -------------------------------------------------------------------------------------------------- | ------------------------ |
| 0     | Confirm Figma plan tier (Org/Enterprise)                                                           | External                 |
| 1     | Set code syntax on all Figma Variables                                                             | Design team              |
| 2     | Publish `figma.config.json` and initial `.figma.js` mappings for top-level shadcn-React components | Dev team                 |
| 3     | Validate MCP `get_code_connect_map` returns populated data                                         | Requires phase 2         |
| 4     | Validate AI-generated React code uses real components + token classes                              | Requires phases 1-3      |
| 5     | Add `LIBRARY_PUBLISH` webhook for automated token sync                                             | Requires Enterprise plan |

---

## 5. Rejected Alternatives

### Remote MCP server as primary

Rejected. `get_variable_defs` unavailable; OAuth-only authentication;
`get_code_connect_map` unreliable until library published.

### Code Connect UI (auto-mapping)

Rejected for React. AI-generated snippets do not accurately represent React
component
APIs (props, slots, Runes). The CLI template approach is more work but produces
correct,
maintainable mappings.

### Figma Make for prototyping integration

Rejected. React-only. No React output path.

### Manual design-to-code (no MCP, no Code Connect)

Rejected. Manual pixel-by-pixel measurement is slow, error-prone, and
disconnects the
design system from the codebase. The Figma developer ecosystem eliminates this
entirely
when set up correctly.

### Custom MCP server wrapper over REST API

Rejected for now. The official desktop MCP server already provides the full tool
surface we need. A custom wrapper adds complexity without benefit at this stage.

---

## 6. Consequences

### Positive

- AI agents receive real shadcn-React component references with correct imports
  and
  Tailwind token classes — dramatically reducing hallucinated component code.
- Dev Mode shows real React snippets during designer–developer handoff.
- Design system tokens are machine-readable end-to-end (Figma → CI → Tailwind
  config).
- The implementation loop (Figma → Code → Browser) is fully instrumented.

### Negative

- **Setup cost:** Code Connect publishing requires manual authoring of
  `.figma.js`
  files for each component. This is a one-time investment per component.
- **Plan dependency:** CLI publishing requires Org/Enterprise plan. If the team
  is on a
  lower tier, Code Connect and the Variables API are not available, and the MCP
  server
  will return degraded data.
- **Desktop dependency:** Every developer working on UI must have the Figma
  desktop app
  installed and a file open in Dev Mode. Browser-only access is insufficient.
- **No React language syntax highlight:** Code Connect's `"language": "html"`
  is the
  closest supported option. Snippets are highlighted as HTML in Dev Mode.

---

## 7. References

- [Figma Architecture
  Research](../research/2026-03-01-figma-architecture-research.md)
- [ADR-005: Frontend Rendering Stack](005-frontend-rendering-stack.md)
- [ADR-011: Frontend-Backend Contract](011-frontend-backend-contract.md)
- [Code Connect Documentation](https://developers.figma.com/docs/code-connect/)
- [Code Connect: No-Parser
  Mode](https://developers.figma.com/docs/code-connect/no-parser/)
- [Figma MCP Server
  Tools](https://developers.figma.com/docs/figma-mcp-server/tools-and-prompts/)
- [Figma REST API
  Variables](https://developers.figma.com/docs/rest-api/variables/)
