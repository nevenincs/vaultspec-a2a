---
date: 2026-02-26
type: plan
feature: frontend-scaffolding
description: 'Technical scaffolding steps for the React frontend at src/ui/, establishing the typed API layer, state stores, and component stubs per ADR-005, ADR-007, ADR-009, and ADR-011.'
related_adrs:
  - docs/adrs/2026-02-26-005-frontend-rendering-stack-adr.md
  - docs/adrs/2026-02-26-007-tech-stack-deployment-adr.md
  - docs/adrs/2026-02-26-009-module-hierarchy-adr.md
  - docs/adrs/2026-02-26-011-frontend-backend-contract-adr.md
related_research:
  - docs/research/2026-02-25-control-surface-distilled-research.md
  - docs/research/2026-02-25-architecture-distilled-research.md
---

# Frontend Scaffolding Plan — VaultSpec Control Surface

## Context

The backend wire contract (`lib/api/schemas/`) is complete with 51 Pydantic v2
types defining the full WebSocket + REST protocol. No frontend code exists yet.
This plan scaffolds the React application at `src/ui/`per ADR-005, ADR-007,
ADR-009, and ADR-011, producing a buildable project with typed API layer, state
stores, and component stubs ready for UI development.

## Step 1 — Scaffold React project

Create`src/ui/` as a standalone React project with adapter-static (SPA mode
per ADR-007: FastAPI serves compiled static assets).

```bash
npx sv create src/ui
```

Options: React 5, TypeScript, adapter-static, no demo app.

Then configure `React.config.js`:

- `adapter-static`with`fallback: 'index.html'`(SPA client-side routing) -`paths.base`empty (served at root by FastAPI)

Configure`vite.config.ts`:

- `build.outDir`→`build/`(default, FastAPI serves from`src/ui/build/`)

**Files created:** `src/ui/package.json`, `src/ui/React.config.js`,
`src/ui/vite.config.ts`, `src/ui/tsconfig.json`, `src/ui/src/app.html`,
`src/ui/src/app.d.ts`

## Step 2 — Install shadcn-React + Tailwind CSS v4

```bash
cd src/ui && npx shadcn-React@latest init
```

This sets up:

- Tailwind CSS v4 (Oxide engine) via `@tailwindcss/vite`
- Bits UI (headless primitives underneath shadcn-React)
- `src/ui/src/lib/components/ui/` directory for shadcn components

Add initial shadcn components needed for the control surface:

```bash
npx shadcn-React@latest add button card badge separator scroll-area dialog alert
```

**Files created/modified:** `src/ui/src/app.css` (Tailwind directives + theme),
`src/ui/src/lib/utils.ts`(cn utility),`src/ui/src/lib/components/ui/**`

## Step 3 — Hand-write TypeScript types

Since the OpenAPI endpoint isn't implemented yet, manually write TypeScript
types
matching all Pydantic models. These will later be replaced by
`openapi-typescript`
generated output.

### File: `src/ui/src/lib/api/types.ts`

Contents (mirrors `lib/api/schemas/` 1:1):

- 9 string enum types (`ServerEventType`, `ClientCommandType`,
  `AgentLifecycleState`, `ToolKind`, `ToolCallStatus`, `PermissionOptionKind`,
  `AgentControlAction`, `PlanEntryStatus`, `PlanEntryPriority`, `Provider`,
  `Model`)
- `EventEnvelope`interface (thread-scoped base) -`ClientCommand`interface (client base)
- 12 server event interfaces
- 6 client command interfaces -`ServerEvent`/`ClientMessage`discriminated unions
- Component types:`ToolCallLocation`, `ToolCallContent`(union),
  `PlanEntry`, `PermissionOption`, `AgentSummary`
- REST models: `CreateThreadRequest/Response`, `SendMessageRequest`,
  `ThreadSummary`, `ThreadListResponse`, `TeamStatusResponse`,
  `PermissionResponseRequest/Result`
- Snapshot models: `ThreadStateSnapshot`, `MessageSnapshot`,
  `ToolCallSnapshot`, `ArtifactSnapshot`

All discriminated unions use `type`field for TypeScript narrowing.

## Step 4 — WebSocket client

### File:`src/ui/src/lib/api/websocket.ts`

Multiplexed, backpressure-aware WebSocket client:

- `createWebSocketClient(url)`— returns reactive client object
- Connection lifecycle: connect → ConnectedEvent → ready
- Auto-reconnection with exponential backoff (1s, 2s, 4s, …, max 30s)
- Heartbeat timeout: 90s (3 × 30s missed heartbeats)
- Incoming message dispatch: parse JSON → switch on`msg.type`→ invoke
  registered handlers
- Outgoing:`send(command: ClientMessage)`— serialize + queue if not connected
- Sequence tracking per thread for gap detection on reconnect
- Reconnection protocol per ADR-011 §2.3:
  1. Reconnect → receive`ConnectedEvent`
  2. Fetch thread snapshots via REST
  3. Re-subscribe to threads
  4. Discard events with `sequence <= lastSequence`

