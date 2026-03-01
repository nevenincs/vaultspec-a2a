# Figma Design API & REST API Research

**Date:** 2026-03-01
**Scope:** Comprehensive research into the Figma REST API, Plugin API, Variables API,
webhooks, authentication, and design-to-code pipeline capabilities.

---

## Table of Contents

1. [What is the Figma REST API / Design API?](#1-what-is-the-figma-rest-api--design-api)
2. [Available Endpoints](#2-available-endpoints)
3. [Extracting Design Tokens Programmatically](#3-extracting-design-tokens-programmatically)
4. [Variables and Styles in the API](#4-variables-and-styles-in-the-api)
5. [Write / Update Access (Bidirectional)](#5-write--update-access-bidirectional)
6. [Plugin API vs REST API](#6-plugin-api-vs-rest-api)
7. [Variables API Deep Dive](#7-variables-api-deep-dive)
8. [REST API and Dev Mode](#8-rest-api-and-dev-mode)
9. [Design-to-Code Pipelines](#9-design-to-code-pipelines)
10. [Webhooks and Change Detection](#10-webhooks-and-change-detection)
11. [Authentication and Access Tokens](#11-authentication-and-access-tokens)
12. [Rate Limits](#12-rate-limits)
13. [Implications for VaultSpec](#13-implications-for-vaultspec)

---

## 1. What is the Figma REST API / Design API?

The Figma REST API is a JSON-based HTTP API that provides programmatic access to
Figma files, components, styles, variables, comments, versions, and projects. It
allows external systems to read (and in limited cases write) design data without
requiring the Figma application to be open.

### Core characteristics

- **Base URL:** `https://api.figma.com` (Government: `https://api.figma-gov.com`)
- **Architecture:** RESTful with JSON responses and standard HTTP status codes
- **Authentication:** Personal Access Tokens (PATs) and OAuth 2.0
- **OpenAPI Spec:** Fully described in the open-source
  [`figma/rest-api-spec`](https://github.com/figma/rest-api-spec) repository
  with exported TypeScript types for type-safe development
- **File representation:** JSON document tree where every layer/object is a
  typed node (DOCUMENT > CANVAS > FRAME > ... > leaf nodes)

### What it exposes

- File structure, pages, nodes, and all layer properties
- Component metadata (published and local)
- Styles (color, text, effect, grid)
- Variables and variable collections (Enterprise only)
- Comments and version history
- Image exports (PNG, JPG, SVG, PDF)
- Dev resources (links between design nodes and external URLs)
- Library analytics (Enterprise)
- Activity logs (Enterprise)
- Webhooks for event-driven integrations

---

## 2. Available Endpoints

### 2.1 File Endpoints

| Endpoint | Method | Tier | Scope | Purpose |
|---|---|---|---|---|
| `/v1/files/:key` | GET | 1 | `file_content:read` | Full file document as JSON tree |
| `/v1/files/:key/nodes` | GET | 1 | `file_content:read` | Specific nodes and subtrees by ID |
| `/v1/images/:key` | GET | 1 | `file_content:read` | Render nodes as PNG/JPG/SVG/PDF images |
| `/v1/files/:key/images` | GET | 2 | `file_content:read` | Download URLs for user-uploaded image fills |
| `/v1/files/:key/meta` | GET | 3 | `file_metadata:read` | File metadata without document content |

#### GET File Parameters

| Parameter | Description |
|---|---|
| `version` | Specific version ID to retrieve |
| `ids` | Comma-separated node IDs for partial tree retrieval |
| `depth` | Maximum tree traversal depth |
| `geometry` | Set to `paths` to include vector path data |
| `branch_data` | Include branch metadata |
| `plugin_data` | Include plugin-stored data |

#### GET File Response Structure

```json
{
  "name": "File Name",
  "role": "owner",
  "lastModified": "2026-01-15T10:30:00Z",
  "editorType": "figma",
  "thumbnailUrl": "https://...",
  "version": "123456789",
  "document": {
    "id": "0:0",
    "name": "Document",
    "type": "DOCUMENT",
    "children": [
      {
        "id": "0:1",
        "name": "Page 1",
        "type": "CANVAS",
        "children": [...]
      }
    ]
  },
  "components": { "<node_id>": { "key": "...", "name": "...", ... } },
  "componentSets": { ... },
  "styles": { "<node_id>": { "key": "...", "name": "...", "styleType": "FILL" } }
}
```

#### GET Image Parameters

| Parameter | Description |
|---|---|
| `ids` | Required. Node IDs to render |
| `scale` | 0.01 to 4. Scaling factor |
| `format` | `jpg`, `png`, `svg`, or `pdf` |
| `svg_outline_text` | Render text as vector paths in SVG |
| `svg_include_id` | Include layer names as SVG element IDs |
| `svg_include_node_id` | Add Figma node IDs to SVG elements |
| `contents_only` | Exclude overlapping content from other layers |
| `use_absolute_bounds` | Full dimensions regardless of cropping |

**Important:** Rendered image URLs expire after 30 days. Images exceeding 32
megapixels are automatically scaled down. Null values in the response indicate
rendering failures.

### 2.2 Component & Style Endpoints

| Endpoint | Method | Tier | Scope | Purpose |
|---|---|---|---|---|
| `/v1/teams/:team_id/components` | GET | 3 | `team_library_content:read` | Paginated published components in team |
| `/v1/files/:file_key/components` | GET | 3 | `library_content:read` | Published components in file |
| `/v1/components/:key` | GET | 3 | `library_assets:read` | Single component by key |
| `/v1/teams/:team_id/component_sets` | GET | 3 | `team_library_content:read` | Component sets (variant groups) in team |
| `/v1/files/:file_key/component_sets` | GET | 3 | `library_content:read` | Component sets in file |
| `/v1/component_sets/:key` | GET | 3 | `library_assets:read` | Single component set by key |
| `/v1/teams/:team_id/styles` | GET | 3 | `team_library_content:read` | Paginated published styles in team |
| `/v1/files/:file_key/styles` | GET | 3 | `library_content:read` | Published styles in file |
| `/v1/styles/:key` | GET | 3 | `library_assets:read` | Single style by key |

Component metadata includes: `key`, `file_key`, `node_id`, `thumbnail_url`,
`name`, `description`, `updated_at`, `created_at`, `user`, and
`containing_frame`. Pagination is cursor-based with `before`/`after` cursors.

### 2.3 Variables Endpoints (Enterprise Only)

| Endpoint | Method | Tier | Scope | Purpose |
|---|---|---|---|---|
| `/v1/files/:file_key/variables/local` | GET | 2 | `file_variables:read` | Local and referenced remote variables |
| `/v1/files/:file_key/variables/published` | GET | 2 | `file_variables:read` | Published variables from file |
| `/v1/files/:file_key/variables` | POST | 3 | `file_variables:write` | Bulk create/update/delete variables |

### 2.4 Comment Endpoints

| Endpoint | Method | Scope | Purpose |
|---|---|---|---|
| `/v1/files/:file_key/comments` | GET | `file_comments:read` | List comments on a file |
| `/v1/files/:file_key/comments` | POST | `file_comments:write` | Post a comment |
| `/v1/files/:file_key/comments/:comment_id` | DELETE | `file_comments:write` | Delete a comment |
| `/v1/files/:file_key/comments/:comment_id/reactions` | GET | `file_comments:read` | List reactions on a comment |
| `/v1/files/:file_key/comments/:comment_id/reactions` | POST | `file_comments:write` | Post a reaction |

### 2.5 Version Endpoints

| Endpoint | Method | Scope | Purpose |
|---|---|---|---|
| `/v1/files/:file_key/versions` | GET | `file_versions:read` | List version history |

### 2.6 Project Endpoints

| Endpoint | Method | Scope | Purpose |
|---|---|---|---|
| `/v1/teams/:team_id/projects` | GET | `projects:read` | List projects in a team |
| `/v1/projects/:project_id/files` | GET | `projects:read` | List files in a project |

### 2.7 Dev Resources Endpoints

| Endpoint | Method | Tier | Scope | Purpose |
|---|---|---|---|---|
| `/v1/files/:file_key/dev_resources` | GET | 2 | `file_dev_resources:read` | Get dev resources in a file |
| `/v1/dev_resources` | POST | - | `file_dev_resources:write` | Bulk create dev resources across files |
| `/v1/dev_resources` | PUT | - | `file_dev_resources:write` | Bulk update dev resources |
| `/v1/files/:file_key/dev_resources/:id` | DELETE | 2 | `file_dev_resources:write` | Delete a dev resource |

### 2.8 Webhook Endpoints

| Endpoint | Method | Tier | Scope | Purpose |
|---|---|---|---|---|
| `/v2/webhooks` | POST | 2 | `webhooks:write` | Create a webhook |
| `/v2/webhooks/:webhook_id` | GET | 2 | `webhooks:read` | Get webhook details |
| `/v2/webhooks/:webhook_id` | PUT | 2 | `webhooks:write` | Update a webhook |
| `/v2/webhooks/:webhook_id` | DELETE | 2 | `webhooks:write` | Delete a webhook |
| `/v2/webhooks` | GET | - | `webhooks:read` | List webhooks by context or plan |
| `/v2/webhooks/:webhook_id/requests` | GET | - | `webhooks:read` | Past 7 days of webhook requests |

### 2.9 Library Analytics Endpoints (Enterprise Only)

| Endpoint | Method | Scope | Purpose |
|---|---|---|---|
| `/v1/analytics/libraries/actions` | GET | `library_analytics:read` | Action time series data |
| `/v1/analytics/libraries/usages` | GET | `library_analytics:read` | Library usage grouped by dimensions |

### 2.10 User and Activity Endpoints

| Endpoint | Method | Scope | Purpose |
|---|---|---|---|
| `/v1/me` | GET | `current_user:read` | Current user profile |
| `/v1/activity_logs` | GET | `org:activity_log_read` | Organization activity logs (Enterprise) |

### 2.11 Payments Endpoint

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/payments` | GET | Payment information for plugins/widgets |

---

## 3. Extracting Design Tokens Programmatically

### 3.1 Via the REST API Variables Endpoints (Enterprise)

The most robust approach. The Variables REST API exposes all variables
(which function as design tokens) with their:

- **Collections** (groupings of related variables)
- **Modes** (e.g., "Light", "Dark", "Compact", "Comfortable")
- **Values per mode** for each variable
- **Variable aliases** (references between variables for token hierarchies)
- **Scoping** (which property types a variable can bind to)

Workflow:
1. `GET /v1/files/:file_key/variables/local` to enumerate all variables
2. Parse the response to extract collections, modes, and values
3. Map to your token format (CSS custom properties, SCSS variables, Tailwind
   config, W3C Design Token Format, Style Dictionary JSON, etc.)

### 3.2 Via the GET File Endpoint (Any Plan)

The `GET /v1/files/:key` response includes `styles` metadata and node properties
with applied colors, typography, spacing, etc. You can:

1. Fetch the full file or specific nodes
2. Traverse the node tree to extract paint fills, text styles, effects, etc.
3. Deduplicate and map to tokens

**Limitations:** No access to variable names, modes, or aliases. You only get
resolved values as they appear on nodes.

### 3.3 Via the Plugin API

The Plugin API (`figma.variables` namespace) provides full read/write access
to variables within the currently open file. This is the approach used by
popular plugins:

- **Figma Token Exporter** -- exports variables to CSS, SASS, and other formats
- **Design Tokens plugin (lukasoppermann)** -- exports to Amazon Style
  Dictionary-compatible JSON
- **Tokens Studio** -- bidirectional sync between Figma tokens and JSON/GitHub

### 3.4 Via Figma's Built-in Export

Figma can export variables as JSON directly from the UI. The export includes
collection names, modes, variable names, and values.

### 3.5 W3C Design Token Standard

The W3C Design Token Community Group is developing a standard format for design
tokens. Converting Figma output to this intermediate format future-proofs
your pipeline. The format structure:

```json
{
  "color": {
    "primary": {
      "$value": "#0066FF",
      "$type": "color"
    }
  },
  "spacing": {
    "small": {
      "$value": "8px",
      "$type": "dimension"
    }
  }
}
```

---

## 4. Variables and Styles in the API

### 4.1 Variables

Variables in Figma are the equivalent of **design tokens**. They store reusable
values that can be applied to design properties and prototyping actions.

#### Supported Variable Types (`resolvedType`)

| Type | Description | Example Use |
|---|---|---|
| `BOOLEAN` | True/false values | Visibility toggles, feature flags |
| `FLOAT` | Numeric values | Spacing, sizing, border-radius, opacity |
| `STRING` | Text values | Font family names, content strings |
| `COLOR` | RGBA color values | Fill colors, stroke colors, text colors |

#### Variable Collections

Collections are containers that organize related variables. Each collection
can have multiple **modes** (such as "Light" and "Dark" themes), and each
variable in the collection can have different values per mode.

- Maximum: 40 modes per collection, 5000 variables per collection
- Mode names: maximum 40 characters
- Extended collections are supported via `parentVariableCollectionId`

#### Variable Aliases

A variable alias is a reference from one variable to another, enabling
hierarchical token systems:

```
color/primary  -->  resolved: #0066FF
button/bg      -->  alias to: color/primary  -->  resolved: #0066FF
```

#### Variable Scoping

Variables can be scoped to specific property types. Recent additions (2025)
include typography-specific scopes:

- Font family, font style/weight, font size
- Line height, letter spacing, paragraph spacing
- Fill color, stroke color, effect color
- Corner radius, gap, padding
- Width, height, opacity

### 4.2 Styles

Styles in the Figma REST API represent published, reusable design decisions.
They are distinct from variables:

| Aspect | Styles | Variables |
|---|---|---|
| **API Access** | Any plan via component/style endpoints | Enterprise only via Variables API |
| **Types** | FILL, TEXT, EFFECT, GRID | BOOLEAN, FLOAT, STRING, COLOR |
| **Modes** | No multi-mode support | Multi-mode (Light/Dark, etc.) |
| **Aliasing** | No native aliasing | Variable aliases supported |
| **Write Access** | Read-only via REST API | Read/Write via REST API (Enterprise) |

Styles are accessed through the component/style endpoints or via the `styles`
property in the GET File response.

---

## 5. Write / Update Access (Bidirectional)

### 5.1 What CAN Be Written via REST API

| Resource | Write Access | Endpoint |
|---|---|---|
| Variables | CREATE, UPDATE, DELETE | `POST /v1/files/:file_key/variables` |
| Variable Collections | CREATE, UPDATE, DELETE | `POST /v1/files/:file_key/variables` |
| Variable Modes | CREATE, UPDATE, DELETE | `POST /v1/files/:file_key/variables` |
| Comments | CREATE, DELETE | `POST/DELETE /v1/files/:file_key/comments/...` |
| Comment Reactions | CREATE, DELETE | `POST/DELETE .../reactions` |
| Dev Resources | CREATE, UPDATE, DELETE | `POST/PUT/DELETE /v1/dev_resources/...` |
| Webhooks | CREATE, UPDATE, DELETE | `POST/PUT/DELETE /v2/webhooks/...` |

### 5.2 What CANNOT Be Written via REST API

- **File content** (nodes, layers, frames, components): READ-ONLY
- **Styles**: READ-ONLY
- **Component definitions**: READ-ONLY
- **File structure** (pages, canvas): READ-ONLY
- **Version history**: READ-ONLY
- **Branches**: Cannot create or merge branches via API

### 5.3 Critical Limitations on Write Access

1. **Variables write requires Enterprise plan** with a Full seat and edit
   access to the file
2. **No file content mutation** -- you cannot create, move, resize, restyle,
   or delete layers/nodes via the REST API
3. **No branch management** -- you cannot create branches via the API, so
   there is no git-like workflow for governing design changes
4. **Immediate effect** -- POSTed variable updates exist in the main file
   immediately with no review/approval gate
5. **Must publish after write** -- after modifying variables via REST API,
   you must publish them before other files can access the updated values

### 5.4 Bidirectional Sync Pattern

The canonical bidirectional design system sync pattern:

```
Code Repository                         Figma File
     |                                      |
     |  1. LIBRARY_PUBLISH webhook fires    |
     |<-------------------------------------|
     |                                      |
     |  2. GET /variables/published         |
     |------------------------------------->|
     |                                      |
     |  3. Transform to code tokens         |
     |  4. Commit to repo / PR              |
     |                                      |
     |  5. Code changes to tokens           |
     |  6. Transform to Figma format        |
     |                                      |
     |  7. POST /variables (update)         |
     |------------------------------------->|
     |                                      |
     |  8. Publish in Figma                 |
     |                                      |
```

### 5.5 Plugin API Write Capabilities

For full write access to file content, you must use the Plugin API, which
supports:

- Creating/deleting/moving/resizing any node type
- Modifying fills, strokes, effects, text content
- Creating/updating components, component sets, and instances
- Creating/updating styles
- Full variable manipulation
- **Limitation:** Requires Figma to be open, single-file scope, user present

---

## 6. Plugin API vs REST API

### Comprehensive Comparison

| Capability | Plugin API | REST API |
|---|---|---|
| **Read file content** | Full (current file) | Full (any accessible file) |
| **Write file content** | Full (create/edit/delete nodes) | NOT SUPPORTED |
| **Write variables** | Full | Full (Enterprise only) |
| **Write styles** | Full | NOT SUPPORTED |
| **Multi-file access** | Only via calling REST API from plugin | Native |
| **Background execution** | NOT SUPPORTED (user must be present) | Full |
| **Comments** | NOT SUPPORTED | Full read/write |
| **Version history** | NOT SUPPORTED | Read-only |
| **Webhooks** | NOT SUPPORTED | Full CRUD |
| **Dev resources** | Read/write | Full CRUD |
| **Requires Figma open** | YES | NO |
| **Rate limits** | N/A | Tier-based per plan |
| **Runtime environment** | Sandboxed JavaScript in Electron/browser | Any HTTP client |
| **Technology** | JavaScript/HTML | Any language with HTTP support |
| **Distribution** | Figma plugin store (requires review) | Self-hosted |
| **Scope** | Single open file | Organization-wide |

### Widget API (Third Option)

The Widget API is a third interface for building persistent on-canvas elements
visible to all file viewers. Widgets can call the REST API and provide
interactive UI elements within the canvas.

### When to Use Which

- **Plugin API:** Interactive tools that modify file content in real-time
  (generating layouts, applying styles, importing assets, design-to-code
  within Figma)
- **REST API:** Automated workflows, CI/CD integration, cross-file analysis,
  design system synchronization, external tool integration, change monitoring
- **Both combined:** A plugin can call the REST API to access data from other
  files while writing to the current file

---

## 7. Variables API Deep Dive

### 7.1 GET Local Variables

```
GET /v1/files/:file_key/variables/local
```

**Scope:** `file_variables:read`
**Tier:** 2
**Plan:** Enterprise (Full members only)

Returns all local variables and remote variables referenced in the file.
Remote variables are identified by their `subscribed_id`.

**Response structure:**

```json
{
  "status": 200,
  "error": false,
  "meta": {
    "variableCollections": {
      "<collection_id>": {
        "id": "VariableCollectionId:123:456",
        "name": "Colors",
        "key": "abc123...",
        "modes": [
          { "modeId": "123:0", "name": "Light" },
          { "modeId": "123:1", "name": "Dark" }
        ],
        "defaultModeId": "123:0",
        "remote": false,
        "hiddenFromPublishing": false
      }
    },
    "variables": {
      "<variable_id>": {
        "id": "VariableID:789:012",
        "name": "color/primary",
        "key": "def456...",
        "variableCollectionId": "VariableCollectionId:123:456",
        "resolvedType": "COLOR",
        "valuesByMode": {
          "123:0": { "r": 0, "g": 0.4, "b": 1, "a": 1 },
          "123:1": { "r": 0.3, "g": 0.6, "b": 1, "a": 1 }
        },
        "remote": false,
        "description": "Primary brand color",
        "hiddenFromPublishing": false,
        "scopes": ["ALL_FILLS"],
        "codeSyntax": {}
      }
    }
  }
}
```

**Key details:**
- Includes variables deleted in the editor that may still be referenced
- Variable aliases appear as `{ "type": "VARIABLE_ALIAS", "id": "VariableID:..." }`
  in `valuesByMode`
- `codeSyntax` can contain platform-specific token names (web, iOS, Android)

### 7.2 GET Published Variables

```
GET /v1/files/:file_key/variables/published
```

**Scope:** `file_variables:read`
**Tier:** 2
**Plan:** Enterprise

Differences from local endpoint:
- Each variable/collection includes a `subscribed_id`
- Modes are omitted from published variable collections
- `id` and `key` are stable; `subscribed_id` changes on each publish
- `updatedAt` fields indicate last publish timestamp
- Must use main file key (not branch key)

### 7.3 POST Variables (Bulk Create/Update/Delete)

```
POST /v1/files/:file_key/variables
```

**Scope:** `file_variables:write`
**Tier:** 3
**Plan:** Enterprise (Full seat + edit access)
**Body limit:** 4 MB

Request body contains four arrays:

```json
{
  "variableCollections": [
    {
      "action": "CREATE",
      "id": "temp_collection_1",
      "name": "Spacing",
      "initialModeId": "temp_mode_1"
    }
  ],
  "variableModes": [
    {
      "action": "CREATE",
      "id": "temp_mode_2",
      "name": "Compact",
      "variableCollectionId": "temp_collection_1"
    }
  ],
  "variables": [
    {
      "action": "CREATE",
      "id": "temp_var_1",
      "name": "spacing/small",
      "variableCollectionId": "temp_collection_1",
      "resolvedType": "FLOAT"
    }
  ],
  "variableModeValues": [
    {
      "variableId": "temp_var_1",
      "modeId": "temp_mode_1",
      "value": 8
    },
    {
      "variableId": "temp_var_1",
      "modeId": "temp_mode_2",
      "value": 4
    }
  ]
}
```

**Key behaviors:**
- Each object requires an `action` field: `CREATE`, `UPDATE`, or `DELETE`
- Temporary IDs can be used for cross-referencing within a single request
- `tempIdToRealId` mapping is returned in the response
- New collections always include one default mode; reference it via
  `initialModeId`
- Extended collections supported via `parentVariableCollectionId`
- Constraints: max 40 modes per collection, max 5000 variables per collection,
  40-char mode name limit

### 7.4 Variable Scoping (2025 additions)

New `VariableScope` options for typography:
- `FONT_FAMILY`
- `FONT_STYLE`
- `FONT_WEIGHT`
- `FONT_SIZE`
- `LINE_HEIGHT`
- `LETTER_SPACING`
- `PARAGRAPH_SPACING`
- `PARAGRAPH_INDENT`

Plus existing scopes:
- `ALL_FILLS`, `FRAME_FILL`, `SHAPE_FILL`, `TEXT_FILL`, `STROKE_COLOR`
- `EFFECT_COLOR`
- `CORNER_RADIUS`
- `WIDTH_HEIGHT`
- `GAP`
- `OPACITY`
- `ALL_SCOPES`

---

## 8. REST API and Dev Mode

### 8.1 Dev Resources

Dev resources are developer-contributed URLs attached to design nodes that
appear in Figma's Dev Mode. They enable bidirectional linking between Figma
and external tools.

**Key characteristics:**
- Can be attached to any node in a file
- Do NOT require publishing -- immediately available when created/updated
- When attached to published components, available instantly in all files
  using those components (no republish needed)
- Support cross-file bulk operations

**Example use case:** Figma's Jira integration creates dev resources
automatically when linking Figma files from Jira issues, establishing
bidirectional links.

### 8.2 Code Connect

Code Connect bridges your codebase and Figma's Dev Mode, connecting source
code components to Figma design components. Two approaches:

#### Code Connect UI (newer, runs inside Figma)
- Connects to GitHub for repository context
- Provides component paths and names
- AI-generated code examples based on connected source files
- No GitHub connection required -- manual mapping is supported

#### Code Connect CLI (developer-focused)
- Runs from terminal within local codebase
- Publishes connections to Figma
- Property mappings and dynamic code examples
- Replaces autogenerated snippets with production code in Dev Mode

**Framework support:** React, React Native, Storybook, HTML (Web Components,
Angular, Vue), SwiftUI, Jetpack Compose

**Plan requirement:** Organization and Enterprise plans, Full Design or Dev
Mode seat

### 8.3 DEV_MODE_STATUS_UPDATE Webhook

Tracks when layers change Dev Mode status:
- Marked "Ready for Dev"
- Marked "Completed"
- Status cleared

Includes change messages if provided. Useful for automated handoff tracking.

---

## 9. Design-to-Code Pipelines

### 9.1 Architecture Patterns

#### Pattern A: Direct API Extraction

```
Figma File
    |
    v
GET /v1/files/:key (full tree)
    |
    v
Parse node tree --> Extract design properties
    |
    v
Code generation (components, tokens, assets)
    |
    v
Codebase
```

#### Pattern B: Token-Centric Pipeline

```
Figma Variables
    |
    v
GET /v1/files/:key/variables/local
    |
    v
Transform to W3C Design Token Format / Style Dictionary
    |
    v
Generate platform-specific tokens
    |
    v
CSS / SCSS / Tailwind / iOS / Android
```

#### Pattern C: Webhook-Driven Continuous Sync

```
Figma publishes library
    |
    v
LIBRARY_PUBLISH webhook --> Your server
    |
    v
GET updated variables + components
    |
    v
Transform + generate code
    |
    v
Create PR / commit to repository
    |
    v
CI/CD deploys updated design system
```

#### Pattern D: MCP-Augmented AI Pipeline (Most Relevant to VaultSpec)

```
Figma MCP Server
    |
    v
AI Agent reads design context (screenshots, tokens, structure)
    |
    v
Code Connect provides component mappings
    |
    v
Agent generates implementation using actual codebase components
    |
    v
Browser verification via Playwright/DevTools
```

### 9.2 Key Tools in the Ecosystem

| Tool | Type | Capabilities |
|---|---|---|
| **Figma MCP Server** | AI bridge | Read design data for LLM-powered code generation |
| **Anima** | Plugin + API | Figma-to-React/HTML code generation with Tailwind/ShadCN |
| **Code Connect** | CLI + UI | Map Figma components to codebase components |
| **Style Dictionary** | Transform tool | Convert tokens to multi-platform output |
| **Tokens Studio** | Plugin | Bidirectional token sync with GitHub |
| **figma-extractor** | CLI (Go) | Extract design specs as markdown with CSS variables |

### 9.3 Best Practices

1. **Consistent naming** in Figma files -- use slash-separated hierarchical
   names (e.g., `color/primary/500`)
2. **Auto-layout** for responsive component extraction
3. **Variables over styles** for token management (when on Enterprise)
4. **Component-first conversion** -- extract individual components before
   composing larger sections
5. **Design tokens as intermediary** -- always generate a standard token
   format before platform-specific output

---

## 10. Webhooks and Change Detection

### 10.1 Webhook Architecture

**Contexts:** Webhooks attach to a specific context:

| Context | Max Webhooks | Required Permission |
|---|---|---|
| Team | 20 | Team admin |
| Project | 5 | Can edit |
| File | 3 | Can edit |

File webhook limits scale by plan: Professional (150), Organization (300),
Enterprise (600).

**Important:** Figma does NOT have a UI for managing webhooks. All
CRUD operations must go through the API.

### 10.2 Event Types

| Event | Description | Payload Includes |
|---|---|---|
| `PING` | Confirmation on webhook creation | Webhook ID |
| `FILE_UPDATE` | File content changes | File name, file key |
| `FILE_VERSION_UPDATE` | New version saved | File name, file key, version info |
| `FILE_DELETE` | File deleted | File name, file key |
| `FILE_COMMENT` | Comment added/modified | File name, file key, comment data |
| `LIBRARY_PUBLISH` | Library published | File name, file key, variable data |
| `DEV_MODE_STATUS_UPDATE` | Layer dev status changes | File name, file key, status, message |

### 10.3 Payload Structure

Every payload (except PING) contains:
- `file_name` -- human-readable file name
- `file_key` -- unique file identifier for API calls
- Event-specific data

### 10.4 Retry Logic

| Attempt | Delay After Failure |
|---|---|
| 1st retry | 5 minutes |
| 2nd retry | 30 minutes |
| 3rd retry (final) | 3 hours |

Server must return `200 OK`. Any other status or timeout is treated as failure.

### 10.5 Webhook Setup Example

```bash
# Create a webhook for a team
curl -X POST 'https://api.figma.com/v2/webhooks' \
  -H 'X-Figma-Token: <PAT>' \
  -H 'Content-Type: application/json' \
  -d '{
    "event_type": "LIBRARY_PUBLISH",
    "team_id": "<TEAM_ID>",
    "endpoint": "https://your-server.com/figma-webhook",
    "passcode": "your-secret-passcode",
    "description": "Design system sync trigger"
  }'
```

### 10.6 Design System Automation with Webhooks

Practical workflow:
1. Designer updates variables in Figma library file
2. Designer publishes the library
3. `LIBRARY_PUBLISH` webhook fires to your server
4. Server calls `GET /v1/files/:key/variables/published` to get updated tokens
5. Server transforms tokens to code format
6. Server creates a PR in the design system repository
7. CI runs, PR is reviewed and merged
8. Updated design system is deployed

---

## 11. Authentication and Access Tokens

### 11.1 Personal Access Tokens (PATs)

**Generation:**
1. Log into Figma
2. Settings > Security tab
3. "Generate new token"
4. Set expiration and scopes
5. Copy immediately (shown only once)

**Usage in requests:**
```
X-Figma-Token: <YOUR_TOKEN>
```

**Constraints (as of 2025):**
- Maximum 90-day expiration enforced
- Non-expiring tokens no longer supported
- Scopes must be specified at generation time
- Rate limits apply per-user

### 11.2 OAuth 2.0

**Setup flow:**
1. Create OAuth app at `figma.com/developers/apps`
2. Configure redirect URLs, scopes, visibility (draft/private/public)
3. Obtain Client ID and Client Secret

**Authorization URL:**
```
GET https://www.figma.com/oauth?
  client_id=:client_id&
  redirect_uri=:callback&
  scope=:scope&
  state=:state&
  response_type=code
```

**Token exchange:**
```
POST https://api.figma.com/v1/oauth/token
```

Using HTTP Basic Auth with Base64-encoded `client_id:client_secret`.

**Critical:** Authentication codes expire after **30 seconds**.

**Token response:**
```json
{
  "user_id_string": "<USER_ID>",
  "access_token": "<TOKEN>",
  "token_type": "bearer",
  "expires_in": 7776000,
  "refresh_token": "<REFRESH_TOKEN>"
}
```

**Token refresh:**
```
POST https://api.figma.com/v1/oauth/token
```
(Previously `/v1/oauth/refresh`, legacy endpoint still works)

**Access token lifetime:** 90 days, refreshable via refresh token.

**PKCE support:** Available for enhanced security.

**Usage in requests:**
```
Authorization: Bearer <ACCESS_TOKEN>
```

### 11.3 Complete Scope Reference

| Scope | Description | PAT | OAuth |
|---|---|---|---|
| `current_user:read` | User profile data | Yes | Yes |
| `file_content:read` | File contents and nodes | Yes | Yes |
| `file_comments:read` | View file comments | Yes | Yes |
| `file_comments:write` | Create/delete comments and reactions | Yes | Yes |
| `file_dev_resources:read` | View dev resources | Yes | Yes |
| `file_dev_resources:write` | Create dev resources | Yes | Yes |
| `file_metadata:read` | Read file metadata | Yes | Yes |
| `file_variables:read` | Access variables (Enterprise) | Yes | Yes |
| `file_variables:write` | Modify variables (Enterprise) | Yes | Yes |
| `file_versions:read` | View version history | Yes | Yes |
| `files:read` | **DEPRECATED** -- broad access | Yes | Yes |
| `library_analytics:read` | Design system analytics (Enterprise) | Yes | Yes |
| `library_assets:read` | Published component/style data | Yes | Yes |
| `library_content:read` | Published components and styles | Yes | Yes |
| `org:activity_log_read` | Org activity logs (Enterprise, admin) | Yes | Yes |
| `org:discovery_read` | Text events (Enterprise Gov+, admin) | Yes | Yes |
| `projects:read` | List projects and files | Yes | Private only |
| `selections:read` | Recent selection data | Yes | Yes |
| `team_library_content:read` | Team components and styles | Yes | Yes |
| `webhooks:read` | Webhook metadata | Yes | Yes |
| `webhooks:write` | Create/manage webhooks | Yes | Yes |

**Important:** Scopes do NOT supersede file/project/team permissions. A token
with `file_content:read` can only access files the user has been granted
access to.

### 11.4 Deprecations and Migration

- `files:read` scope is deprecated; use specific scopes
  (`file_content:read`, `file_comments:read`, etc.)
- Numeric `user_id` in OAuth responses is deprecated; use `user_id_string`
- All public OAuth apps required re-publishing by November 17, 2025
- HTTPS enforced; HTTP requests return 403

---

## 12. Rate Limits

### 12.1 Rate Limit Tiers

Each endpoint is assigned a tier reflecting infrastructure cost:

| Tier | Example Endpoints |
|---|---|
| **Tier 1** | GET files, GET file nodes, GET images |
| **Tier 2** | GET image fills, GET local variables, GET dev resources, webhooks |
| **Tier 3** | POST variables, GET components/styles, GET file metadata |

### 12.2 Limits by Plan and Seat Type

| Tier | View/Collab Seats | Dev/Full on Starter | Dev/Full on Pro | Dev/Full on Org | Dev/Full on Enterprise |
|---|---|---|---|---|---|
| Tier 1 | Up to 6/month | 10/min | 15/min | 20/min | 20/min |
| Tier 2 | Up to 5/min | 25/min | 50/min | 100/min | 100/min |
| Tier 3 | Up to 10/min | 50/min | 100/min | 150/min | 150/min |

**Note:** View/Collab seats have a monthly cap for Tier 1 (6 requests/month).
This is extremely restrictive.

### 12.3 Algorithm

Figma uses a **leaky bucket algorithm**. When the bucket overflows, the API
returns `429 Too Many Requests` with headers:

| Header | Description |
|---|---|
| `Retry-After` | Seconds to wait before retrying |
| `X-Figma-Plan-Tier` | Plan level of the resource (enterprise, org, pro, starter) |
| `X-Figma-Rate-Limit-Type` | Seat classification (`low` for Collab/Viewer, `high` for Full/Dev) |
| `X-Figma-Upgrade-Link` | URL to pricing or account settings |

### 12.4 Rate Limit Tracking

- **PATs:** Per-user, per-plan, per-file basis
- **OAuth apps:** Per-user, per-plan, per-app basis (more restrictive in
  aggregate since limits apply to entire app across all users)

### 12.5 Best Practices

1. **Batch requests** whenever possible (use `ids` parameter for multiple nodes)
2. **Cache results** aggressively (especially images, which have 30-day URLs)
3. **Implement exponential backoff** when receiving 429 errors
4. **Use the `Retry-After` header** value, not arbitrary sleep durations
5. **Prefer `GET /v1/files/:key/nodes`** over `GET /v1/files/:key`** for
   targeted node access (same tier, less data)
6. **Use webhooks** instead of polling for change detection

---

## 13. Implications for VaultSpec

### 13.1 For the MCP-Driven Frontend Workflow

The CLAUDE.md mandates a Figma-first workflow: **Figma > shadcn-ui > Svelte
MCP > implement > browser verification**. Based on this research:

1. **Figma MCP Server** provides `get_design_context`, `get_screenshot`,
   `get_variable_defs`, and `get_code_connect_map` -- these internally call
   the REST API endpoints documented above
2. **Design token extraction** from the MCP server maps to
   `GET /v1/files/:key/variables/local` under the hood
3. **Code Connect integration** means Figma components can be mapped to the
   project's shadcn-svelte components, providing the AI agent with exact
   component usage patterns

### 13.2 For Automated Design System Sync

If VaultSpec needs to keep design tokens synchronized:

1. Set up `LIBRARY_PUBLISH` webhooks on the design system file
2. On webhook fire, extract variables and transform to Tailwind token format
3. Auto-generate/update Tailwind config and CSS custom properties
4. Create PR for review

### 13.3 Limitations to Be Aware Of

- **Variables API requires Enterprise** -- if the Figma account is not
  Enterprise, design tokens must be extracted via the Plugin API or file
  parsing
- **No file content writes via REST API** -- the MCP server cannot modify
  Figma designs; it is read-only for design content
- **Rate limits are strict on lower plans** -- Starter plan only allows
  10 Tier 1 requests per minute
- **Image URLs expire after 30 days** -- screenshots must be cached or
  re-requested
- **OAuth auth codes expire in 30 seconds** -- token exchange must happen
  immediately

### 13.4 Key Endpoints for VaultSpec's Figma Integration

| Use Case | Endpoint | Plan Required |
|---|---|---|
| Read design structure | `GET /v1/files/:key` | Any |
| Read specific components | `GET /v1/files/:key/nodes?ids=...` | Any |
| Export component images | `GET /v1/images/:key?ids=...` | Any |
| Extract design tokens | `GET /v1/files/:key/variables/local` | Enterprise |
| List published components | `GET /v1/files/:key/components` | Any |
| Detect design changes | `POST /v2/webhooks` (LIBRARY_PUBLISH) | Any (team admin) |
| Track dev handoff status | Webhook: DEV_MODE_STATUS_UPDATE | Any (Can edit) |
| Link code to design | Dev Resources API | Any |

---

## Sources

- [Figma REST API Introduction](https://developers.figma.com/docs/rest-api/)
- [Figma REST API File Endpoints](https://developers.figma.com/docs/rest-api/file-endpoints/)
- [Figma REST API Variables](https://developers.figma.com/docs/rest-api/variables/)
- [Figma REST API Variables Endpoints](https://developers.figma.com/docs/rest-api/variables-endpoints/)
- [Figma REST API Component Endpoints](https://developers.figma.com/docs/rest-api/component-endpoints/)
- [Figma REST API Authentication](https://developers.figma.com/docs/rest-api/authentication/)
- [Figma REST API Scopes](https://developers.figma.com/docs/rest-api/scopes/)
- [Figma REST API Rate Limits](https://developers.figma.com/docs/rest-api/rate-limits/)
- [Figma REST API Webhooks V2](https://developers.figma.com/docs/rest-api/webhooks/)
- [Figma REST API Webhook Types](https://developers.figma.com/docs/rest-api/webhooks-types/)
- [Figma REST API Changelog](https://developers.figma.com/docs/rest-api/changelog/)
- [Compare the Figma APIs](https://developers.figma.com/compare-apis/)
- [Figma REST API Dev Resources](https://developers.figma.com/docs/rest-api/dev-resources/)
- [Figma Dev Resources Endpoints](https://developers.figma.com/docs/rest-api/dev-resources-endpoints/)
- [Figma Code Connect Introduction](https://developers.figma.com/docs/code-connect/)
- [Figma Code Connect CLI](https://developers.figma.com/docs/code-connect/quickstart-guide/)
- [Figma Code Connect UI](https://developers.figma.com/docs/code-connect/code-connect-ui-setup/)
- [Figma Code Connect MCP Integration](https://developers.figma.com/docs/figma-mcp-server/code-connect-integration/)
- [Figma OpenAPI Spec (GitHub)](https://github.com/figma/rest-api-spec)
- [Code Connect GitHub Repository](https://github.com/figma/code-connect)
- [Figma Plugin API Reference](https://developers.figma.com/docs/plugins/api/api-reference/)
- [Figma Token Exporter](https://figma-tokens.com/)
- [Design Tokens Plugin (lukasoppermann)](https://github.com/lukasoppermann/design-tokens)
- [figma-extractor](https://github.com/kataras/figma-extractor)
- [Manage Personal Access Tokens](https://help.figma.com/hc/en-us/articles/8085703771159-Manage-personal-access-tokens)
- [Guide to Variables in Figma](https://help.figma.com/hc/en-us/articles/15339657135383-Guide-to-variables-in-Figma)
- [Synchronizing Figma Variables with Design Tokens (Nate Baldwin)](https://medium.com/@NateBaldwin/synchronizing-figma-variables-with-design-tokens-3a6c6adbf7da)
- [Automating Design System Sync via Variables REST API (Agshin Rajabov)](https://medium.com/@agshinrajabov/automating-the-synchronization-of-design-systems-using-the-figma-variables-rest-api-6c54deffbb75)
- [Getting Started with Figma Webhooks](https://souporserious.com/getting-started-with-figma-webhooks/)
- [Advanced Figma Webhook Integration](https://blog.poespas.me/posts/2025/02/13/advanced-figma-webhook-integration/)
- [Component Generation with Figma API (DEV Community)](https://dev.to/krjakbrjak/component-generation-with-figma-api-bridging-the-gap-between-development-and-design-1nho)
