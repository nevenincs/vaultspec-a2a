---
date: 2026-02-28
type: research
feature: react-state-management
description: "Research into React state management patterns for the frontend pivot."
---

# React State Management & Data Fetching Library Research

**Date:** 2026-02-28
**Context:** VaultSpec A2A Control Surface — React 18 SPA with FastAPI backend
**Decision:** TanStack Query v5 + Zustand v5 (adopted in ADR-018 amendment)

## 1. Problem Statement

The React frontend connects to a FastAPI backend via:

- **8 REST endpoints** (CRUD threads, team status, permission responses)
- **1 WebSocket connection** (real-time streaming: message chunks, thought
  chunks, tool call updates, agent status, permission requests)

Key requirements:

- Chunk accumulation (message_chunk events must be appended into complete
  messages)
- Sequence-based gap detection (reconnection replays from snapshots)
- Permission responses MUST go via REST (WS is rejected by server)
- VS Code-style tab system where each tab subscribes to a thread's event
  stream

The initial implementation used a monolithic `use-app-state.ts`hook (530
lines) with raw`useState`calls, mock data imports, and a`useRef<Map>`
chunk accumulation index. This needs to be decomposed into a proper state
management architecture.

## 2. Libraries Evaluated

### 2.1 TanStack Query (React Query) v5 — ADOPTED

- **Purpose:** Server-state management (REST data fetching)
- **Bundle:** ~16.2 KB gzipped
- **npm:** 12.3M weekly downloads, 48K GitHub stars
- **React 18:** Requires React 18+ (uses `useSyncExternalStore`)
- **Version evaluated:** 5.90.21

### Strengths for our use case

- Automatic caching, request deduplication, background refetching
- `useQuery`for reads,`useMutation`for writes with optimistic updates
- Experimental`streamedQuery`API with custom reducers for chunk
  accumulation
- Queries auto-GC when components unmount
- DevTools extension for debugging cache state
- Can be integrated with WebSocket via`queryClient.setQueryData()`
  (push WS data into cache) or `queryClient.invalidateQueries()`
  (trigger refetch after WS event)

### Limitations

- Does NOT handle WebSocket connection lifecycle
- No WS subscribe/unsubscribe protocol support
- No ping/heartbeat timer management
- `streamedQuery`is experimental (may change)

**What it replaces:** Thread list fetching, team status/presets fetching,
thread state snapshot hydration, create thread / permission response
mutations.

### 2.2 Zustand v5 — ADOPTED

- **Purpose:** Client + real-time state management
- **Bundle:** ~1 KB gzipped
- **npm:** 19.1M weekly downloads, 57K GitHub stars
- **React 18:** Requires React 18+ (uses`useSyncExternalStore`)
- **Version evaluated:** 5.0.11

### Strengths for our use case: (2)

- **Vanilla store API** (`createStore`from`zustand/vanilla`) works
  outside React — critical for WebSocket event handlers that dispatch
  high-frequency chunk events without needing React context
- **Selective subscriptions** prevent render storms: updating one
  thread's stream events does NOT re-render components displaying other
  threads
- **Immer middleware** enables readable mutable-style chunk accumulation
- **Persist middleware** for theme/sidebar preferences across sessions
- **DevTools middleware** integrates with Redux DevTools
- No Provider wrapper needed, zero boilerplate
- Most popular state management library in React (surpassed Redux in new
  projects)

### Limitations: (2)

- No server-state features (caching, refetching, dedup) — must pair with
  TanStack Query

**What it replaces:** The entire `use-app-state.ts`monolithic hook,
decomposed into focused stores (stream-store, tab-store, ui-store,
permission-store).

### 2.3 RTK Query (Redux Toolkit Query) — REJECTED

- **Purpose:** Data fetching layer built into Redux Toolkit
- **Bundle:** ~41 KB gzipped (full Redux Toolkit)
- **npm:** 10.5M weekly downloads

### Why rejected

