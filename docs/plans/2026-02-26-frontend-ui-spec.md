# Frontend UI Specification — VaultSpec Control Surface

## 1. Overview

This document defines the complete user interface specification for the
VaultSpec Control Surface frontend. It is the binding reference for all
component implementation, layout decisions, and interaction behavior.

**Companion documents:**

- `docs/plans/2026-02-26-frontend-scaffolding-plan.md` — technical
  scaffolding steps
- `docs/adrs/005-frontend-rendering-stack.md` — rendering stack decisions
- `docs/adrs/011-frontend-backend-contract.md` — wire protocol contract

---

## 2. Application Layout

### 2.1 Three-Panel Architecture

The application uses a three-panel layout: **Sidebar**, **Stream**,
and **Inspector** (on-demand).

```text
┌──────────────────────────────────────────────────────────────────┐
│  VaultSpec Control Surface                                       │
├───────────────┬──────────────────────────────────────────────────┤
│               │                                                  │
│   SIDEBAR     │            MESSAGE STREAM                        │
│   (240px)     │            (fills remaining width)               │
│               │                                                  │
│  ┌──────────┐ │  ┌──────────────────────────────────────┐        │
│  │ Threads  │ │  │  Chat bubbles, tool cards,           │        │
│  │          │ │  │  thoughts, artifacts — all inline     │        │
│  │          │ │  │                                       │        │
│  ├──────────┤ │  │                                       │        │
│  │ Team     │ │  ├──────────────────────────────────────┤        │
│  │ Status   │ │  │  Input Bar (provider + textarea)     │        │
│  └──────────┘ │  └──────────────────────────────────────┘        │
├───────────────┴──────────────────────────────────────────────────┤
│  Status Bar (connection · threads · heartbeat)                   │
└──────────────────────────────────────────────────────────────────┘
```

When the **Inspector** is open (triggered by clicking a tool card,
artifact, or plan item):

```text
┌───────────────┬──────────────────────┬───────────────────────────┐
│   SIDEBAR     │  STREAM (narrowed)   │    INSPECTOR (~40%)       │
│   (240px)     │                      │    (slides in from right) │
│               │                      │                           │
│               │                      │  [X] Title                │
│               │                      │  [Tab1] [Tab2] [Tab3]     │
│               │                      │                           │
│               │                      │  Content area             │
│               │                      │                           │
└───────────────┴──────────────────────┴───────────────────────────┘
```

### 2.2 Responsive Behavior

- **Sidebar**: 240px default width, resizable 180–400px via drag handle.
  Collapsible via toggle button (`Ctrl+.`). When collapsed, only a narrow
  strip with the expand toggle remains.
- **Stream**: fills all remaining horizontal space. When inspector opens,
  the stream narrows proportionally.
- **Inspector**: ~40% of the content area width. Resizable. Slides in from
  the right with a subtle transition. Closes with `[X]` button or `Escape`.
- **Minimum viewport**: 1024px width. Below that, sidebar auto-collapses.

---

## 3. Sidebar

### 3.1 Structure

The sidebar is divided into two stacked sections:

```text
┌────────────────────────┐
│ [◀] VaultSpec  [☾]     │  ← header: collapse toggle + theme toggle
├────────────────────────┤
│ [+ New Thread]         │  ← action button
├────────────────────────┤
│ THREADS                │  ← section label
│ ┌────────────────────┐ │
│ │ ● Debug auth bug   │ │  ← active thread (highlighted bg)
│ │   working · 3m ago │ │  ← state badge + relative time
│ └────────────────────┘ │
│ ┌────────────────────┐ │
│ │ ○ Refactor models  │ │  ← inactive thread
│ │   idle · 12m ago   │ │
│ └────────────────────┘ │
│         ...            │  ← scrollable list
├────────────────────────┤
│ TEAM STATUS            │  ← fixed at bottom, not scrollable
│ ● Planner  working     │
│ ○ Coder    idle        │
│ △ Reviewer input_req   │
└────────────────────────┘
```

