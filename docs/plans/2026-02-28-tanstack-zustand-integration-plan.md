---
date: 2026-02-28
type: plan
feature: tanstack-zustand
description: 'Implementation plan for replacing the monolithic useAppState hook with TanStack Query v5 (server state) and Zustand v5 (client/real-time state) to eliminate prop drilling and enable selective re-renders.'
related_adrs:
  - docs/adrs/2026-02-28-018-react-tailwind-figma-migration-adr.md
  - docs/adrs/2026-02-26-011-frontend-backend-contract-adr.md
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
related_research:
  - docs/research/2026-02-28-react-state-management-research.md
  - docs/research/2026-02-25-control-surface-distilled-research.md
---

## Plan: TanStack Query v5 + Zustand v5 Integration

## Context

The React frontend (`src/ui/src/app/`) has a monolithic 530-line
`useAppState()`hook
that manages ALL application state with raw`useState`/`useCallback`/`useEffect`.
ADR-018 §2.2 mandates decomposing this into TanStack Query (server state) +
Zustand
(client/real-time state). Neither library is installed yet.

The current hook prop-drills ~40 properties from `App → AppShell → children`,
causes
full-tree re-renders on any state change, has no
caching/dedup/background-refresh for
REST, and forces the WS event handler to run inside React's render cycle.

**Goal:** Replace `useAppState()` with a clean TanStack Query + Zustand
architecture
that separates server state (REST-cacheable) from client state (WS-driven,
UI-local),
eliminates prop drilling, and enables selective re-renders.

---

## Architecture Decisions

| Decision                    | Choice                                                                  | Why                                                                                |
| --------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Zustand store type          | Single **vanilla** store (`createStore`from`zustand/vanilla`)           | WS callback runs outside React and needs `store.getState()`directly                |
| Store composition           | 5 slices merged into one store                                          | Atomic WS dispatch across stream + permission + connection state                   |
| Middleware stack            | `devtools > persist > immer`(outermost → innermost)                     | Immer for chunk accumulation mutations; persist for UI prefs only                  |
| Persist scope               | `themeMode`, `sidebarCollapsed`, `sidebarWidth`only                     | Tabs/stream/inspector are session-transient                                        |
| queryClient location        | Module-level singleton (not inside Zustand)                             | WS bridge needs direct`setQueryData`; React `QueryClientProvider`is a thin wrapper |
| WS → TQ cache updates       | `setQueryData`(not`invalidateQueries`) for `team_status`/`agent_status` | WS event has complete data — no need to refetch                                    |
| Component state consumption | Direct`useStore(appStore, selector)`+ TQ hooks                          | Eliminates prop drilling;`useShallow`prevents render storms                        |
| Chunk index                 | `_chunkIndex: Map` inside stream slice                                  | Immer passes Maps unproxied; O(1) lookup preserved                                 |

---

## New Dependencies

```python
@tanstack/react-query ^5.64.0
@tanstack/react-query-devtools ^5.64.0
zustand ^5.0.3
immer ^10.1.1
```text

---

## File Plan

### New files (14)

```text
src/ui/src/app/
  store/
    index.ts                     -- barrel re-exports
    app-store.ts                 -- vanilla Zustand store, 5 slices composed
    slices/
      stream-slice.ts            -- streamEvents, _chunkIndex, handleWireEvent, hydrateThreadEvents
      connection-slice.ts        -- connectionState, lastHeartbeat
      permission-slice.ts        -- permissionQueue, pushPermission, removePermission
      tab-slice.ts               -- tabs, activeTabId, open/close/pin logic
      ui-slice.ts                -- sidebar, inspector, theme (persisted subset)
  queries/
    index.ts                     -- barrel re-exports
    query-client.ts              -- QueryClient singleton
    query-keys.ts                -- typed cache key factory
    use-threads.ts               -- useThreadsQuery, useCreateThread mutation
    use-thread-state.ts          -- useThreadStateQuery (snapshot hydration)
    use-team.ts                  -- useTeamStatusQuery, useTeamPresetsQuery
    use-permissions.ts           -- useRespondToPermission mutation
  bridge/
    ws-bridge.ts                 -- initWsBridge(): WS callbacks → Zustand + TQ invalidation
```text

### Modified files (10)

```text
src/ui/package.json                              -- add 4 deps
src/ui/src/main.tsx                              -- no change (App is entry)
src/ui/src/app/App.tsx                           -- wrap in QueryClientProvider + devtools
src/ui/src/app/components/layout/app-shell.tsx   -- replace useAppState() with store/queries
src/ui/src/app/components/layout/sidebar.tsx     -- direct store/query consumption
src/ui/src/app/components/layout/tab-bar.tsx     -- direct store consumption
src/ui/src/app/components/layout/status-bar.tsx  -- direct store consumption
src/ui/src/app/components/stream/input-bar.tsx   -- TQ hooks for presets, mutation for create
src/ui/src/app/components/permission/permission-modal.tsx -- store + mutation
src/ui/src/app/components/stream/message-stream.tsx      -- receives events as prop (unchanged API)
```text

