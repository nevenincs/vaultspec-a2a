---
date: 2026-02-28
type: audit
feature: code-connect
description: 'Initial Code Connect audit of all 27 .figma.tsx mapping files identifying 12 TypeScript errors, 3 type-correctness issues, and 2 figma.config.json problems before fixes.'
related:
  - docs/adrs/2026-02-28-018-react-tailwind-figma-migration-adr.md
  - docs/adrs/2026-03-01-019-figma-developer-workflow-adr.md
---

# Code Connect Audit Report

**Date**: 2026-02-28 (deep pass: 2026-03-01)
**Auditor**: opus (auditor agent)
**Scope**: All `.figma.tsx`Code Connect mapping files,`figma.config.json`,
package.json dependency, TypeScript correctness, build verification, CVA variant
enum validation, and dry-run publish verification.

---

## Summary

- **Total .figma.tsx files**: 27 (15 domain + 12 UI primitives)
- **Total figma.connect() calls**: 28 (message-bubble.figma.tsx has 2:
  UserBubble + AgentBubble)
- **TypeScript errors**: 12 (across 9 files)
- **Additional type-correctness issues** (not caught by tsc due to excess
  property erasure in JSX): 3
- **Build status**: PASS (vite build succeeds, 3433 modules, 6.87s)
- **Dry-run publish**: PASS (28 mappings detected, fails at auth as expected)
- **figma.config.json**: 2 issues (importPaths mapping incorrect, overly broad
  include)
- **CVA variant enums**: Button (7/7 match), Badge (4/4 match)
- **Coverage**: All 15 domain components covered. 12 of ~47 UI primitives
  covered.

---

## Findings

### CRITICAL (3)

#### C1. `sequence`property does not exist on StreamEvent types

**Files affected**: 7 files

-`message-bubble.figma.tsx`(lines 21, 47) -`thought-block.figma.tsx`(line 22) -`tool-call-card.figma.tsx`(line 32) -`artifact-card.figma.tsx`(line 25) -`error-alert.figma.tsx`(line 21) -`inspector-panel.figma.tsx`(line 38)

**Issue**: All event mock objects include`sequence: N` but the TypeScript types
(`UserMessageEvent`, `AgentMessageEvent`, `ThoughtEvent`, `ToolCallEvent`,
`ArtifactEvent`, `ErrorStreamEvent`) in `data/types.ts`do not have
a`sequence`property. The`BaseStreamEvent`interface only has:`id`, `type`,
`timestamp`, `thread_id`.

**Fix**: Remove `sequence` from all mock event objects, add missing required
fields (`id`, `thread_id`) that ARE on the types.

**TypeScript errors**: TS2353 x 7

#### C2. `PermissionRequest.tool_kind`set to invalid value`'shell'`

**File**: `permission-modal.figma.tsx`(line 30)

| **Issue**:`tool_kind: 'shell'`but`ToolKind`is`'read' | 'edit' | 'search' |
'execute' | 'browser' | 'mcp' | 'other'`. There is no `'shell'`variant. |

**Fix**: Change to`tool_kind: 'execute'`.

**TypeScript error**: TS2322

#### C3. Missing required `id`and`thread_id`on all event mock objects

**Files affected**: All domain component .figma.tsx files using event props

**Issue**: The event mock objects are missing required`id: string`and`thread_id:
string`fields from`BaseStreamEvent`. When `sequence`is removed, these are still
absent. The mock objects will fail TypeScript strict checks.

**Fix**: Add`id`and`thread_id`to all event mock objects in .figma.tsx files.

### HIGH (5)

#### H1.`PlanEntry`mock includes non-existent`description`property

**File**:`plan-update-card.figma.tsx`(lines 20-22)

**Issue**: Each`PlanEntry`in the example includes`description:
''`but`PlanEntry`has:`{ id, title, status, priority }`-- no`description`field.
Also missing required`priority`field.

**Fix**: Remove`description`, add `priority: 'medium'`to each entry.

**TypeScript errors**: TS2353 x 3

#### H2.`MarkdownEditor`example missing required`onKeyDown`prop

**File**:`markdown-editor.figma.tsx`(line 23)

**Issue**: The`MarkdownEditorProps`interface requires`onKeyDown`but the example
only provides`value`, `onChange`, and `placeholder`.