### 3.2 Thread List Items

Each thread entry displays:

| Element           | Source                | Behavior                      |
|-------------------|-----------------------|-------------------------------|
| Status dot        | `AgentLifecycleState` | Color-coded (see §6)         |
| Title             | `ThreadSummary.title` | Truncated with ellipsis       |
| State label       | `agent_state`         | Text badge (working, idle...) |
| Relative time     | `updated_at`          | "3m ago", "1h ago", etc.      |

- **Click**: navigates to `/thread/[id]`, subscribes to thread
- **Active thread**: highlighted background, bold title
- **Right-click / long-press**: context menu (rename, delete — future)

### 3.3 Team Status Panel

Fixed-height panel at the bottom of the sidebar. Displays all agents from
`TeamStatusEvent.agents`:

| Element    | Source                    | Display                     |
|------------|---------------------------|-----------------------------|
| Status dot | `AgentSummary.state`      | Color-coded (see §6)        |
| Name       | `AgentSummary.node_name`  | Agent display name          |
| State      | `AgentSummary.state`      | Text label                  |

---

## 4. Message Stream

### 4.1 Event-to-UI Mapping

The central stream renders server events chronologically as inline elements:

| Server Event             | UI Element              | Alignment | Style               |
|--------------------------|-------------------------|-----------|----------------------|
| `SendMessageCommand`     | Chat bubble             | Right     | User message color   |
| `MessageChunkEvent`      | Chat bubble (streaming) | Left      | Agent message color  |
| `ThoughtChunkEvent`      | Collapsible thought     | Left      | Dimmed, italic       |
| `ToolCallStartEvent`     | Tool call card          | Left      | Bordered card        |
| `ToolCallUpdateEvent`    | Updates existing card   | —         | Delta-merge          |
| `ArtifactUpdateEvent`    | Artifact card           | Left      | File icon + name     |
| `PlanUpdateEvent`        | Plan update card        | Left      | Checklist summary    |
| `PermissionRequestEvent` | Modal overlay           | Center    | Blocking modal       |
| `AgentStatusEvent`       | Inline status badge     | Center    | Subtle divider-style |
| `ErrorEvent`             | Error alert             | Full      | Red/destructive      |

### 4.2 Chat Bubbles (MessageChunkEvent)

- **User messages**: right-aligned, distinct background color
- **Agent messages**: left-aligned, default surface color
- **Streaming**: text streams in character-by-character with cursor indicator
- **Markdown**: rendered via `@humanspeak/svelte-markdown` with intelligent
  token caching (O(n) streaming). Code blocks show raw `<pre>` during
  streaming, Shiki highlights on completion (deferred, per ADR-005).
- **Agent label**: small text above the bubble showing `agent_id` when
  multiple agents are active

### 4.3 Thought Blocks (ThoughtChunkEvent)

- **Default state**: collapsed single-line with dimmed text
  ```
  ┌─ 💭 Thinking...          [▶] ─┐
  └─────────────────────────────────┘
  ```
- **Expanded state**: shows full streaming content
  ```
  ┌─ 💭 Thinking              [▼] ─┐
  │ Need to check the session       │
  │ handling in middleware to        │
  │ understand the auth flow...     │
  └─────────────────────────────────┘
  ```
- **Visual**: dimmed opacity (~60%), italic text, smaller font size
- **Interaction**: click `[▶/▼]` to toggle
- **Auto-collapse**: collapses automatically when the agent's next
  non-thought event arrives
- **During streaming**: if expanded, content streams in real-time

### 4.4 Tool Call Cards (ToolCallStartEvent + ToolCallUpdateEvent)

Compact inline cards showing tool execution status:

**Running state**:
```
┌──────────────────────────────────┐
│ 🔧 read_file               ●    │  ← animated spinner
│ auth.py:42            [running]  │  ← location + status badge
└──────────────────────────────────┘
```

**Completed state**:
```
┌──────────────────────────────────┐
│ ✓ read_file                      │  ← green checkmark
│ auth.py:42          [completed]  │
└──────────────────────────────────┘
```

