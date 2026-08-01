---
tags:
  - '#exec'
  - '#ui-integration-wire-regen'
date: 2026-04-04
modified: '2026-07-15'
body_hash: 'sha256:4d5af78828ddd4bfa47304775efe33474d20b0f993b9dcecd8a89d3bf400b0bb'
related:
  - "[[2026-04-04-ui-integration-wire-regen-plan]]"
---

# `ui-integration-wire-regen` phase-3 hydration-reconnection

Fixed critical data loss on reconnect/refresh by hydrating all snapshot fields.

- Modified: `src/ui/src/app/queries/use-thread-state.ts`
- Modified: `src/ui/src/app/queries/use-threads.ts`

## Description

**Snapshot hydration** (use-thread-state.ts): Added hydration for 6 previously dropped data sources:
- `pending_permissions` → mapped `_PermissionSnapshot[]` to `PermissionRequest[]` via inline mapper (injecting thread_id context, mapping option fields)
- `plan` entries → created `PlanUpdateEvent` stream event from `PlanEntry[]`
- `agents` → populated `_agentDisplayNames` cache via `updateAgentDisplayNames()`
- `ToolCallSnapshot.content` → mapped text→input/output, diff→diff+diff_path, terminal→terminal_id
- Agent name resolution → built local lookup from `snapshot.agents` for message and tool call events
- `snapshot.status` → updated TanStack Query thread list cache

**Optimistic insert** (use-threads.ts): Added missing fields to `useCreateThread` optimistic `ThreadSummary`: `status: 'submitted'`, `created_at`, `repair_status: null`, `execution_readiness: null`, `approval_status: null`, `approval_request_id: null`. Fixed `?? undefined` to `?? null` for nullable fields.

**ConnectedEvent bootstrap** (ws-bridge.ts): Added `setConnectedCallback` handler that logs `server_version` and `active_threads.length`. Progressive enhancement — no store field for version yet.

## Tests

`npm run check` remains at 0 errors. `npm run build` produces clean production bundle.