**Fix**: Add `onKeyDown={() => {}}`to the example.

**TypeScript error**: TS2741

#### H3.`PermissionRequest`mock includes non-existent`thread_id`property

**File**:`permission-modal.figma.tsx`(line 27)

**Issue**: The mock includes`thread_id: 'thread-1'`but`PermissionRequest`does
not have a`thread_id`field. It has:`id`, `agent_id`, `agent_name`, `tool_name`,
`tool_kind`, `message`, `options`. Missing required `agent_id`field.

**Fix**: Remove`thread_id`, add `agent_id: 'agent-1'`.

#### H4. `ArtifactEvent`mocks missing required`artifact_id`and`complete`fields

**Files**:`artifact-card.figma.tsx`(line 14-29),`inspector-panel.figma.tsx`(if
artifact target is added later)

**Issue**: The`ArtifactEvent`type (types.ts:114-123) requires`artifact_id:
string`and`complete: boolean`, but the mock in `artifact-card.figma.tsx`omits
both. TypeScript does not flag this because the excess property`sequence`masks
the check. Once`sequence`is removed and`id`/`thread_id`are added, tsc will
report these as missing.

**Fix**: Add`artifact_id: 'art-1'`and`complete: true`to the artifact event mock.

#### H5.`ToolCallEvent`mocks missing required`tool_call_id`field

**Files**:`tool-call-card.figma.tsx`(line
22-33),`inspector-panel.figma.tsx`(line 28-39)

**Issue**: The`ToolCallEvent`type (types.ts:99-112) requires`tool_call_id:
string`, but the mocks in both files omit it. As with H4, this is masked by the
`sequence`excess property error.

**Fix**: Add`tool_call_id: 'tc-1'`to both ToolCallEvent mock objects.

### MEDIUM (3)

#### M1.`figma.config.json`importPaths mapping is incorrect

**File**:`src/ui/figma.config.json`

**Issue**: The `importPaths`mapping`"src/app/components/*": "@/components"`does
not correctly map to the project's path alias system. The
tsconfig`paths`has`"@/*": ["./src/*"]`, so
`src/app/components/ui/button.tsx`resolves to`@/app/components/ui/button`. The
config maps `src/app/components/*`to`@/components`which would produce incorrect
import paths like`@/components/button`instead of`@/app/components/ui/button`.

**Fix**: Change to `"src/app/components/*": "@/app/components"`or remove the
mapping entirely since all .figma.tsx files use relative imports
(e.g.,`./button`).

#### M2. `figma.config.json`include array is overly broad

**File**:`src/ui/figma.config.json`

**Issue**: The `include`array contains`"src/**/*.tsx"`and`"src/**/*.ts"`in
addition to`"src/**/*.figma.tsx"`. This means Code Connect will scan ALL source
files, not just `.figma.tsx`mapping files. While it won't cause incorrect
behavior (non-mapping files are ignored), it adds unnecessary I/O overhead
during`figma connect parse`and`publish`.

**Fix**: Remove `"src/**/*.tsx"`and`"src/**/*.ts"`from the include array,
keeping only`"src/**/*.figma.tsx"`.

#### M3. Only 12 of ~47 UI primitives have Code Connect mappings

**Files**: 12 UI .figma.tsx files created

**Covered**: button, badge, input, tooltip, scroll-area, dialog, alert-dialog,
tabs, card, popover, separator, skeleton

**Missing notable ones**: checkbox, collapsible, select, dropdown-menu,
textarea, progress, resizable, sheet, sidebar (shadcn), switch, table, toggle,
toggle-group, command, context-menu, hover-card, accordion, avatar, breadcrumb,
radio-group, slider, navigation-menu, menubar, form, label, drawer, carousel,
calendar, aspect-ratio, input-otp, notification-pills

**Assessment**: The 12 covered primitives are the most actively used ones in the
codebase. Missing primitives like `textarea`, `checkbox`, `select`, and
`progress`are used but less critical. This is acceptable for an initial pass.

### LOW (1)

#### L1. All Figma URLs point to Make project root, not specific component nodes

**Files**: All 27 .figma.tsx files