**Failed state**:
```
┌──────────────────────────────────┐
│ ✗ execute_shell                  │  ← red X, red border accent
│ npm install            [failed]  │
└──────────────────────────────────┘
```

- **Click**: opens inspector with tool call detail
- **Delta-merge**: `ToolCallUpdateEvent` merges into existing card
  (keyed by `tool_call_id`). Status, content fields update in-place.
- **Icon**: derived from `ToolKind` enum (read, edit, search, execute, etc.)

### 4.5 Artifact Cards (ArtifactUpdateEvent)

```
┌──────────────────────────────────┐
│ 📄 auth.py (modified)            │
│ ▸ Click to view diff             │
└──────────────────────────────────┘
```

- **Click**: opens inspector with artifact detail (Preview / Diff / Raw tabs)
- **Icon**: file type icon based on extension
- **Append-mode**: new content appends; `complete: true` finalizes

### 4.6 Plan Update Cards (PlanUpdateEvent)

```
┌──────────────────────────────────┐
│ 📋 Plan updated (3/5 complete)   │
│ ▸ Click to view plan             │
└──────────────────────────────────┘
```

- **Click**: opens inspector with plan checklist (see §5.3)
- **Summary**: shows completion ratio inline

### 4.7 Error Alerts (ErrorEvent)

Full-width destructive alert using shadcn `Alert` component:

```
┌──────────────────────────────────────────┐
│ ⚠ Error                                  │
│ Connection to agent "Planner" lost.      │
│ Thread: debug-auth · Code: AGENT_TIMEOUT │
└──────────────────────────────────────────┘
```

### 4.8 Auto-Scroll Behavior

- **Smart auto-scroll**: auto-scrolls to bottom when new content arrives
  IF user is within 100px of the bottom
- **Scroll-up pauses**: if user scrolls up to read history, auto-scroll
  pauses
- **"New messages" badge**: floating badge appears above input bar:
  ```
  ┌───────────────────────┐
  │  ▼ 3 new messages     │
  └───────────────────────┘
  ```
  - Click badge: scrolls to bottom and resumes auto-scroll
  - Scroll to bottom manually: also resumes auto-scroll

---

## 5. Inspector Panel

### 5.1 General Behavior

- **Trigger**: opens when user clicks a tool card, artifact card, or plan
  update card in the stream
- **Position**: slides in from the right edge, occupying ~40% of the
  content area width
- **Resizable**: drag handle on left edge
- **Close**: `[X]` button, `Escape` key, or `Ctrl+I` toggle
- **Transition**: subtle slide animation (200ms ease-out)
- **Persistence**: stays open when scrolling the stream. Clicking a
  different inspectable item updates the inspector content without closing.

### 5.2 Tool Call Inspector

Shown when clicking a tool call card.

**Header**: tool name + close button
**Tabs**: `Output` | `Diff` | `JSON`

```text
┌────────────────────────────────┐
│ [X] read_file                  │
├────────────────────────────────┤
│ [Output] [Diff] [JSON]        │
├────────────────────────────────┤
│ File: auth.py:42               │
│ Status: completed              │
│ Kind: read                     │
│                                │
│ ┌────────────────────────────┐ │
│ │ def validate_token():      │ │
│ │     if not token:           │ │
│ │         raise AuthError()  │ │
│ │     ...                     │ │
│ └────────────────────────────┘ │
└────────────────────────────────┘
```

**Tab content by `ToolCallContent` type**:

| Content Type              | Output Tab          | Diff Tab              | JSON Tab       |
|---------------------------|---------------------|-----------------------|----------------|
| `ToolCallContentText`     | Rendered text/code  | —                     | Raw JSON       |
| `ToolCallContentDiff`     | New text            | Side-by-side diff     | Raw JSON       |
| `ToolCallContentTerminal` | Terminal output     | —                     | Raw JSON       |

### 5.3 Plan Inspector

Shown when clicking a plan update card or plan icon.