- Requires buying into the entire Redux ecosystem (actions, reducers,
  store, middleware)
- Heaviest bundle option by far
- Its streaming model assumes per-query WebSocket connections via
 `onCacheEntryAdded`, but our architecture uses a single global
  WebSocket with per-thread subscriptions — fundamental mismatch
- Redux is declining in new React projects
- Boilerplate: `createApi`, `configureStore`, `Provider`, `setupListeners`

### 2.4 SWR (by Vercel) — REJECTED

- **Purpose:** Lightweight stale-while-revalidate data fetching
- **Bundle:** ~5.3 KB gzipped
- **npm:** 5.8M weekly downloads, 32K GitHub stars

### Why rejected: (2)

- Strictly less capable than TanStack Query: no mutations API, no
  infinite query, no devtools, fewer cache control options
- No WebSocket or streaming support whatsoever
- Optimized for Next.js ecosystem, not pure SPA
- Weaker optimistic update story
- Less active development than TanStack Query

### 2.5 react-use-websocket — REJECTED

- **Purpose:** React hooks for WebSocket communication
- **Bundle:** ~5-8 KB gzipped
- **npm:** 300K weekly downloads, 1.1K GitHub stars

### Why rejected: (3)

- Our custom `WebSocketClient`(243 lines) already handles everything
  this library does: reconnection with exponential backoff, heartbeat
  timeout, and ping keepalive
- Our protocol is complex (subscribe/unsubscribe commands, sequence
  tracking, gap detection) — the library only handles transport, not
  protocol. We'd have to rewrite our protocol logic on top of their
  hook API
- Single maintainer (bus factor risk)
- No advantage over existing custom implementation

### 2.6 Socket.IO Client — REJECTED

- **Purpose:** Full-featured real-time bidirectional communication
- **Bundle:** ~10.4 KB gzipped

### Why rejected: (4)

- **Requires Socket.IO server** — our FastAPI backend uses native
  WebSocket (Starlette), NOT Socket.IO. Adopting Socket.IO client
  would require rewriting the server. Non-starter.
- Custom protocol overhead (metadata per message, framing)
- Long-polling fallback is irrelevant for a local developer tool

### 2.7 Jotai — REJECTED

- **Purpose:** Atomic state management for React
- **Bundle:** ~2-4 KB gzipped
- **npm:** 2.5M weekly downloads, 21K GitHub stars

### Why rejected: (5)

- Atomic model is a poor fit for our data: stream events per thread are
  inherently arrays, not individual atoms. Atomizing each event would
  be extreme overhead
- No vanilla store API — harder to integrate with non-React WebSocket
  event handlers
- Smaller ecosystem than Zustand (2.5M vs 19M weekly downloads)

## 3. Recommended Architecture

### TanStack Query + Zustand + Existing WebSocketClient

**Total new bundle cost:** ~17.2 KB gzipped

| Concern | Owner | Previous Location |
| --------- | ------- | ------------------ |
| REST fetching (threads, team, presets, snapshots) | TanStack Query | `rest-client.ts`+`use-app-state.ts` |
| REST mutations (create thread, permission response) | TanStack Query | `use-app-state.ts` |
| WebSocket transport (connect, reconnect, ping, heartbeat) | Existing`WebSocketClient` | `websocket-client.ts` |
| Real-time stream events (chunk accumulation, tool calls) | Zustand store | `use-app-state.ts` |
| Tab system (open, close, pin, activate) | Zustand store | `use-app-state.ts` |
| UI state (theme, sidebar, inspector) | Zustand store (persist) | `use-app-state.ts` |
| Permission queue | Zustand store | `use-app-state.ts` |

**Key integration point:**`WebSocketClient`'s event callback calls
`zustandStore.getState().handleWireEvent(threadId, event)`— Zustand's
vanilla API works without React context.

### Decomposition of use-app-state.ts