### Deleted files (2)

```text
src/ui/src/app/hooks/use-app-state.ts            -- replaced entirely
src/ui/src/app/data/mock-data.ts                 -- demoPermissionRequest no longer needed
```text

---

## Zustand Store Shape

```text
AppStore = StreamSlice & ConnectionSlice & PermissionSlice & TabSlice & UiSlice
```typescript

### StreamSlice

- `streamEvents: Record<string, StreamEvent[]>`— per-thread event arrays -`_chunkIndex: Map<string, { threadId: string; idx: number }>`— O(1) chunk
  lookup -`handleWireEvent(threadId, event)`— full WS event switch (message_chunk,
  thought_chunk, tool_call_start/update, artifact_update, plan_update,
  agent_status stream, error) -`hydrateThreadEvents(threadId, events, lastSequence)`— snapshot → store +
  rebuild index -`clearThreadEvents(threadId)`— cleanup on tab close

### ConnectionSlice

-`connectionState: ConnectionState`

- `lastHeartbeat: number`
- `setConnectionState(state)`, `setLastHeartbeat(ts)`

### PermissionSlice

- `permissionQueue: PermissionRequest[]`
- `pushPermission(wireEvent)`— maps + appends -`removePermission(requestId)`— optimistic removal on respond

### TabSlice

| -`tabs: EditorTab[]`, `activeTabId: string | null` | -`openTransient(threadId)`, `openPinned(threadId)`, `pinTab(threadId)`,
`closeTab(threadId)`, `activateTab(threadId)`, `clearActiveTab()`

- `closeTab`also calls`wsClient.unsubscribe()`

### UiSlice

- `themeMode: ThemeMode`(persisted),`sidebarCollapsed:
  boolean`(persisted),`sidebarWidth: number`(persisted)
  | -`inspectorTarget: InspectorTarget | null`, `contextDocuments:
ContextDocument[]` | -`setThemeMode(mode)`— also applies to`document.documentElement.classList`
- `toggleSidebar()`, `setSidebarWidth(w)`, `openInspector(target)`,
  `closeInspector()`, `openDocument(doc)`, `toggleContextPanel(docs)`

---

## TanStack Query Hooks

### Cache Key Factory (`query-keys.ts`)

```text
threads.list()        → ['threads', 'list']
threads.state(id)     → ['threads', id, 'state']
threads.metadata(id)  → ['threads', id, 'metadata']
team.status()         → ['team', 'status']
team.presets()        → ['team', 'presets']
```text

### Queries

| Hook                      | Endpoint                      | staleTime | Notes                                                       |
| ------------------------- | ----------------------------- | --------- | ----------------------------------------------------------- |
| `useThreadsQuery`         | `GET /api/threads`            | 30s       | Maps via`mapThreadSummary`                                  |
| `useThreadStateQuery(id)` | `GET /api/threads/{id}/state` | Infinity  | Enabled only when tab has no events; hydrates Zustand store |
| `useTeamStatusQuery`      | `GET /api/team/status`        | 10s       | WS`setQueryData`supplements                                 |
| `useTeamPresetsQuery`     | `GET /api/teams`              | 5min      | Near-static data                                            |

### Mutations

| Hook                     | Endpoint                             | Side Effects                                                                            |
| ------------------------ | ------------------------------------ | --------------------------------------------------------------------------------------- |
| `useCreateThread`        | `POST /api/threads`                  | Optimistic prepend to thread list cache;`appStore.openPinned()`; `wsClient.subscribe()` |
| `useRespondToPermission` | `POST /api/permissions/{id}/respond` | Optimistic`removePermission()` from Zustand queue                                       |

---

## WS Bridge (`ws-bridge.ts`)

`initWsBridge()`— called once from`AppShell useEffect`. Sets up 3 WS callbacks:

1. **Connection callback** → `appStore.getState().setConnectionState()`
2. **Heartbeat callback** → `appStore.getState().setLastHeartbeat()`
3. **Event callback** → switch on `event.type`:
   | - `message_chunk | thought_chunk | tool_call_start | tool_call_update |
artifact_update | plan_update | error`→`appStore.getState().handleWireEvent()` | -`agent_status`→ **dual dispatch**:`handleWireEvent()`(stream) +`queryClient.setQueryData(team.status(), ...)`(update agent in TQ cache) -`team_status`→`queryClient.setQueryData(team.status(), mapped agents)`(full
   replacement, no stream event) -`permission_request`→`appStore.getState().pushPermission(event)`
   - Sequence tracking: `wsClient.updateLastSequence()`for all events
     with`sequence`

