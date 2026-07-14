---
tags:
  - '#audit'
  - '#ui-integration-wire-regen'
date: 2026-04-04
modified: '2026-04-04'
related:
  - "[[2026-04-04-ui-integration-wire-regen-plan]]"
  - "[[2026-04-04-ui-integration-wire-regen-review-audit]]"
---

# `ui-integration-wire-regen` Rolling Audit

Continuous discovery of drifts, wiring gaps, and regression risks across the
frontend codebase. Findings appended by parallel sub-agents.

## Round 1 — 4 parallel agents (2026-04-04)

### Actionable — PR #28 scope

BRIDGE-001 | HIGH | WS event callback always wired — double dispatch when USE_SSE=true
`ws-bridge.ts:66`: wsClient.setEventCallback is set unconditionally. When
USE_SSE=true, both WS and SSE dispatch the same events, doubling every store
update. The WS event callback should be gated behind `!USE_SSE`.

QUERY-004 | HIGH | SSE bridge agent_status missing TQ cache updates
`ws-bridge.ts:146-159`: SSE callback only calls handleWireEvent for
agent_status. WS path additionally updates TQ `team.status()` and
`threads.list()` caches. Agent panel and thread list go stale under SSE mode.

QUERY-005 | HIGH | SSE bridge silently drops team_status events
`ws-bridge.ts:161`: bare `break` on team_status. WS path replaces TQ agent
cache and populates display name map. Team panel never updates under SSE.

SSE-004 | MEDIUM | SSE client has no sequence dedup
`sse-client.ts`: no lastSequences tracking. EventSource auto-reconnect may
replay events, causing duplicate store entries. WS client has this protection.

RACE-001 | MEDIUM | WS + SSE race on single connectionState atom
Both transports write to `appStore.setConnectionState()`. When USE_SSE=true,
WS reconnect cycle overwrites SSE state causing UI flicker.

PERM-001 | MEDIUM | WS permission events show UUID as agent_name
`mappers.ts:80`: `agent_name: wire.agent_id ?? 'Unknown'`. The WS bridge
does not resolve agent_id against `_agentDisplayNames` before pushing to
store. Snapshot path resolves correctly (inconsistency).

PROXY-001 | MEDIUM | Vite dev proxy rules target wrong path prefix
`vite.config.ts`: proxy rules are `/threads`, `/team`, `/teams`,
`/permissions` but backend routes are `/api/threads`, `/api/team`, etc.
Dead config — clients use absolute URLs — but misleading.

DOCKER-DEV-002 | MEDIUM | VITE_API_BASE_URL not set in Docker dev compose
`docker-compose.dev.yml`: only sets VITE_API_URL (build-time proxy target).
Runtime clients read VITE_API_BASE_URL which falls back to localhost:8000,
unreachable from browser in containerized dev mode.

QUERY-003 | LOW | useCreateThread does not invalidate thread list after mutation
No onSettled invalidation. Stale optimistic entry persists until 30s staleTime
expires. WS agent_status events will eventually update, but not immediate.

QUERY-006 | LOW | useSendMessage bypasses slice pattern with direct setState
`use-send-message.ts:31`: only hook that calls appStore.setState directly
instead of using a named action. Fragile if middleware stack changes.

QUERY-011 | LOW | REST client captures error body as text, not parsed JSON
`rest-client.ts:113-114`: error responses read with `res.text()`, losing
structured HTTPValidationError detail. Limits error reporting.

QUERY-015 | LOW | useThreadMetadataQuery returns raw wire type, no mapper
Breaks the architectural pattern (all other queries map wire→frontend types).
No frontend ThreadMetadata type exists in types.ts.

ENV-001 | LOW | VITE_API_URL vs VITE_API_BASE_URL naming confusion
Two vars for related but different purposes (build-time proxy vs runtime
browser-side URL). Poorly documented distinction.

### Informational — no action needed

PERM-003 | INFO | Hydrated permissions always show tool_kind 'other'
`_PermissionSnapshot` lacks tool_kind. WS path maps correctly. Cosmetic.

