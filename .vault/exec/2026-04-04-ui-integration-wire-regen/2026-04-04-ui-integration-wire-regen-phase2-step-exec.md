---
tags:
  - '#exec'
  - '#ui-integration-wire-regen'
date: 2026-04-04
modified: '2026-07-15'
related:
  - "[[2026-04-04-ui-integration-wire-regen-plan]]"
---

# `ui-integration-wire-regen` phase-2 api-client-mapper-alignment

Fixed all REST client, WebSocket client, mapper, bridge, and store slice type drift.

- Modified: `src/ui/src/app/api/websocket-client.ts`
- Modified: `src/ui/src/app/api/mappers.ts`
- Modified: `src/ui/src/app/store/slices/stream-slice.ts`
- Modified: `src/ui/src/app/store/slices/permission-slice.ts`
- Modified: `src/ui/src/app/bridge/ws-bridge.ts`

## Description

**REST client** (rest-client.ts): All 12 REST types resolve correctly from `components['schemas']` — no changes needed.

**WebSocket client** (websocket-client.ts): Changed WS type imports from `components['schemas']['...']` lookups to direct named imports from wire-types.ts. All 11 WS types now resolve correctly.

**Mappers** (mappers.ts): Imported `WsAgentSummary`, `PermissionRequestEvent`, `WsPermissionOption` directly. Added `repair_status`, `execution_readiness`, `approval_status`, `approval_request_id` to `mapThreadSummary()`. Fixed 5 `undefined → null` coalescing issues. Added type annotation to permission options `.map()` callback.

**Stream slice** (stream-slice.ts): Imported `ServerEvent` and `WsToolCallContent` directly. Added `WsToolCallContent` type annotations to 4 `.find()` callbacks. Fixed `plan_update` `.map()` callback types.

**Permission slice** (permission-slice.ts): Imported `PermissionRequestEvent` directly.

**Bridge** (ws-bridge.ts): Fixed status conflation bug — terminal agent states now set `status: 'completed'` instead of conflating with `agent_state` value.

## Tests

`npm run check` reduced from 27 errors to 0 after Phase 2.
