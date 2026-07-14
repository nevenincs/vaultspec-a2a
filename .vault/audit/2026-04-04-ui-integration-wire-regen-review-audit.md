---
tags:
  - '#audit'
  - '#ui-integration-wire-regen'
date: 2026-04-04
modified: '2026-04-04'
related:
  - "[[2026-04-04-ui-integration-wire-regen-plan]]"
  - "[[2026-04-04-ui-integration-wire-regen-summary-exec]]"
---

# `ui-integration-wire-regen` Code Review

## Status: PASS

Three parallel review agents audited type safety, hydration logic, SSE client,
and component correctness. Two HIGH and four MEDIUM issues found; all resolved
in a revision pass.

## Findings

BRIDGE-001 | HIGH | **FIXED** Terminal agent states blindly set `status: 'completed'`
The ws-bridge agent_status handler set `thread.status` to `'completed'` for all
terminal agent states (completed, failed, cancelled). A failed agent would
incorrectly mark the thread as completed in the sidebar. Fix: removed the
`status` overwrite entirely — thread status is now only set from REST responses.

TYPE-001 | HIGH | **ACCEPTED** `PlanEntry.id` field not in backend schema
The frontend `PlanEntry.id` is a synthetic field populated by the hydration
mapper (`plan-entry-${i}`). It does not exist in the backend `PlanEntry`
Pydantic model. This is by design — the backend sends content/status/priority;
the frontend generates index-based IDs for React list keying.

STREAM-002 | MEDIUM | **FIXED** `tool_call_start` never populated `terminal_id` or `diff_path`
Added extraction of terminal content type and diff path to the tool_call_start
handler in stream-slice.ts.

STREAM-003 | MEDIUM | **FIXED** `tool_call_update` dropped terminal, diff_path, locations
Added terminal content, diff_path, and locations update handling to the
tool_call_update handler.

STREAM-004 | MEDIUM | **FIXED** error handler dropped `event.recoverable`
Added `recoverable: event.recoverable` to the error stream event.

SSE-010 | MEDIUM | **FIXED** `thread_terminal` cast to `ServerEvent` was unsound
Changed thread_terminal handler to parse as `ThreadTerminalEvent` and log
instead of dispatching through the `ServerEvent` pipeline.

BRIDGE-003 | MEDIUM | SSE event callback not wired when `USE_SSE=true`
The SSE connection callback is wired but event callback is not. Since
`USE_SSE=false` by default and SSE is documented as opt-in, this is acceptable
for #28. Noted for future activation.

WIRE-001 | MEDIUM | `PermissionResponseCommand` omitted from `ClientMessage` union
The frontend intentionally routes permission responses through REST, not WS.
The backend rejects permission_response over WS. Omission is defensible.

MAP-006 | MEDIUM | `mapToolCallStatus` cast has no fallback for unknown values
Unlike `mapToolKind` which validates against a set, `mapToolCallStatus` does a
direct cast. ToolCallStatus is stable (4 values). Accepted as-is.

BRIDGE-005 | LOW | Initial WS connect reports as 'reconnecting'
The 3-value frontend `ConnectionState` has no `'connecting'` — initial connect
maps to `'reconnecting'`. Functionally harmless.

STATE-002 | LOW | No compile-time exhaustive guard on `agentState*` switches
The switch functions cover all 8 values but lack a `const _: never` guard.
`noFallthroughCasesInSwitch` in tsconfig catches fall-through but not missing
members. Acceptable for stable enum.