| New file | Concern | Library |
| ---------- | --------- | --------- |
| `stores/stream-store.ts` | Per-thread stream events + chunk accumulation | Zustand + Immer |
| `stores/tab-store.ts` | Tab open/close/pin/activate + WS subscribe | Zustand |
| `stores/ui-store.ts` | Theme, sidebar, inspector | Zustand + persist |
| `stores/permission-store.ts` | Permission queue (WS pushes, REST removes) | Zustand |
| `hooks/use-threads.ts` | Thread list, create, snapshot | TanStack Query |
| `hooks/use-team.ts` | Team status, presets | TanStack Query |

### What stays unchanged

-`websocket-client.ts`— well-structured, protocol-aware
-`rest-client.ts`— becomes the fetcher passed to TanStack Query
-`wire-types.ts`— backend schema mirrors
-`types.ts`— frontend domain types
-`mappers.ts`— wire-to-frontend translation

## 4. Production Precedent

| App Type | Typical Stack |
| ---------- | -------------- |
| AI coding assistants (Cursor, Windsurf) | Custom WS + custom state |
| Chat applications | TanStack Query (REST) + Zustand (messages/WS) |
| Real-time dashboards | TanStack Query + Zustand + native WebSocket |
| IDE-like web tools | Zustand for UI state + custom WS client |

The consistent pattern across production real-time React apps in 2025-2026
is: TanStack Query for REST, Zustand for client + real-time state, custom
WebSocket client for protocol-specific needs.

## 5. MCP Server Ecosystem for New Stack

Research identified available MCP servers for each frontend library:

| Library | Best MCP Server | Package | Actively Maintained | Recommendation |
| --------- | ---------------- | --------- | ------- | ---------------- |
| TanStack Query | TanStack CLI | `@tanstack/cli` | Yes (first-party) | Add to`.mcp.json` |
| Zustand | context7 / GitMCP | `gitmcp.io/pmndrs/zustand` | N/A | Use existing context7 |
| React 18 | context7 / GitMCP | `gitmcp.io/facebook/react` | N/A | Use existing context7 |
| Tailwind CSS v4 | @clarity-contrib server | `@clarity-contrib/tailwindcss-mcp-server` | Yes | Add to`.mcp.json` |
| Radix UI | @gianpieropuleo server | `@gianpieropuleo/radix-mcp-server` | Moderate | Add to`.mcp.json` |
| shadcn/ui (React) | Official shadcn CLI | `shadcn@latest mcp` | Yes (first-party) | **Replace current** |
| Vite | context7 | N/A | N/A | Use existing context7 |
| Lucide React | lucide-icons-mcp | `lucide-icons-mcp` | Yes | Add to`.mcp.json` |

### High-priority actions

1. Replace current`shadcn-ui-mcp-server`with official`shadcn@latest mcp`
2. Add `@tanstack/cli`for TanStack Query documentation
3. Add`@clarity-contrib/tailwindcss-mcp-server`for Tailwind v4 utilities
4. Add`@gianpieropuleo/radix-mcp-server`for Radix component docs
5. Add`lucide-icons-mcp` for icon lookup

## 6. References

- [TanStack Query Docs](https://tanstack.com/query/v5/docs)
- [Zustand Docs](https://zustand.docs.pmnd.rs/)
- [TanStack Query + WebSockets
  (tkdodo)](https://tkdodo.eu/blog/using-web-sockets-with-react-query)
- [Zustand + TanStack Query
Pattern](https://javascript.plainenglish.io/zustand-and-tanstack-query-the-dynamic-duo-that-simplified-my-react-state-management-e71b924efb90)
- [React State Management 2026
Comparison](https://dev.to/jsgurujobs/state-management-in-2026-zustand-vs-jotai-vs-redux-toolkit-vs-signals-2gge)
- [MCP Server Registry](https://registry.modelcontextprotocol.io/)
- [RTK Query Streaming
  Updates](https://redux-toolkit.js.org/rtk-query/usage/streaming-updates)
- [Socket.IO vs WebSocket](https://ably.com/topic/socketio-vs-websocket)