**Issue**: Every`figma.connect()`call uses the same
URL:`https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface`without
a`?node-id=`parameter. This means all mappings point to the project root rather
than their specific Figma component node. While Code Connect will still
function, the mappings won't link directly to the correct component in Figma's
UI.

**Fix**: Obtain specific node IDs from Figma for each component and
append`?node-id=X:Y`to each URL. This can be done via the Figma
MCP`get_metadata` tool.

---

## Positive Findings (Deep Pass)

### CVA Variant Enum Verification

**Button** (`button.figma.tsx`vs`button.tsx`):

- CVA variants: `default`, `destructive`, `outline`, `secondary`, `ghost`,
  `link`, `terminal`-- **all 7 mapped correctly**
- CVA sizes:`default`, `sm`, `lg`, `icon`-- **all 4 mapped correctly** -`figma.boolean('Disabled')`and`figma.string('Label')` are appropriate

**Badge** (`badge.figma.tsx`vs`badge.tsx`):

- CVA variants: `default`, `secondary`, `destructive`, `outline`-- **all 4
  mapped correctly** -`figma.string('Label')`is appropriate

### Component Prop Accuracy (non-event components)

-`app-shell.figma.tsx`: No props, correct (AppShell takes none)

- `status-bar.figma.tsx`: No props, correct (StatusBar takes none)
- `sidebar.figma.tsx`: All required props provided (threads, activeTabId,
  openTransient, openPinned, clearActiveTab), optional onFocusSearchRef
  correctly omitted
- `tab-bar.figma.tsx`: All required props provided (tabs, activeTabId, threads,
  activateTab, pinTab, closeTab)
- `message-stream.figma.tsx`: Required props provided (events, onInspect,
  emptyState, agentState), optional props correctly omitted
- `input-bar.figma.tsx`: Required props provided (agentState, onSend), optional
  props selectively included (teamPresets, isNewThread)
- All UI primitive .figma.tsx files use correct relative imports
- All `figma.enum()`, `figma.string()`, `figma.boolean()` calls are semantically
  correct

### Dry-Run Publish Verification

```bash
npx figma connect publish --dry-run
Config file found, parsing using specified include globs
Files that would be published: 28 mappings across 27 files
- 12 UI primitives: Tooltip, Tabs, Skeleton, Separator, ScrollArea, Popover,
  Input, Dialog, Card, Button, Badge, AlertDialog
- 16 domain components: ToolCallCard, ThoughtBlock, PlanUpdateCard, MessageStream,
  UserBubble, AgentBubble, MarkdownEditor, InputBar, ErrorAlert, ArtifactCard,
  PermissionModal, TabBar, StatusBar, Sidebar, AppShell, InspectorPanel
Status: PASS (fails at auth token step, expected for dry-run without credentials)
```

---

## Build Verification

```python
vite build: PASS (3433 modules, 6.87s)
TypeScript (tsc --noEmit): FAIL (12 errors in 9 files)
@figma/code-connect: Installed (^1.4.1 in devDependencies)
figma connect publish --dry-run: PASS (28 mappings detected)
```

---

## Verdict

The Code Connect mapping structure is solid: all 15 domain components have
mappings (16 `figma.connect()`calls due to message-bubble split), 12 key UI
primitives are covered, import paths are correct (relative),`figma.connect()`API
usage is correct, and CVA variant enums are accurate.

However, **12 TypeScript errors must be fixed** plus **3 additional
type-correctness issues** (H4, H5) that are currently masked by
the`sequence`excess property error. These are all mock data issues
in`example`functions.

### Required fixes before merge

1. Remove`sequence`from all event mocks, add`id`and`thread_id`(C1, C3)
2. Change`'shell'`to`'execute'`in permission-modal (C2)
3. Remove`description`, add `priority`to PlanEntry mocks (H1)
4. Add`onKeyDown`to MarkdownEditor example (H2)
5. Fix PermissionRequest mock: remove`thread_id`, add `agent_id`(H3)
6. Add`artifact_id`and`complete`to ArtifactEvent mock (H4)
7. Add`tool_call_id`to ToolCallEvent mocks in tool-call-card + inspector-panel
   (H5)
8. Fix or remove`importPaths`in figma.config.json (M1)
9. Trim`include`array in figma.config.json to only`*.figma.tsx` (M2)
