/**
 * WebSocket protocol types — auto-generated from Pydantic models.
 *
 * DO NOT EDIT MANUALLY. Regenerate with:
 *   uv run python scripts/export_ws_schema.py
 *   uv run python scripts/generate_ws_types.py
 *
 * Source: TypeAdapter(ServerEvent).json_schema() and
 *         TypeAdapter(ClientMessage).json_schema()
 */

// ======================================================================
// Server-to-client events
// ======================================================================

/** Observable agent states exposed to the frontend. */
export type AgentLifecycleState = "submitted" | "idle" | "working" | "input_required" | "auth_required" | "completed" | "failed" | "cancelled";

/** LLM capability levels. */
export type Model = "low" | "mid" | "high" | "max";

/** User permission response options (mirrors ACP PermissionOption.kind). */
export type PermissionOptionKind = "allow_once" | "allow_always" | "reject_once" | "reject_always";

/** Supported LLM providers. */
export type Provider = "claude" | "gemini" | "mock" | "openai" | "zhipu";

/** Lifecycle states for a single tool invocation. */
export type ToolCallStatus = "pending" | "in_progress" | "completed" | "failed";

/** ACP tool categories (mirrors agentclientprotocol.com schema). */
export type ToolKind = "read" | "edit" | "delete" | "move" | "search" | "execute" | "think" | "fetch" | "switch_mode" | "other";

/** Agent lifecycle state transition. */
export interface AgentStatusEvent {
  type: "agent_status";
  thread_id: string;
  agent_id?: string | null;
  timestamp: string;
  sequence: number;
  metadata?: Record<string, unknown> | null;
  state: AgentLifecycleState;
  node_name: string;
  detail?: string | null;
}

/** Lightweight agent descriptor for team status broadcasts. */
export interface AgentSummary {
  agent_id: string;
  node_name: string;
  state: AgentLifecycleState;
  provider?: Provider | null;
  model?: Model | null;
  role?: string;
  display_name?: string;
  description?: string;
}

/** Streaming file artifact content. */
export interface ArtifactUpdateEvent {
  type: "artifact_update";
  thread_id: string;
  agent_id?: string | null;
  timestamp: string;
  sequence: number;
  metadata?: Record<string, unknown> | null;
  artifact_id: string;
  filename: string;
  content: string;
  append?: boolean;
  last_chunk?: boolean;
}

/** Sent once on WebSocket open; connection-scoped, not thread-scoped. */
export interface ConnectedEvent {
  type: "connected";
  client_id: string;
  server_version: string;
  active_threads?: string[];
  metadata?: Record<string, unknown> | null;
}

/** Server-side error notification. */
export interface ErrorEvent {
  type: "error";
  thread_id: string;
  agent_id?: string | null;
  timestamp: string;
  sequence: number;
  metadata?: Record<string, unknown> | null;
  code: string;
  message: string;
  recoverable?: boolean;
}

/** Periodic keepalive; connection-scoped, not thread-scoped. */
export interface HeartbeatEvent {
  type: "heartbeat";
  timestamp: string;
  server_uptime_seconds: number;
  metadata?: Record<string, unknown> | null;
}

/** Streaming agent message token. */
export interface MessageChunkEvent {
  type: "message_chunk";
  thread_id: string;
  agent_id?: string | null;
  timestamp: string;
  sequence: number;
  metadata?: Record<string, unknown> | null;
  content: string;
  message_id: string;
  finish_reason?: string | null;
}

/** A selectable option in a permission request. */
export interface PermissionOption {
  option_id: string;
  name: string;
  kind: PermissionOptionKind;
}

/** Agent is requesting user permission to proceed. */
export interface PermissionRequestEvent {
  type: "permission_request";
  thread_id: string;
  agent_id?: string | null;
  timestamp: string;
  sequence: number;
  metadata?: Record<string, unknown> | null;
  request_id: string;
  description: string;
  options: PermissionOption[];
  tool_call?: string | null;
  tool_kind?: ToolKind | null;
}

export interface PlanEntry {
  content: string;
  status?: string;
  priority?: string;
}

/** Full plan state replacement. */
export interface PlanUpdateEvent {
  type: "plan_update";
  thread_id: string;
  agent_id?: string | null;
  timestamp: string;
  sequence: number;
  metadata?: Record<string, unknown> | null;
  entries: PlanEntry[];
}

