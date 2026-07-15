---
tags:
  - '#exec'
  - '#ui-integration-wire-regen'
date: 2026-04-04
modified: '2026-07-15'
related:
  - "[[2026-04-04-ui-integration-wire-regen-plan]]"
---

# `ui-integration-wire-regen` phase-1 type-foundation

Installed openapi-typescript, started the gateway, generated wire types from the live OpenAPI spec, and created the frontend presentation type module.

- Created: `src/ui/src/app/data/wire-types.ts` (generated from OpenAPI + hand-authored WS protocol types)
- Created: `src/ui/src/app/data/types.ts` (frontend presentation types)
- Modified: `src/ui/package.json` (added openapi-typescript devDependency)

## Description

The OpenAPI spec at `/openapi.json` contains 37 REST schemas but no WebSocket protocol types (WS is not a REST endpoint). Generated the REST types via `openapi-typescript`, then hand-authored all 12 server event types, 5 client command types, and supporting types (ToolCallContent union, PermissionOption, AgentSummary) from the Pydantic models in the backend schemas package.

The `types.ts` file defines the full frontend type surface: `AgentLifecycleState` (8 values), `ToolKind` (10 values), `ToolCallStatus` (4 values), `ConnectionState`, `ThemeMode`, `ThreadSummary` (including 4 new PR #22 fields), `AgentSummary`, `TeamPreset`, `PermissionRequest`, `EditorTab`, `ContextDocument`, `InspectorTarget`, and the `StreamEvent` discriminated union (8 variants with new `diff_path`, `terminal_id`, `recoverable` fields).

## Tests

`npm run check` reduced from 80+ errors to 27 after Phase 1 (all remaining were WS import path and nullability issues resolved in Phase 2).
