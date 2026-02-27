# Frontend Scaffolding Audit Report

**Date:** 2026-02-26
**Scope:** `src/ui/` — SvelteKit 5 frontend scaffolding (Steps 1–9)
**Audited against:** ADR-005, ADR-007, ADR-009, ADR-011, UI Spec, Scaffolding
Plan, Pydantic schemas
**Auditors:** Orchestrator, Coder (self-review), Researcher-1 (ADR compliance),
Researcher-2 (research doc gap analysis)

---

## Executive Summary

The scaffolding produced a buildable SvelteKit 5 SPA with 473-line typed API
layer, 3 reactive stores, 6 REST wrappers, a WebSocket client, 3 routes, and
9 component stubs — backed by 21 shadcn-svelte component sets. Automated checks
pass: svelte-check (836 files, 0 errors, 0 warnings), Prettier clean.

Cross-referencing against binding ADRs, user-approved UI spec, and Pydantic
schemas reveals **32 unique findings** after de-duplication across all 4 auditors:
7 critical, 8 high, 10 moderate, 7 low. All 4 auditors independently confirmed
TypeScript types are 100% field-accurate against Pydantic models.

---

## CRITICAL (7) — Will break functionality

### C-1: SvelteMap in-place mutation — tool call updates invisible to UI

**File:** `agent-state.svelte.ts:257-267`
**Found by:** Coder (unique)

`#applyToolCallUpdate` mutates fields on the existing `ThreadToolCall` object
retrieved from the SvelteMap but never calls `thread.toolCalls.set(id, existing)`
afterward. SvelteMap only triggers reactivity on `set`/`delete`, not on in-place
mutation of stored values. Tool call status transitions (pending → in_progress →
completed) will **not re-render** in the UI.

**Fix:** Add `thread.toolCalls.set(event.tool_call_id, existing)` at end of
method.

### C-2: SvelteMap in-place mutation — artifact streaming invisible to UI

**File:** `agent-state.svelte.ts:272-273`
**Found by:** Coder (unique)

Same pattern as C-1: `#applyArtifactUpdate` append path mutates
`existing.content += event.content` and `existing.filename = event.filename`
without re-setting the SvelteMap entry. Streaming artifact content will not
update in the UI.

**Fix:** Add `thread.artifacts.set(event.artifact_id, existing)` at end of
append branch.

### C-3: `$derived` calls `getOrCreateThread` — side effect in derivation

**File:** `thread/[id]/+page.svelte:13`
**Found by:** Researcher-2 (unique), confirmed by Orchestrator

```ts
let thread: ThreadState = $derived(agentState.getOrCreateThread(threadId));
```

`getOrCreateThread` mutates the store (creates a new ThreadState + sets it in
the SvelteMap). Svelte 5 runes documentation explicitly warns against side
effects in derivations — they can cause infinite re-derivation loops when the
mutation triggers reactivity on the same dependency graph.

**Fix:** Call `getOrCreateThread` in `onMount`/`$effect`, use pure `.get()` in
`$derived`.

### C-4: `$effect(() => loadThreads())` may loop infinitely

**File:** `+page.svelte:32-34`
**Found by:** Orchestrator, Coder

The `$effect` calls `loadThreads()` which sets `$state` variables (`threads`,
`loading`). If Svelte 5's tracking system considers those state mutations as
dependencies that re-trigger the effect, this creates an infinite REST call
loop. Should use `onMount` for one-time data fetching.

**Fix:** Replace `$effect(() => { loadThreads(); })` with `onMount(loadThreads)`.

### C-5: `isStaleEvent()` exists but never called in WS handler

**File:** `websocket.svelte.ts:111-113, :128-151`
**Found by:** Orchestrator, Researcher-1, Researcher-2

The `isStaleEvent()` method correctly checks sequence numbers, but `onmessage`
dispatches events to handlers without any staleness check. After reconnection,
duplicate events from the overlap window will corrupt store state (duplicate
messages, tool call restarts, etc.).

**Fix:** Call `isStaleEvent()` before dispatching thread-scoped events in
`onmessage`.

### C-6: Double event handling — permission_request enqueued twice

**File:** `+layout.svelte:34-39`
**Found by:** Orchestrator, Researcher-1, Researcher-2

The layout registers a specific handler for `PERMISSION_REQUEST` (→
permissionQueue.enqueue), then also routes ALL events through
`agentState.applyEvent()` via the `for` loop. While agentState has a no-op
`break` for PERMISSION_REQUEST, the **permissionQueue.enqueue is called once
by the specific handler**, meaning the dedicated handler fires correctly but
the architecture is confusing and fragile.

