# Figma Developer Ecosystem Bootstrap Plan

**Date:** 2026-03-01
**Feature:** figma-architecture
**Type:** plan
**ADR:** docs/adrs/018-figma-developer-workflow.md

---

## Objective

Bootstrap the complete Figma → Code Connect → MCP → Svelte implementation pipeline
so that AI-assisted UI development in `src/ui/` has:

1. Real component references (not invented) in MCP responses via Code Connect
2. Design token names (not hard-coded values) via Figma Variable code syntax + `get_variable_defs`
3. A validated canonical agent workflow that exercises all four MCP tools

---

## Prerequisites (External / Team)

Before any code work begins, these must be confirmed:

| # | Action | Owner | Notes |
|---|---|---|---|
| P1 | Confirm Figma subscription tier is Organisation or Enterprise | Team lead | Required for Code Connect CLI publishing |
| P2 | Confirm developer PAT exists with `Code Connect: Write` + `File content: Read` scopes | Each developer | Required for `figma connect publish` |
| P3 | Identify the Figma file key for the VaultSpec design file | Designer | Extracted from file URL |
| P4 | Confirm Figma desktop app is installed on all developer machines | Each developer | Required for MCP desktop server |

---

## Phase 0: Figma File Audit

Before writing any Code Connect files, the Figma design file must be audited:

### 0.1 Variable Audit

- Open the Figma design file in Dev Mode
- Open `Resources` → `Variables` panel
- For every variable used in the UI:
  - [ ] Verify a **code syntax** value is set (e.g., `--color-primary-500`)
  - [ ] Verify the code syntax matches the project's CSS custom property naming
  - [ ] Verify the variable is bound to nodes (not raw values in fills/spacing)

If code syntax is missing on any variable, work with the designer to populate it before
continuing. The format should match the Tailwind v4 token names used in the project.

### 0.2 Component Audit

- List all Figma components that have corresponding shadcn-svelte implementations:

| Figma Component | Code Connect target | shadcn-svelte file |
|---|---|---|
| Button | Button | `src/ui/components/ui/button/button.svelte` |
| Card | Card | `src/ui/components/ui/card/card.svelte` |
| Badge | Badge | `src/ui/components/ui/badge/badge.svelte` |
| Input | Input | `src/ui/components/ui/input/input.svelte` |
| Textarea | Textarea | `src/ui/components/ui/textarea/textarea.svelte` |
| Select | Select | `src/ui/components/ui/select/select.svelte` |
| Tabs | Tabs | `src/ui/components/ui/tabs/tabs.svelte` |
| Alert | Alert | `src/ui/components/ui/alert/alert.svelte` |
| AlertDialog | AlertDialog | `src/ui/components/ui/alert-dialog/alert-dialog.svelte` |
| Sheet | Sheet | `src/ui/components/ui/sheet/sheet.svelte` |
| Collapsible | Collapsible | `src/ui/components/ui/collapsible/collapsible.svelte` |
| ScrollArea | ScrollArea | `src/ui/components/ui/scroll-area/scroll-area.svelte` |
| Checkbox | Checkbox | `src/ui/components/ui/checkbox/checkbox.svelte` |

*(This table must be updated once the actual Figma file is available and components
confirmed.)*

---

## Phase 1: Project Config

### 1.1 Install Code Connect

```bash
npm install --save-dev @figma/code-connect
```

### 1.2 Create `figma.config.json`

At the project root (alongside `package.json`):

```json
{
  "codeConnect": {
    "include": ["src/ui/**/*.figma.js"],
    "exclude": ["node_modules/**", ".svelte-kit/**"],
    "label": "Svelte",
    "language": "html"
  }
}
```

### 1.3 Add npm scripts

In `package.json`:

```json
{
  "scripts": {
    "figma:publish": "figma connect publish",
    "figma:parse":   "figma connect parse",
    "figma:create":  "figma connect create"
  }
}
```

---

## Phase 2: Write Code Connect Mapping Files

For each component identified in Phase 0, create a `.figma.js` file alongside the
corresponding `.svelte` source.

### 2.1 File Naming Convention

```
src/ui/components/ui/button/button.svelte
src/ui/components/ui/button/button.figma.js    ← new
```

### 2.2 Template Structure

```js
// button.figma.js
// @url https://www.figma.com/design/<FILE_KEY>/VaultSpec?node-id=<NODE_ID>
// @source src/ui/components/ui/button/button.svelte
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
      Link:        'link',
    })
    const size = figma.selectedInstance.getEnum('Size', {
      Default: 'default',
      Small:   'sm',
      Large:   'lg',
      Icon:    'icon',
    })
    const label    = figma.selectedInstance.getString('Label')
    const disabled = figma.selectedInstance.getBoolean('Disabled')

    return figma.code`<Button
  variant="${variant}"
  size="${size}"${disabled ? '\n  disabled' : ''}