Returns cleanup function (calls `wsClient.disconnect()`).

---

## Tab Activation → Snapshot Hydration Flow

1. User clicks thread → `tabSlice.openTransient(threadId)`→ sets`activeTabId`
2. `AppShell`watches`activeTabId`via`useEffect`→
   calls`wsClient.subscribe([activeTabId])`
3. `useThreadStateQuery(activeTabId)`fires (enabled when`streamEvents[id]`is
   empty)
4. Query fetches`GET /api/threads/{id}/state`, builds `StreamEvent[]`, calls
   `appStore.hydrateThreadEvents()`
5. `wsClient.updateLastSequence()`set from snapshot — WS fills the gap going
   forward
6. Components re-render via`useStore(appStore, s =>
s.streamEvents[activeTabId])`

---

## Component Migration Pattern

**Before** (prop drilling):

```tsx
// AppShell
const state = useAppState();
<Sidebar state={state} />
<StatusBar state={state} />
```text

**After** (direct consumption):

```tsx
// Sidebar.tsx
import { useStore } from 'zustand';
import { useShallow } from 'zustand/react/shallow';
import { appStore } from '../../store';
import { useThreadsQuery } from '../../queries';

export function Sidebar() {
  const { data: threads = [] } = useThreadsQuery();
  const { activeTabId, openTransient, themeMode, setThemeMode, ... } = useStore(
    appStore, useShallow(s => ({ ... }))
  );
```text

Components that need only 1 property skip `useShallow`:

```tsx
const connectionState = useStore(appStore, (s) => s.connectionState);
```text

---

## Implementation Phases

### Phase 1: Infrastructure (non-breaking)

1. Install deps: `npm install @tanstack/react-query
@tanstack/react-query-devtools zustand immer`
2. Create `store/`directory with all 5 slices +`app-store.ts`+`index.ts`
3. Create `queries/`directory with`query-client.ts`, `query-keys.ts`, all hooks
4. Create `bridge/ws-bridge.ts`
5. Add `QueryClientProvider`in`App.tsx`(wraps existing`<AppShell />`)
6. **Verify**: app runs identically (old `useAppState`still in use)

### Phase 2: Bridge activation

1. Call`initWsBridge()`in`AppShell`'s existing mount `useEffect`
2. Verify both old + new state systems populate via Redux DevTools + React Query
   DevTools
3. **Verify**: Zustand store and TQ cache receive correct data in parallel

### Phase 3: Component migration (one at a time)

1. `StatusBar`— simplest (2 store selectors) 2.`TabBar`— store selectors +`useThreadsQuery`
2. `PermissionModal`— store selector +`useRespondToPermission`mutation 4.`Sidebar`— store selectors +`useThreadsQuery`
3. `InputBar`—`useTeamPresetsQuery`+`useCreateThread`mutation + store selectors 6.`MessageStream`— continues receiving`events`as prop (no change needed) 7.`InspectorPanel`— store selectors 8.`AppShell`— remove`useAppState()`, use hooks directly, remove prop passing
4. **Verify after each**: app functional, no regressions

### Phase 4: Cleanup

1. Delete `hooks/use-app-state.ts`
2. Delete `data/mock-data.ts`+ remove demo permission`useEffect`from AppShell
3. Remove`AppState`type imports from all files
4. Remove`state: AppState`prop interfaces from component signatures
5. **Verify**:`npm run build`clean, 0 type errors, profile with React DevTools
   for render storms

---

## Verification

1. **Type check**:`npx tsc --noEmit`— 0 errors
2. **Build**:`npm run build`— clean, no warnings
3. **Dev server**:`npm run dev`— app loads, sidebar shows threads, tabs work
4. **WS flow**: Connect to backend, verify stream events accumulate in Zustand
   (Redux DevTools)
5. **REST caching**: Open React Query DevTools, verify thread list is cached,
   team presets fetched once
6. **Theme persistence**: Toggle dark/light, refresh page — preference preserved
7. **Tab hydration**: Click a thread tab, verify snapshot loads from REST then
   WS events append
8. **Permission flow**: Trigger permission request, verify modal appears,
   respond via REST mutation
9. **Render performance**: React DevTools Profiler — verify no cascading
   re-renders from WS chunks

---

## Files to Reference (no changes needed)

-`src/ui/src/app/api/rest-client.ts`— REST singleton, used by TQ hooks -`src/ui/src/app/api/websocket-client.ts`— WS singleton, used by bridge + tab
slice -`src/ui/src/app/api/mappers.ts`— wire→frontend translation, used by slices +
hooks -`src/ui/src/app/data/types.ts`— all frontend presentation types -`src/ui/src/app/data/wire-types.ts` — all wire types from backend