More critically, if the agentState ever forwards permission events to the
queue (a natural refactor), double-enqueue will occur. The control flow should
be cleaned up to a single dispatch path.

**Fix:** Remove dedicated TEAM_STATUS/PERMISSION_REQUEST handlers; route all
events through `handleAllEvents` → `agentState.applyEvent()`, which then
delegates to appropriate stores.

### C-7: No WS subscribe/unsubscribe on thread navigation

**File:** `thread/[id]/+page.svelte`
**Found by:** Orchestrator, Researcher-1, Coder

ADR-011 §2.1 requires explicit `SubscribeCommand` to receive thread-scoped
events. Neither the layout nor the thread page sends a SubscribeCommand after
connecting or navigating. The server has no way to know which threads the
client cares about — no real-time events will be delivered.

**Fix:** Send `SubscribeCommand` on thread page mount, `UnsubscribeCommand`
on destroy.

---

## HIGH (8) — Contradict ADRs, UI spec, or research

### H-1: No reconnection protocol (ADR-011 §2.3)

**Files:** `websocket.svelte.ts`, `+layout.svelte`
**Found by:** Orchestrator, Researcher-1, Researcher-2

The WebSocket client reconnects via `#open()` after backoff but does NOT
implement the full protocol: (1) receive ConnectedEvent → (2) extract
`client_id` → (3) GET /threads/{id}/state → (4) `restoreFromSnapshot()` →
(5) re-subscribe to active threads → (6) process new events with stale
filtering. The `clientId` `$state` field exists but is never assigned.

### H-2: Thread page uses Card.Root, not AlertDialog for permissions

**Files:** `thread/[id]/+page.svelte:151-170`
**Found by:** Orchestrator, Researcher-1

UI Spec §5 mandates a non-dismissible centered modal. The thread page uses a
raw `<div>` with `bg-black/50` overlay and `Card.Root` which is dismissible by
click-outside. The proper `PermissionModal.svelte` component exists (uses
`AlertDialog.Root`) but is not imported.

### H-3: PermissionModal AlertDialog is also dismissible

**File:** `PermissionModal.svelte:15`
**Found by:** Researcher-1 (unique)

Even the dedicated PermissionModal component, while using `AlertDialog.Root`,
doesn't set `closeOnOutsideClick={false}` or intercept Escape. The UI Spec §5
says "cannot be dismissed without responding."

### H-4: Sidebar empty — no thread list, team status, connection indicator

**Files:** `+layout.svelte:62-67`, `+page.svelte`
**Found by:** Orchestrator, Researcher-1

UI Spec §2 defines a 240px collapsible sidebar with thread list (top), team
status (bottom), "New Thread" button, and collapse toggle. The current sidebar
is an empty `<aside>` with only "VaultSpec" text. Thread list renders fullscreen
in the main content area.

### H-5: Tool calls rendered separately, not in chronological stream

**File:** `thread/[id]/+page.svelte:65-131`
**Found by:** Researcher-1 (unique), confirmed by Orchestrator

UI Spec §3 requires a single chronological stream interleaving messages, tool
calls, and thoughts. The page renders all messages (L66-88), then all tool
calls (L91-110), then all artifacts (L113-131) — destroying temporal context.

### H-6: Thread creation hardcodes `initial_message: 'Hello'`

**File:** `+page.svelte:23-26`
**Found by:** Orchestrator, Researcher-1

UI Spec §10 specifies inline thread creation — user types in the input bar and
their first message creates the thread. Current implementation sends
`initial_message: 'Hello'` regardless of user intent.

### H-7: WS `on()` method accepts `string` instead of `ServerEventType`

**File:** `websocket.svelte.ts:71`
**Found by:** Orchestrator

`on(type: string, handler: EventHandler)` should accept `ServerEventType` for
type safety. Currently any arbitrary string can be passed as an event type.

### H-8: `clientId` never set from ConnectedEvent

**File:** `websocket.svelte.ts:17-18, :121-126`
**Found by:** Researcher-2, Coder

The `clientId` `$state` field exists but the `onopen`/`onmessage` handler never
extracts `client_id` from the ConnectedEvent. Related to H-1 but specific to
client identity tracking.

---

## MODERATE (10) — Code quality issues

### M-1: `ThreadMessage.role` type `| string` makes union meaningless

**File:** `agent-state.svelte.ts:31`
**Found by:** Orchestrator, Coder