>
  ${label}
</Button>`
  },
}
```

To get the `node-id` for each component: open the component in Figma → right-click →
"Copy link to selection" → extract `node-id` from URL.

### 2.3 Workflow for Each Component

1. `npx figma connect create "https://www.figma.com/design/<KEY>/...?node-id=<ID>"`
   generates a boilerplate file
2. Fill in variant/prop mappings based on the component's Figma property panel
3. `npx figma connect parse` to validate without uploading
4. Commit the `.figma.js` file to version control

---

## Phase 3: Publish and Validate

### 3.1 Publish to Figma

```bash
FIGMA_ACCESS_TOKEN=<token> npx figma connect publish
```

Expected output: list of published components with their node IDs and labels.

### 3.2 Validate in Dev Mode

For each published component:
1. Open the Figma file in Dev Mode
2. Select the component node
3. Open the Code panel (right sidebar)
4. Confirm the "Svelte" tab shows the real snippet from the `.figma.js` file
5. Change a variant in the property panel — confirm the snippet updates

### 3.3 Validate MCP `get_code_connect_map`

With the Figma desktop app open and the file in Dev Mode:

```
Tool call: get_code_connect_map
  fileKey: <FILE_KEY>
  nodeId:  <any published component node ID>
```

Expected response:
```json
{
  "<nodeId>": {
    "codeConnectSrc":  "src/ui/components/ui/button/button.svelte",
    "codeConnectName": "Button"
  }
}
```

If the response is `{}`, Code Connect has not published correctly. Re-run
`figma connect publish` and check the output for errors.

### 3.4 Validate `get_variable_defs`

With a frame selected that uses Figma Variables:

```
Tool call: get_variable_defs
```

Expected: token names with values (e.g., `"--color-primary-500": { "light": "#0066CC" }`).

If raw hex values appear without names, the Figma Variables do not have code syntax set.
Return to Phase 0.1.

---

## Phase 4: Full Agent Workflow Validation

Run a test UI task through the complete pipeline:

1. Select a Figma frame (e.g., the Sidebar component)
2. Execute the canonical call sequence:
   - `get_metadata` (frame summary)
   - `get_design_context` (full layout + Code Connect snippets)
   - `get_screenshot` (visual reference)
   - `get_variable_defs` (token names)
   - `get_code_connect_map` (component paths)
3. Inspect the `get_design_context` response: confirm `<CodeConnectSnippet>` blocks
   are present and contain real Svelte import statements
4. Ask the agent to implement the frame
5. Verify the generated code:
   - Uses `import { Button } from "$lib/components/ui/button"` (not invented components)
   - Uses `text-primary-500` or `var(--color-primary-500)` (not `color: #0066CC`)
   - Renders correctly in the browser (Playwright screenshot matches Figma screenshot)

---

## Phase 5: Token Sync Automation (Deferred)

Automated token synchronisation requires:

- Enterprise Figma plan (for `file_variables:write` REST API access)
- `LIBRARY_PUBLISH` webhook registration

When prerequisites are met:

```
Figma library publish
  → webhook POST → CI pipeline
  → GET /v1/files/:key/variables/local
  → transform to CSS custom properties
  → update src/ui/tokens.css
  → update Tailwind v4 token config
  → open PR
```

This phase is deferred and tracked separately.

---

## Success Criteria

- [ ] `figma connect publish` completes without errors for all audited components
- [ ] Dev Mode shows "Svelte" tab with real component snippet for every published component
- [ ] `get_code_connect_map` returns non-empty mapping for all published node IDs
- [ ] `get_variable_defs` returns token names (not raw values) for all variables in scope
- [ ] An AI-generated Svelte component matches the Figma design within visual tolerance
  and uses no invented imports or hard-coded values

---

## Appendix: `figma.selectedInstance` Template API Reference

| Method | Figma property type | Example |
|---|---|---|
| `.getString('Name')` | Text / string property | `getString('Label')` |
| `.getBoolean('Name')` | Boolean property | `getBoolean('Disabled')` |
| `.getEnum('Name', map)` | Variant / string enum | `getEnum('Variant', { Primary: 'primary' })` |
| `.findInstance('LayerName')` | Named child instance | `findInstance('Icon')` |
| `.executeTemplate()` | Nested Code Connect | call after `findInstance` |

The `figma.code` tagged template literal handles attribute formatting:
- String interpolation: `variant="${variant}"` → `variant="primary"`
- Conditional attributes: `${disabled ? 'disabled' : ''}` → `disabled` or empty
- Multi-line: preserves indentation in the Dev Mode snippet