**Header**: "Execution Plan" + close button
**Tabs**: `Checklist` | `Timeline`

```text
┌────────────────────────────────┐
│ [X] Execution Plan             │
├────────────────────────────────┤
│ [Checklist] [Timeline]         │
├────────────────────────────────┤
│                                │
│ ☑ Analyze auth module    HIGH  │  ← completed (green)
│ ☑ Read session config    MED   │  ← completed (green)
│ ■ Fix validation         HIGH  │  ← in_progress (blue, pulsing)
│ ☐ Update tests           LOW   │  ← pending (gray)
│ ☐ Run test suite         MED   │  ← pending (gray)
│                                │
└────────────────────────────────┘
```

**Status icons**:
- `☑` completed — green
- `■` in_progress — blue with subtle pulse animation
- `☐` pending — gray

**Priority badges**: `HIGH` (red), `MED` (yellow), `LOW` (gray)

### 5.4 Artifact Inspector

Shown when clicking an artifact card.

**Header**: filename + close button
**Tabs**: `Preview` | `Diff` | `Raw`

- **Preview**: CodeMirror 6 read-only view with syntax highlighting
- **Diff**: `diff2html` rendered diff (if old content available)
- **Raw**: plain text content

---

## 6. Agent Lifecycle State Visualization

Each `AgentLifecycleState` maps to a visual indicator used consistently
across the sidebar thread list, team status panel, and stream badges:

| State            | Dot Color  | Icon    | Animation        | Label Text     |
|------------------|------------|---------|------------------|----------------|
| `submitted`      | Gray       | `○`     | Pulse (slow)     | "submitted"    |
| `idle`           | Green      | `○`     | None             | "idle"         |
| `working`        | Blue       | `●`     | Pulse (active)   | "working"      |
| `input_required` | Yellow     | `△`     | Pulse (attention)| "input needed" |
| `auth_required`  | Orange     | `⚠`     | Pulse (warning)  | "auth needed"  |
| `completed`      | Green      | `✓`     | None             | "completed"    |
| `failed`         | Red        | `✗`     | None             | "failed"       |
| `cancelled`      | Gray       | `—`     | None             | "cancelled"    |

---

## 7. Permission Modal

### 7.1 Behavior

- **Trigger**: `PermissionRequestEvent` arrives via WebSocket
- **Display**: centered modal with dimmed backdrop overlay
- **Blocking**: cannot be dismissed without responding (no click-outside,
  no Escape)
- **Queue**: FIFO queue. If multiple permission requests arrive, they are
  displayed one at a time. Queue counter shows position (e.g., "1 of 3").
- **Response**: sent via REST `POST /permissions/{id}/respond` (never
  WebSocket, per ADR-011)

### 7.2 Layout

```text
┌────────────────────────────────────┐
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ ░░ ┌──────────────────────────┐ ░░ │
│ ░░ │ Permission Required       │ ░░ │
│ ░░ ├──────────────────────────┤ ░░ │
│ ░░ │ Agent: Planner           │ ░░ │
│ ░░ │ Tool:  execute_shell     │ ░░ │
│ ░░ │                          │ ░░ │
│ ░░ │ "Run npm install in     │ ░░ │
│ ░░ │  the project root"      │ ░░ │
│ ░░ │                          │ ░░ │
│ ░░ │ [Allow] [Deny] [Skip]   │ ░░ │
│ ░░ │                          │ ░░ │
│ ░░ │ ● 1 of 3 pending        │ ░░ │
│ ░░ └──────────────────────────┘ ░░ │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
└────────────────────────────────────┘
```

### 7.3 Modal Content

| Element         | Source                              | Display                   |
|-----------------|-------------------------------------|---------------------------|
| Title           | Static                              | "Permission Required"     |
| Agent name      | `agent_id`                          | Agent identifier          |
| Tool name       | `tool_name`                         | Tool being invoked        |
| Tool kind       | `tool_kind` (`ToolKind` enum)       | Icon + label              |
| Description     | `message`                           | Human-readable request    |
| Options         | `options: PermissionOption[]`       | Buttons per option        |
| Queue position  | Permission queue length             | "N of M pending"          |