`role: 'assistant' | 'user' | 'thought' | string` — the `| string` widens
the type to accept any string, defeating the named variants. Should be just
`string` (matches Pydantic `str`) or a strict union.

### M-2: `ThreadToolCall.kind` and `.status` typed as `string` not enums

**File:** `agent-state.svelte.ts:40-42`
**Found by:** Orchestrator

Should use `ToolKind` and `ToolCallStatus` types from `types.ts`, matching the
Pydantic models. The current `string` types allow invalid values.

### M-3: `#messageAccumulators` never cleaned up (memory leak)

**File:** `agent-state.svelte.ts:73`
**Found by:** Orchestrator, Coder

The plain Map accumulating streaming message chunks grows indefinitely. No
cleanup occurs when messages finish or threads are removed.

### M-4: `restoreFromSnapshot` skips `pending_permissions`

**File:** `agent-state.svelte.ts:152-203`
**Found by:** Coder (unique)

The restore function processes messages, tool_calls, artifacts, plan, and
agents, but skips the `pending_permissions` array from `ThreadStateSnapshot`.
On reconnect, pending permission requests won't be shown.

### M-5: `restoreFromSnapshot` loses `detail` field

**File:** `agent-state.svelte.ts:196-198`
**Found by:** Orchestrator

Sets `lifecycleState` and `nodeName` from first agent but never restores
`thread.detail`, which remains null.

### M-6: `lastSequence` initial value -1 vs WS client returning 0

**File:** `agent-state.svelte.ts:62`, `websocket.svelte.ts:95-96`
**Found by:** Orchestrator

Store initializes to -1, but `getLastSequence` returns 0 for unknown threads.
First event (sequence=0) accepted by store (0 > -1) but marked stale by WS
client (0 <= 0).

### M-7: No error handling on REST calls in components

**Files:** `+page.svelte:22-29`, `thread/[id]/+page.svelte:22-27`
**Found by:** Orchestrator, Coder

`handleSendMessage()` and `handleNewThread()` call REST endpoints without
try/catch. Errors will be uncaught promise rejections.

### M-8: No ErrorEvent wired to sonner toast

**File:** `agent-state.svelte.ts:140-141`
**Found by:** Orchestrator

`<Toaster />` from sonner is mounted in layout but no ErrorEvent handler calls
`toast.error()` anywhere. Server errors are silently swallowed.

### M-9: Unsafe `as` casts in WS onmessage

**File:** `websocket.svelte.ts:134-139`
**Found by:** Researcher-1, Coder

`(event as { thread_id: string })` — should use proper type narrowing with
`'thread_id' in event` instead of unsafe casts.

### M-10: TeamStatusPanel missing Tooltip.Provider wrapper

**File:** `TeamStatusPanel.svelte:15-22`
**Found by:** Researcher-1 (unique)

`Tooltip.Root` used without a `Tooltip.Provider` ancestor will error at runtime
in shadcn-svelte/Bits UI.

---

## LOW (7) — Style, placeholders, minor gaps

### L-1: No test files in `src/ui/`

Zero test files for stores, utilities, or API modules.
**Found by:** Orchestrator

### L-2: Component stubs not used in routes

`MessageBubble`, `ToolCallCard`, `ArtifactViewer`, `PlanView`,
`TeamStatusPanel`, `PermissionModal` all exist but routes have inline
implementations instead.
**Found by:** Orchestrator

### L-3: PlanView keys `#each` by index not unique ID

`{#each entries as entry, i (i)}` — index keys cause incorrect list diffing on
mutations.
**Found by:** Orchestrator

### L-4: TerminalOutput `content` prop never populated from events

`ToolCallContentTerminal` type has only `terminal_id`, no content field. The
`content` prop default is fine as a placeholder but will never receive data.
**Found by:** Orchestrator

### L-5: No ESLint config for `src/ui/`

Root ESLint config excludes `src/ui/` to avoid Svelte 5 parse errors. No local
ESLint config with svelte parser exists for hand-written files.
**Found by:** Coder (unique)

### L-6: Stores barrel missing interface type re-exports

`stores/index.ts` exports `ThreadState` type but not `ThreadMessage`,
`ThreadToolCall`, `ThreadArtifact` — requiring deep imports.
**Found by:** Orchestrator

### L-7: Private Python snapshot types exposed as public TS exports

`_PermissionSnapshot`, `_PermissionOptionSnapshot`, `_AgentSnapshot` are
private in Python but exported as public in `types.ts`.
**Found by:** Orchestrator

---

## Rendering Library Integration Status (ADR-005)

These component stubs use `<pre>` placeholders. Expected for scaffolding phase
but tracked for Phase 3 remediation.

