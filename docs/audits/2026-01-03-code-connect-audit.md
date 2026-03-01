# Code Connect Final Audit Report

**Date**: 2026-03-01
**Auditor**: opus (auditor agent)
**Scope**: Re-verification of all `.figma.tsx` Code Connect mapping files after coder fixes (task #10), plus full deep audit per task #9.

---

## Summary

- **Total .figma.tsx files**: 27 (15 domain + 12 UI primitives)
- **Total figma.connect() calls**: 28 (message-bubble.figma.tsx has 2: UserBubble + AgentBubble)
- **TypeScript errors**: 0 (was 12 -- all fixed)
- **Build status**: PASS (vite build, 3433 modules, 6.34s)
- **Dry-run publish**: PASS (28 mappings detected, fails at auth as expected)
- **figma.config.json**: 1 remaining minor issue (overly broad include)
- **CVA variant enums**: Button (7/7 match), Badge (4/4 match)
- **Coverage**: All 15 domain components covered. 12 of ~47 UI primitives covered.

---

## Fix Verification (9 required fixes from initial audit)

| # | Finding | Status | Verification |
|---|---------|--------|-------------|
| C1 | Remove `sequence` from all event mocks | FIXED | Removed from all 7 files. No `sequence` property in any .figma.tsx |
| C2 | Change `'shell'` to `'execute'` in permission-modal | FIXED | `tool_kind: 'execute'` at permission-modal.figma.tsx:30 |
| C3 | Add `id` and `thread_id` to all event mocks | FIXED | All mocks have `id: 'evt-N'` and `thread_id: 'thread-1'` |
| H1 | Remove `description`, add `priority` to PlanEntry mocks | FIXED | `description` removed, `priority: 'high'\|'medium'` added |
| H2 | Add `onKeyDown` to MarkdownEditor example | FIXED | `onKeyDown={() => {}}` at markdown-editor.figma.tsx:26 |
| H3 | Fix PermissionRequest mock (remove `thread_id`, add `agent_id`) | FIXED | `agent_id: 'agent-1'` added, `thread_id` removed |
| H4 | Add `artifact_id` and `complete` to ArtifactEvent mock | FIXED | `artifact_id: 'art-1'`, `complete: true` at artifact-card.figma.tsx:21,24 |
| H5 | Add `tool_call_id` to ToolCallEvent mocks | FIXED | `tool_call_id: 'tc-1'` in tool-call-card.figma.tsx:27 and inspector-panel.figma.tsx:32 |
| M1 | Fix `importPaths` in figma.config.json | FIXED | Changed to `"src/app/components/*": "@/app/components"` |

**8 of 9 fixes applied.** M2 (trim `include` to only `*.figma.tsx`) was NOT applied -- the include array still contains `"src/**/*.tsx"` and `"src/**/*.ts"`. This is cosmetic (causes extra scanning, not incorrect behavior).

---

## Remaining Issues

### MEDIUM (1)

#### M2. `figma.config.json` include array is overly broad (NOT FIXED)
**File**: `src/ui/figma.config.json`

**Issue**: The `include` array contains `"src/**/*.tsx"` and `"src/**/*.ts"` in addition to `"src/**/*.figma.tsx"`. Code Connect scans all matched files looking for `figma.connect()` calls, so this adds unnecessary I/O.

**Fix**: Remove `"src/**/*.tsx"` and `"src/**/*.ts"`, keeping only `"src/**/*.figma.tsx"`.

**Impact**: Low. Functional correctness is unaffected.

### LOW (1)

#### L1. All Figma URLs point to Make project root, not specific component nodes (DEFERRED)
**Files**: All 27 .figma.tsx files

**Issue**: Every `figma.connect()` call uses the same URL without a `?node-id=` parameter. This is acceptable for initial deployment but should be addressed when specific Figma component node IDs are available.

---

## Deep Audit Verification

### TypeScript Correctness
```
npx tsc --noEmit: PASS (0 errors)
```

### Build
```
npm run build: PASS (3433 modules, 6.34s)
```

### Dry-Run Publish
```
npx figma connect publish --dry-run: PASS
28 mappings detected across 27 files:
  UI primitives (12): Tooltip, Tabs, Skeleton, Separator, ScrollArea,
    Popover, Input, Dialog, Card, Button, Badge, AlertDialog
  Domain components (16): ToolCallCard, ThoughtBlock, PlanUpdateCard,
    MessageStream, UserBubble, AgentBubble, MarkdownEditor, InputBar,
    ErrorAlert, ArtifactCard, PermissionModal, TabBar, StatusBar,
    Sidebar, AppShell, InspectorPanel
```

### CVA Variant Enum Verification

**Button** (`button.figma.tsx` vs `button.tsx` CVA config):
- Variants: `default`, `destructive`, `outline`, `secondary`, `ghost`, `link`, `terminal` -- 7/7 MATCH
- Sizes: `default`, `sm`, `lg`, `icon` -- 4/4 MATCH

**Badge** (`badge.figma.tsx` vs `badge.tsx` CVA config):
- Variants: `default`, `secondary`, `destructive`, `outline` -- 4/4 MATCH

### Import Resolution
- All 27 .figma.tsx files use relative imports (e.g., `./button`, `./message-bubble`)
- No `@/` alias imports in any .figma.tsx file
- All imports resolve correctly (verified via tsc)

### Prop Mapping Accuracy (non-event components)
- `app-shell.figma.tsx`: No props (correct -- AppShell takes none)
- `status-bar.figma.tsx`: No props (correct -- StatusBar takes none)
- `sidebar.figma.tsx`: All 5 required props provided, optional `onFocusSearchRef` correctly omitted
- `tab-bar.figma.tsx`: All 6 required props provided
- `message-stream.figma.tsx`: 4 required props provided, 8 optional props correctly omitted
- `input-bar.figma.tsx`: 2 required props provided, optional props selectively included
- `input.figma.tsx`: `figma.string('Placeholder')` and `figma.boolean('Disabled')` appropriate
- `tooltip.figma.tsx`: Correct compound component composition (TooltipProvider wrapping omitted, acceptable)
- `dialog.figma.tsx`: Correct compound component composition with trigger
- `alert-dialog.figma.tsx`: Correct usage with `open={true}` (matches PermissionModal pattern)
- `card.figma.tsx`: Correct compound component with `figma.string()` for title/description
- `popover.figma.tsx`: Correct compound component composition
- `scroll-area.figma.tsx`: Minimal correct example
- `separator.figma.tsx`: `figma.enum('Orientation')` correctly maps horizontal/vertical
- `skeleton.figma.tsx`: Minimal correct example with className
- `tabs.figma.tsx`: Correct compound component with TabsList/TabsTrigger/TabsContent

### Event Mock Accuracy (post-fix)
All event mocks now include:
- `id: string` (BaseStreamEvent) -- present in all mocks
- `thread_id: string` (BaseStreamEvent) -- present in all mocks
- `type: string` (correct discriminant value) -- present in all mocks
- `timestamp: string` (via `new Date().toISOString()`) -- present in all mocks
- All type-specific required fields (agent_id, agent_name, tool_call_id, artifact_id, complete, etc.) -- verified

---

## Verdict

**PASS.** All 12 original TypeScript errors are resolved. 8 of 9 required fixes from the initial audit have been correctly applied. The one remaining issue (M2: overly broad `include`) is cosmetic and does not affect correctness or functionality. The Code Connect mappings are type-safe, structurally sound, and ready for deployment.