### 7.4 Option Buttons

Each `PermissionOption` renders as a button:

| `PermissionOptionKind` | Button Style  | Label Example        |
|------------------------|---------------|----------------------|
| `allow`                | Primary       | "Allow"              |
| `deny`                 | Destructive   | "Deny"               |
| `allow_always`         | Secondary     | "Always Allow"       |
| `deny_always`          | Ghost         | "Always Deny"        |

---

## 8. Input Bar

### 8.1 Layout

Pinned to the bottom of the stream panel:

```text
┌─────────────────────────────────────────────┐
│ Claude/Sonnet ▾    ● working     [■ Stop]   │  ← header row
├─────────────────────────────────────────────┤
│ Type a message...                      [↑]  │  ← textarea + send
└─────────────────────────────────────────────┘
```

### 8.2 Elements

| Element          | Behavior                                          |
|------------------|---------------------------------------------------|
| Provider/Model   | Dropdown selector. Shows current provider + model  |
|                  | tier. Defaults to project defaults.                |
| Status badge     | Color-coded dot + state label from current agent   |
| Stop button      | Visible when agent state is `working`. Sends       |
|                  | `AgentControlCommand` with `action: "cancel"`.     |
| Textarea         | Single-line default, auto-grows to multi-line.     |
|                  | Max height: 200px (then scrolls internally).       |
| Send button      | `[↑]` icon. Disabled when agent is `working` or    |
|                  | input is empty.                                    |

### 8.3 States

| Agent State      | Input Behavior                                     |
|------------------|----------------------------------------------------|
| `idle`           | Input enabled. Send button active. No stop button. |
| `working`        | Input disabled (grayed out). Stop button visible.  |
| `input_required` | Input enabled with attention styling (yellow       |
|                  | border). Placeholder: "Agent needs input..."       |
| `completed`      | Input enabled. Status shows "completed".           |
| `failed`         | Input enabled. Status shows "failed" in red.       |

### 8.4 Keyboard

- `Enter`: send message (when input focused and not empty)
- `Shift+Enter`: newline in textarea
- `Ctrl+Enter`: send message (always, regardless of cursor position)

---

## 9. Status Bar

### 9.1 Layout

Full-width bar at the bottom of the application window:

```text
┌──────────────────────────────────────────────────────┐
│ ● Connected  |  3 threads · 2 active  |  ♥ 1.2s     │
└──────────────────────────────────────────────────────┘
```

### 9.2 Sections

| Section (left)     | Content                                        |
|--------------------|------------------------------------------------|
| Connection status  | Dot + label: Connected / Reconnecting / Error  |

| Section (center)   | Content                                        |
|--------------------|------------------------------------------------|
| Thread count       | Total threads · active (working) count         |

| Section (right)    | Content                                        |
|--------------------|------------------------------------------------|
| Heartbeat          | `♥` + time since last heartbeat                |

### 9.3 Connection States

| WebSocket State  | Dot Color | Label                    | Bar Style      |
|------------------|-----------|--------------------------|----------------|
| Connected        | Green     | "Connected"              | Default        |
| Reconnecting     | Yellow    | "Reconnecting (Ns)..."  | Yellow bg tint |
| Disconnected     | Red       | "Disconnected"           | Red bg tint    |

---

## 10. New Thread Creation

### 10.1 Flow

1. User clicks `[+ New Thread]` button in sidebar
2. New thread entry appears immediately in sidebar (untitled, pending)
3. Stream area clears to empty state
4. Input bar is focused with cursor ready
5. User types first message
6. User sends (Enter or click send)
7. `POST /threads` fires with `initial_message` from input and
   selected `provider`/`model` from input bar dropdown
8. Thread starts streaming events

**No dialog. No form. Inline creation only.**

### 10.2 Empty State

When a new thread has no messages yet:

```text
┌──────────────────────────────────────┐
│                                      │
│                                      │
│         Start a conversation         │
│     Type a message below to begin    │
│                                      │
│                                      │
├──────────────────────────────────────┤
│ [input bar focused]                  │
└──────────────────────────────────────┘
```

---

## 11. Theme

### 11.1 Strategy

Use shadcn-svelte's built-in theming system (`mode-watcher` or equivalent
Svelte 5 theme provider). **No custom color values** — rely entirely on
the shadcn CSS variable system.

### 11.2 Modes

Three modes are mandatory:

| Mode   | Behavior                                        |
|--------|-------------------------------------------------|
| Dark   | Default. Dark backgrounds, light text.          |
| Light  | Light backgrounds, dark text.                   |
| System | Follows OS `prefers-color-scheme` media query.  |

### 11.3 Toggle Location

Theme toggle button in the sidebar header (sun/moon icon). Persisted to
`localStorage`.

---

## 12. Keyboard Shortcuts

| Shortcut        | Action                          |
|-----------------|---------------------------------|
| `Ctrl+N`        | Create new thread               |
| `Ctrl+I`        | Toggle inspector panel          |
| `Ctrl+K`        | Open command palette            |
| `Escape`        | Close inspector or modal        |
| `Ctrl+Enter`    | Send message                    |
| `Ctrl+.`        | Toggle sidebar                  |
| `Ctrl+1..9`     | Switch to thread N              |
| `Ctrl+Shift+T`  | Reopen last closed thread       |

All shortcuts are discoverable via the `Ctrl+K` command palette.

---

## 13. Loading & Empty States

### 13.1 Initial Load

- App shows skeleton placeholders while WebSocket connects
- Sidebar shows thread list skeletons
- Status bar shows "Connecting..."

### 13.2 No Threads

- Sidebar thread list shows: "No threads yet"
- Stream area shows centered prompt: "Create a new thread to get started"
- `[+ New Thread]` button is prominent

### 13.3 Disconnected

- All interactive elements remain visible but grayed out
- Status bar turns red/yellow with reconnection timer
- Toast notification: "Connection lost. Reconnecting..."
- On reconnect: state snapshots fetched, UI reconciled

---

## 14. Component-to-shadcn Mapping

| UI Element         | shadcn Component(s)                    |
|--------------------|----------------------------------------|
| Chat bubbles       | `Card` (custom styled)                 |
| Tool call cards    | `Card` + `Badge`                       |
| Thought blocks     | `Collapsible` + `Card`                 |
| Artifact cards     | `Card` + `Badge`                       |
| Permission modal   | `AlertDialog` (non-dismissible)        |
| Inspector panel    | `Sheet` (side) or custom panel         |
| Inspector tabs     | `Tabs`                                 |
| Input bar          | `Textarea` + `Button` + `Select`       |
| Sidebar            | `ScrollArea` + custom layout           |
| Status bar         | Custom flex layout + `Badge`           |
| Plan checklist     | Custom list + `Badge` + `Checkbox`     |
| Error alerts       | `Alert` (destructive variant)          |
| Theme toggle       | `Button` (icon variant)                |
| Command palette    | `Command` (cmdk)                       |
| New messages badge | `Button` (floating, absolute position) |
| Thread list items  | Custom `Button` variant                |
| Team status items  | Custom flex row + `Badge`              |

---

## 15. Event → Store → UI Data Flow

```text
WebSocket Event
    │
    ▼
Store.applyEvent(event)     ← dispatches on event.type
    │
    ├─► agent-state store   ← per-thread: messages, tool calls, artifacts, plan
    ├─► team-state store    ← agents list, active threads
    └─► permission-queue    ← FIFO queue of permission requests
         │
         ▼
    Svelte 5 Runes ($state/$derived)
         │
         ▼
    Component re-render (fine-grained, per-field)
```

On reconnect:
1. `GET /threads/{id}/state` → `ThreadStateSnapshot`
2. `agentState.restoreFromSnapshot(snapshot)`
3. `SubscribeCommand` sent for all thread IDs
4. Incoming events with `sequence <= last_sequence` discarded