| Component | Required Library (ADR-005) | Current State |
|-----------|--------------------------|---------------|
| MarkdownRenderer | @humanspeak/svelte-markdown | raw `<pre>` |
| DiffViewer | diff2html | raw `<pre>`, comment names wrong lib |
| ArtifactViewer | CodeMirror 6 (read-only) | raw `<pre>` |
| TerminalOutput | xterm.js v5 + WebGL addon | raw `<pre>` |
| app.css | xterm.js Preflight isolation | Not present |

---

## Type Alignment Verification

All 51 TypeScript types in `types.ts` verified field-by-field against Pydantic
schemas. Result: **100% alignment** (confirmed by all 4 auditors independently).

| Module | Types | Match |
|--------|-------|-------|
| enums | 11 const objects + types | Exact |
| events (component) | ToolCallLocation, ToolCallContent (3), PlanEntry, PermissionOption, AgentSummary | Exact |
| events (server) | 12 event interfaces | Exact |
| commands | 6 command interfaces + union | Exact |
| rest | 8 interfaces | Exact |
| snapshots | 7 interfaces | Exact (private prefix dropped, see L-7) |
| base | EventEnvelope, ClientCommand | Exact |

---

## Positive Confirmations (all 4 auditors agree)

- All 51 TypeScript types correct, field-for-field match with Pydantic
- REST client correct (6 endpoints, proper error handling, encodeURIComponent)
- WebSocket exponential backoff and heartbeat timeout correct
- Store event dispatch logic (exhaustive switch with assertExhaustive) correct
- Permission queue REST-only pattern correct (per ADR-011)
- Build clean (836 files, 0 errors, 0 warnings)
- Prettier formatting clean
- SvelteMap usage for fine-grained reactivity is correct architectural choice

---

## Severity Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 7 |
| HIGH | 8 |
| MODERATE | 10 |
| LOW | 7 |
| **Total** | **32** |

---

## Recommended Remediation Order

### Phase 1 — Reactivity + Protocol (blocks all integration testing)

1. **C-1 + C-2**: SvelteMap re-set after mutation (trivial 2-line fix, highest
   impact)
2. **C-3**: Remove side effect from `$derived` — use `onMount`/`$effect` for
   creation, `.get()` in `$derived`
3. **C-4**: Replace `$effect` with `onMount` for `loadThreads()`
4. **C-6**: Fix double event dispatch — single dispatch path through agentState
5. **C-5 + C-7 + H-1**: Wire stale event filtering + subscribe/unsubscribe +
   full reconnection protocol
6. **H-8**: Set `clientId` from ConnectedEvent
7. **M-6**: Align `lastSequence` initialization

### Phase 2 — Layout alignment (blocks UI testing)

8. **H-4**: Implement sidebar with shadcn Sidebar, thread list, team status
9. **H-5**: Create unified chronological stream interleaving messages + tool
   calls + artifacts
10. **H-6**: Inline thread creation from input bar
11. **H-2 + H-3**: Use PermissionModal in thread page, make non-dismissible
12. **M-10**: Wrap TeamStatusPanel tooltips in Tooltip.Provider

### Phase 3 — Rendering fidelity (progressive enhancement)

13. Integrate `@humanspeak/svelte-markdown` into MarkdownRenderer
14. Replace DiffViewer with diff2html
15. Integrate CodeMirror 6 into ArtifactViewer
16. Integrate xterm.js v5 with Preflight isolation in app.css

### Phase 4 — Polish + Missing features

17. Status bar (connection indicator, agent count, heartbeat)
18. Theme toggle with mode-watcher (Dark/Light/System)
19. Keyboard shortcuts (Ctrl+K, Ctrl+N, Ctrl+Enter, Escape)
20. Smart auto-scroll
21. Inspector panel with tabbed content
22. Input bar with provider/model selector + Stop button
23. Wire ErrorEvent → sonner toast
24. Fix type issues (M-1, M-2, M-9)
25. Add ESLint config for `src/ui/`
26. Fix stores barrel re-exports
27. Add unit tests for stores and WebSocket client

---

## Open Decision: SPA Fallback Value

`svelte.config.js` uses `fallback: 'index.html'`. Researcher-1 flagged this
as a violation (SvelteKit convention is `200.html`). However, this depends on
how FastAPI's static file mount is configured (ADR-007). If FastAPI serves the
SPA shell on all 404s as `index.html`, the current value is correct. If
using a CDN or generic static server, `200.html` is needed. **Needs team
decision based on deployment strategy.**