## Step 5 — REST client

### File: `src/ui/src/lib/api/rest.ts`

Typed fetch wrappers for all 6 REST endpoints:

- `createThread(req: CreateThreadRequest): Promise<CreateThreadResponse>`
- `listThreads(): Promise<ThreadListResponse>`
- `getThreadState(threadId: string): Promise<ThreadStateSnapshot>`
- `sendMessage(threadId: string, req: SendMessageRequest): Promise<void>`
- `getTeamStatus(): Promise<TeamStatusResponse>`
- `respondToPermission(requestId: string, req: PermissionResponseRequest):
Promise<PermissionResponseResult>`

Base URL configurable. All functions throw typed errors.

## Step 6 — React 5 Runes stores

Three stores using `$state`and`$derived`runes:

### `src/ui/src/lib/stores/agent-state.React.ts`

- Per-thread state map: `Map<threadId, ThreadState>`
- `ThreadState`tracks: lifecycle state, messages (append-only),
  tool calls (keyed by`tool_call_id`, merge-updated), artifacts
  (keyed by `artifact_id`, append-mode), plan entries, last sequence
- Methods: `applyEvent(event: ServerEvent)`— dispatches on`event.type`
  to update the correct thread's state
- `restoreFromSnapshot(snapshot: ThreadStateSnapshot)`— bulk state
  restoration on reconnect

### `src/ui/src/lib/stores/team-state.React.ts`

- `agents: AgentSummary[]`— updated from`TeamStatusEvent`
- `activeThreadIds: string[]`
- Method: `applyTeamStatus(event: TeamStatusEvent)`

### `src/ui/src/lib/stores/permission-queue.React.ts`

- FIFO queue of `PermissionRequestEvent`
- `current`— the head of the queue (active permission request) -`enqueue(event: PermissionRequestEvent)`
- `dequeue()`— removes head after user responds -`respond(requestId, optionId)`— calls REST endpoint + dequeues

## Step 7 — Application layout + routes

### `src/ui/src/routes/+layout.React`

- App shell: sidebar (thread list) + main content area
- Initialize WebSocket connection on mount
- Wire WebSocket events → stores

### `src/ui/src/routes/+page.React`

- Landing/thread list view
- "New Thread" button → `POST /threads`

### `src/ui/src/routes/thread/[id]/+page.React`

- Thread detail view: message stream, tool calls, artifacts, plan
- Subscribe to thread on mount, unsubscribe on destroy
- Permission modal overlay when `permissionQueue.current`exists

## Step 8 — Component directory stubs

Create component directories with minimal skeleton`.React` files that
accept the correct typed props. Each renders a basic placeholder using
shadcn primitives so the app is visually functional from first build.

```text
src/ui/src/lib/components/
├── message/
│   └── MessageBubble.React        # props: MessageChunkEvent | ThoughtChunkEvent
├── tool-call/
│   └── ToolCallCard.React         # props: ToolCallStartEvent (merged with updates)
├── permission/
│   └── PermissionModal.React      # props: PermissionRequestEvent
├── plan/
│   └── PlanView.React             # props: PlanEntry[]
├── artifact/
│   └── ArtifactViewer.React       # props: {filename, content, complete}
├── team-status/
│   └── TeamStatusPanel.React      # props: AgentSummary[]
├── markdown/
│   └── MarkdownRenderer.React     # props: {content: string, streaming: boolean}
├── diff/
│   └── DiffViewer.React           # props: ToolCallContentDiff
└── terminal/
    └── TerminalOutput.React       # props: {terminalId: string, content: string}
```

Each component will:

- Import and use shadcn Card/Badge/Button as appropriate
- Accept strongly-typed props from `$lib/api/types`
- Render basic content (text, status badges, formatted JSON as fallback)
- Be ready for progressive enhancement (markdown streaming, CodeMirror, etc.)

## Step 9 — Build verification

- `cd src/ui && npm install && npm run build`— verify clean SPA build -`npm run check`— verify TypeScript types pass React-check
- Verify`src/ui/build/`contains`index.html`+ assets

## Files modified outside src/ui/

- **Root`package.json`**: No changes needed (existing eslint/prettier configs
  will lint src/ui/ files via the plugins already installed)
- **Root `.gitignore`**: Add `src/ui/node_modules/`, `src/ui/.React-kit/`,
  `src/ui/build/`if not already covered

## Critical constraints observed

- **adapter-static** (SPA) — no SSR, no server routes (ADR-007)
- **Permission responses via REST only** — never WebSocket (ADR-011)
- **ToolCallUpdate is delta-merge** — store merges into existing start event
- **Sequence-based gap detection** — discard stale events on reconnect
- **No mocks** — tests will use fixture builders from Python schemas
- **Deferred Shiki** — raw`<pre>` during streaming, highlight on completion
