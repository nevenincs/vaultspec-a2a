---
tags:
  - '#exec'
  - '#ui-integration-wire-regen'
date: 2026-04-04
modified: '2026-04-04'
related:
  - "[[2026-04-04-ui-integration-wire-regen-plan]]"
  - "[[2026-04-04-ui-integration-wire-regen-research]]"
---

# `ui-integration-wire-regen` execution summary

Issue #28 / PR #29: Regenerated wire types from the restructured backend and fixed every identified frontend drift point.

- Created: `src/ui/src/app/data/wire-types.ts`, `src/ui/src/app/data/types.ts`, `src/ui/src/app/api/sse-client.ts`
- Modified: `mappers.ts`, `websocket-client.ts`, `ws-bridge.ts`, `message-stream.tsx`, `use-thread-state.ts`, `use-threads.ts`, `permission-slice.ts`, `stream-slice.ts`, `.gitignore`, `package.json`

## Description

Four phases executed across 6 parallel sub-agents:

**Phase 1** — Generated wire-types.ts from live OpenAPI (37 REST schemas) + hand-authored 12 WS event types and 5 client command types. Created types.ts with full frontend type surface including 4 new PR #22 fields.

**Phase 2** — Fixed all import paths (WS types direct, REST via components), added `repair_status`/`execution_readiness`/`approval_status`/`approval_request_id` to ThreadSummary mapper, fixed status conflation bug in ws-bridge, resolved all implicit any errors.

**Phase 3** — Fixed reconnection data loss: hydrated `pending_permissions`, `plan` entries, `agents` (display names), `ToolCallSnapshot.content` (text/diff/terminal), `snapshot.status`. Fixed optimistic insert completeness.

**Phase 4** — Created SSE client (145 LOC, EventSource wrapper), removed `as any` casts in message-stream.tsx, verified state-indicators exhaustiveness, fixed .gitignore `data/` exception.

## Drift registry resolution

All 5 BLOCKING, 7 HIGH, and 6 addressable MEDIUM drift items resolved. 4 MEDIUM and 10 LOW items documented as out of scope (feature work, monitoring, idempotency).

## Tests

- `npm run check`: 0 TypeScript errors (down from 80+)
- `npm run build`: Clean production bundle
- Gateway serves correct OpenAPI spec with all 37 schemas
- Full-stack smoke test pending (requires gateway + worker)