/** Team-wide agent status broadcast. */
export interface TeamStatusEvent {
  type: "team_status";
  thread_id: string;
  agent_id?: string | null;
  timestamp: string;
  sequence: number;
  metadata?: Record<string, unknown> | null;
  agents: AgentSummary[];
  active_thread_ids?: string[];
}

/** Streaming agent thought/reasoning token. */
export interface ThoughtChunkEvent {
  type: "thought_chunk";
  thread_id: string;
  agent_id?: string | null;
  timestamp: string;
  sequence: number;
  metadata?: Record<string, unknown> | null;
  content: string;
  message_id: string;
}

/** Diff content block within a tool call. */
export interface ToolCallContentDiff {
  content_type: "diff";
  path: string;
  old_text?: string | null;
  new_text: string;
}

/** Terminal output content block within a tool call. */
export interface ToolCallContentTerminal {
  content_type: "terminal";
  terminal_id: string;
}

/** Plain text content block within a tool call. */
export interface ToolCallContentText {
  content_type: "text";
  text: string;
}

/** File location associated with a tool call. */
export interface ToolCallLocation {
  path: string;
  line?: number | null;
}

/** A new tool invocation has begun. */
export interface ToolCallStartEvent {
  type: "tool_call_start";
  thread_id: string;
  agent_id?: string | null;
  timestamp: string;
  sequence: number;
  metadata?: Record<string, unknown> | null;
  tool_call_id: string;
  title: string;
  kind: ToolKind;
  status?: ToolCallStatus;
  locations?: ToolCallLocation[];
  content?: (ToolCallContentText | ToolCallContentDiff | ToolCallContentTerminal)[];
}

/** Incremental update to an in-progress tool call (merge semantics). */
export interface ToolCallUpdateEvent {
  type: "tool_call_update";
  thread_id: string;
  agent_id?: string | null;
  timestamp: string;
  sequence: number;
  metadata?: Record<string, unknown> | null;
  tool_call_id: string;
  title?: string | null;
  kind?: ToolKind | null;
  status?: ToolCallStatus | null;
  locations?: ToolCallLocation[] | null;
  content?: (ToolCallContentText | ToolCallContentDiff | ToolCallContentTerminal)[] | null;
}

/** Discriminated union on "type" field. */
export type ServerEvent =
  | AgentStatusEvent
  | MessageChunkEvent
  | ThoughtChunkEvent
  | ToolCallStartEvent
  | ToolCallUpdateEvent
  | PermissionRequestEvent
  | ArtifactUpdateEvent
  | PlanUpdateEvent
  | TeamStatusEvent
  | ErrorEvent
  | ConnectedEvent
  | HeartbeatEvent;

// ======================================================================
// Client-to-server commands
// ======================================================================

/** Actions a user can issue to control a running agent. */
export type AgentControlAction = "pause" | "resume" | "terminate";

/** Issue a control action (pause/resume/terminate) to an agent. */
export interface AgentControlCommand {
  type: "agent_control";
  request_id?: string | null;
  thread_id: string;
  agent_id: string;
  action: AgentControlAction;
  option_id?: string | null;
}

/** Respond to a permission request via WebSocket. */
export interface PermissionResponseCommand {
  type: "permission_response";
  request_id: string;
  option_id: string;
}

/** Client keepalive ping. */
export interface PingCommand {
  type: "ping";
  request_id?: string | null;
}

/** Send a user message into a thread. */
export interface SendMessageCommand {
  type: "send_message";
  request_id?: string | null;
  thread_id: string;
  content: string;
  agent_id?: string | null;
}

/** Subscribe to real-time events for one or more threads. */
export interface SubscribeCommand {
  type: "subscribe";
  request_id?: string | null;
  thread_ids: string[];
}

/** Unsubscribe from real-time events for one or more threads. */
export interface UnsubscribeCommand {
  type: "unsubscribe";
  request_id?: string | null;
  thread_ids: string[];
}

/** Discriminated union on "type" field. */
export type ClientMessage =
  | SubscribeCommand
  | UnsubscribeCommand
  | SendMessageCommand
  | AgentControlCommand
  | PermissionResponseCommand
  | PingCommand;