TOOL-002 | INFO | ToolCallCard does not render diff_path or terminal_id
Fields flow to inspector via JSON.stringify on click. No data loss.

SSE-005 | INFO | SSE heartbeat listener is no-op
No lastHeartbeat update from SSE connections. Minor monitoring gap.

QUERY-008 | INFO | useThreadStateQuery staleTime Infinity edge case
If Zustand events cleared and re-fetched, TQ serves stale cached snapshot
status. Minor since hydration works correctly.

RACE-002 | INFO | Sequence gap after WS reconnect — events during disconnect lost
Known ADR-004 limitation. No gap-fill mechanism exists.

## Round 2 — 2 parallel agents (2026-04-04)

All Round 1 HIGH/MEDIUM confirmed fixed. New findings:

THEME-001 | MEDIUM | **FIXED** No theme hydration on startup — FOUC
`app-store.ts`: persist middleware had no `onRehydrateStorage` callback.
Persisted dark/light preference was not applied to document root until
user toggled theme. Fix: added `onRehydrateStorage` that applies the
persisted `themeMode` to `document.documentElement` immediately.

BARREL-001 | LOW | Dead barrel files in queries/ and store/
`queries/index.ts` and `store/index.ts` re-export everything but are
never imported — all consumers use direct file imports. Dead code.

BRIDGE-002 | LOW | WS/SSE dispatch logic duplicated (~45 lines)
Near-identical switch/case blocks in WS and SSE paths. Refactor to
shared helper would prevent future drift. Not a bug.

SSE-003 | LOW | Sequence dedup would drop first event if 0-based
`lastSequence` init to 0 + guard `seq <= lastSequence` means seq=0
is dropped. Backend uses 1-based sequences so this is a non-issue.

THEME-002 | INFO | palette.ts hue labels drift from theme.css
Cosmetic naming inconsistency. palette.ts values are dead documentation.

DEAD-001 | INFO | palette.ts exports PALETTES/PaletteId/ACTIVE_PALETTE — unused
Forward-looking infrastructure for palette switching.

PKG-001 | INFO | No generate-types script in package.json
openapi-typescript regen command only documented in wire-types.ts header.

## Round 3 — deep edge cases (2026-04-04)

PERM-DEDUP | MEDIUM | **FIXED** pushPermission allows duplicate request_id
`permission-slice.ts`: no dedup guard. Server re-delivery after reconnect
creates duplicate permission cards. Fix: added `.some()` check on
`request_id` before pushing.

CHUNK-BOUNDS | MEDIUM | **FIXED** Stale chunk index after hydration
`stream-slice.ts`: handleWireEvent reads `_chunkIndex` outside the draft,
then mutates at `existing.idx` inside the draft. If the array was replaced
by hydration between read and write, `idx` could be out of bounds. Fix:
added `existing.idx >= arr.length` bounds check inside the draft for
message_chunk, thought_chunk, and tool_call_update.

WS-GAP | MEDIUM | Events during reconnect window permanently lost
`websocket-client.ts`: after reconnect, re-subscribe does not include
last known sequence numbers. Server cannot replay missed events. For
already-populated threads, `useThreadStateQuery` won't re-fire (guarded
by `hasEvents`). **Out of scope** — requires protocol-level gap recovery.

WS-CONTROL-DROP | MEDIUM | sendAgentControl silently drops during reconnect
`websocket-client.ts:send()`: silent no-op when socket not OPEN. UI uses
REST for messages (safe), but agent control commands via WS would be lost
during reconnect. **Out of scope** — needs command acknowledgement design.

MEMORY-UNBOUNDED | MEDIUM | streamEvents grow unboundedly per open tab
No upper bound or pruning for `streamEvents[threadId]` or `_chunkIndex`.
Long-running agent threads with heavy tool-call activity accumulate
indefinitely. Cleanup only on tab close. **Out of scope** — needs pruning
strategy decision (LRU, cap, archive).

### Out of scope — backend or future work

BACKEND-PERM-001 | MEDIUM | `get_pending_permission_requests` lacks order_by
Control layer uses `[-1]` for most recent request. Non-deterministic without
explicit ordering. (Forwarded to PR #22 team.)
