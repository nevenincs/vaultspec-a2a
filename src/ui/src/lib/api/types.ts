// src/ui/src/lib/api/types.ts
// Hand-written TypeScript types mirroring lib/api/schemas/ Pydantic models.
// Will be replaced by openapi-typescript generated output when OpenAPI endpoint exists.

// ============================================================
// Enums (from lib/api/schemas/enums.py + lib/utils/enums.py)
// ============================================================

export const ServerEventType = {
  AGENT_STATUS: 'agent_status',
  MESSAGE_CHUNK: 'message_chunk',
  THOUGHT_CHUNK: 'thought_chunk',
  TOOL_CALL_START: 'tool_call_start',
  TOOL_CALL_UPDATE: 'tool_call_update',
  PERMISSION_REQUEST: 'permission_request',
  ARTIFACT_UPDATE: 'artifact_update',
  PLAN_UPDATE: 'plan_update',
  TEAM_STATUS: 'team_status',
  ERROR: 'error',
  CONNECTED: 'connected',
  HEARTBEAT: 'heartbeat',
} as const;
export type ServerEventType = (typeof ServerEventType)[keyof typeof ServerEventType];

export const ClientCommandType = {
  SUBSCRIBE: 'subscribe',
  UNSUBSCRIBE: 'unsubscribe',
  SEND_MESSAGE: 'send_message',
  PERMISSION_RESPONSE: 'permission_response',
  AGENT_CONTROL: 'agent_control',
  PING: 'ping',
} as const;
export type ClientCommandType =
  (typeof ClientCommandType)[keyof typeof ClientCommandType];

export const AgentLifecycleState = {
  SUBMITTED: 'submitted',
  IDLE: 'idle',
  WORKING: 'working',
  INPUT_REQUIRED: 'input_required',
  AUTH_REQUIRED: 'auth_required',
  COMPLETED: 'completed',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
} as const;
export type AgentLifecycleState =
  (typeof AgentLifecycleState)[keyof typeof AgentLifecycleState];

export const ToolKind = {
  READ: 'read',
  EDIT: 'edit',
  DELETE: 'delete',
  MOVE: 'move',
  SEARCH: 'search',
  EXECUTE: 'execute',
  THINK: 'think',
  FETCH: 'fetch',
  SWITCH_MODE: 'switch_mode',
  OTHER: 'other',
} as const;
export type ToolKind = (typeof ToolKind)[keyof typeof ToolKind];

export const ToolCallStatus = {
  PENDING: 'pending',
  IN_PROGRESS: 'in_progress',
  COMPLETED: 'completed',
  FAILED: 'failed',
} as const;
export type ToolCallStatus = (typeof ToolCallStatus)[keyof typeof ToolCallStatus];

export const PermissionOptionKind = {
  ALLOW_ONCE: 'allow_once',
  ALLOW_ALWAYS: 'allow_always',
  REJECT_ONCE: 'reject_once',
  REJECT_ALWAYS: 'reject_always',
} as const;
export type PermissionOptionKind =
  (typeof PermissionOptionKind)[keyof typeof PermissionOptionKind];

export const AgentControlAction = {
  PAUSE: 'pause',
  RESUME: 'resume',
  TERMINATE: 'terminate',
} as const;
export type AgentControlAction =
  (typeof AgentControlAction)[keyof typeof AgentControlAction];

export const PlanEntryStatus = {
  PENDING: 'pending',
  IN_PROGRESS: 'in_progress',
  COMPLETED: 'completed',
} as const;
export type PlanEntryStatus = (typeof PlanEntryStatus)[keyof typeof PlanEntryStatus];

export const PlanEntryPriority = {
  HIGH: 'high',
  MEDIUM: 'medium',
  LOW: 'low',
} as const;
export type PlanEntryPriority =
  (typeof PlanEntryPriority)[keyof typeof PlanEntryPriority];

export const Provider = {
  CLAUDE: 'claude',
  GEMINI: 'gemini',
  OPENAI: 'openai',
  ZHIPU: 'zhipu',
} as const;
export type Provider = (typeof Provider)[keyof typeof Provider];

export const Model = {
  LOW: 'low',
  MID: 'mid',
  HIGH: 'high',
  MAX: 'max',
} as const;
export type Model = (typeof Model)[keyof typeof Model];

// ============================================================
// Component Types (from lib/api/schemas/events.py)
// ============================================================

export interface ToolCallLocation {
  path: string;
  line: number | null;
}

export interface ToolCallContentText {
  content_type: 'text';
  text: string;
}

export interface ToolCallContentDiff {
  content_type: 'diff';
  path: string;
  old_text: string | null;
  new_text: string;
}

export interface ToolCallContentTerminal {
  content_type: 'terminal';
  terminal_id: string;
}

export type ToolCallContent =
  | ToolCallContentText
  | ToolCallContentDiff
  | ToolCallContentTerminal;

export interface PlanEntry {
  content: string;
  status: PlanEntryStatus;
  priority: PlanEntryPriority;
}

export interface PermissionOption {
  option_id: string;
  name: string;
  kind: PermissionOptionKind;
}

export interface AgentSummary {
  agent_id: string;
  node_name: string;
  state: AgentLifecycleState;
  provider: Provider;
  model: Model;
}

// ============================================================
// Base Envelope Types (from lib/api/schemas/base.py)
// ============================================================

export interface EventEnvelope {
  type: ServerEventType;
  thread_id: string;
  agent_id: string | null;
  timestamp: string; // ISO 8601 datetime string
  sequence: number;
  metadata: Record<string, unknown> | null;
}

export interface ClientCommand {
  type: ClientCommandType;
  request_id: string | null;
}

// ============================================================
// Server Event Types (from lib/api/schemas/events.py)
// ============================================================

// Thread-scoped events (extend EventEnvelope)

export interface AgentStatusEvent extends EventEnvelope {
  type: 'agent_status';
  state: AgentLifecycleState;
  node_name: string;
  detail: string | null;
}

export interface MessageChunkEvent extends EventEnvelope {
  type: 'message_chunk';
  content: string;
  message_id: string;
  finish_reason: string | null;
}

export interface ThoughtChunkEvent extends EventEnvelope {
  type: 'thought_chunk';
  content: string;
  message_id: string;
}

export interface ToolCallStartEvent extends EventEnvelope {
  type: 'tool_call_start';
  tool_call_id: string;
  title: string;
  kind: ToolKind;
  status: ToolCallStatus;
  locations: ToolCallLocation[];
  content: ToolCallContent[];
}

export interface ToolCallUpdateEvent extends EventEnvelope {
  type: 'tool_call_update';
  tool_call_id: string;
  title: string | null;
  kind: ToolKind | null;
  status: ToolCallStatus | null;
  locations: ToolCallLocation[] | null;
  content: ToolCallContent[] | null;
}

export interface PermissionRequestEvent extends EventEnvelope {
  type: 'permission_request';
  request_id: string;
  description: string;
  options: PermissionOption[];
  tool_call: string | null;
}

export interface ArtifactUpdateEvent extends EventEnvelope {
  type: 'artifact_update';
  artifact_id: string;
  filename: string;
  content: string;
  append: boolean;
  last_chunk: boolean;
}

export interface PlanUpdateEvent extends EventEnvelope {
  type: 'plan_update';
  entries: PlanEntry[];
}

export interface TeamStatusEvent extends EventEnvelope {
  type: 'team_status';
  agents: AgentSummary[];
  active_thread_ids: string[];
}

export interface ErrorEvent extends EventEnvelope {
  type: 'error';
  code: string;
  message: string;
  recoverable: boolean;
}

// Connection-scoped events (standalone, no EventEnvelope)

export interface ConnectedEvent {
  type: 'connected';
  client_id: string;
  server_version: string;
  active_threads: string[];
  metadata: Record<string, unknown> | null;
}

export interface HeartbeatEvent {
  type: 'heartbeat';
  timestamp: string; // ISO 8601
  server_uptime_seconds: number;
  metadata: Record<string, unknown> | null;
}

// Discriminated union of all server events
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

// ============================================================
// Client Command Types (from lib/api/schemas/commands.py)
// ============================================================

export interface SubscribeCommand extends ClientCommand {
  type: 'subscribe';
  thread_ids: string[];
}

export interface UnsubscribeCommand extends ClientCommand {
  type: 'unsubscribe';
  thread_ids: string[];
}

export interface SendMessageCommand extends ClientCommand {
  type: 'send_message';
  thread_id: string;
  content: string;
  agent_id: string | null;
}

export interface AgentControlCommand extends ClientCommand {
  type: 'agent_control';
  thread_id: string;
  agent_id: string;
  action: AgentControlAction;
}

export interface PermissionResponseCommand extends ClientCommand {
  type: 'permission_response';
  request_id: string;
  option_id: string;
}

export interface PingCommand extends ClientCommand {
  type: 'ping';
}

// Discriminated union of all client commands
export type ClientMessage =
  | SubscribeCommand
  | UnsubscribeCommand
  | SendMessageCommand
  | AgentControlCommand
  | PermissionResponseCommand
  | PingCommand;

// ============================================================
// REST Models (from lib/api/schemas/rest.py)
// ============================================================

export interface CreateThreadRequest {
  title: string | null;
  initial_message: string;
  provider: Provider | null;
  model: Model | null;
}

export interface CreateThreadResponse {
  thread_id: string;
  status: string;
}

export interface SendMessageRequest {
  content: string;
  agent_id: string | null;
}

export interface ThreadSummary {
  thread_id: string;
  title: string | null;
  status: string;
  agent_state: AgentLifecycleState | null;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}

export interface ThreadListResponse {
  threads: ThreadSummary[];
  total: number;
}

export interface AgentStatusEntry {
  agent_id: string;
  node_name: string;
  state: AgentLifecycleState;
  provider: Provider;
  model: Model;
}

export interface PendingPermission {
  request_id: string;
  thread_id: string;
  description: string;
}

export interface TeamStatusResponse {
  agents: AgentStatusEntry[];
  active_threads: string[];
  pending_permissions: PendingPermission[];
}

export interface PermissionResponseRequest {
  option_id: string;
  kind: PermissionOptionKind | null;
}

export interface PermissionResponseResult {
  request_id: string;
  accepted: boolean;
  thread_id: string;
}

// ============================================================
// Snapshot Models (from lib/api/schemas/snapshots.py)
// ============================================================

export interface MessageSnapshot {
  message_id: string;
  role: string;
  content: string;
  agent_id: string | null;
  timestamp: string; // ISO 8601
}

export interface ToolCallSnapshot {
  tool_call_id: string;
  title: string;
  kind: ToolKind;
  status: ToolCallStatus;
  locations: ToolCallLocation[];
  content: ToolCallContent[];
}

export interface ArtifactSnapshot {
  artifact_id: string;
  filename: string;
  content: string;
  complete: boolean;
}

export interface PermissionSnapshot {
  request_id: string;
  description: string;
  options: PermissionOptionSnapshot[];
  tool_call: string | null;
}

export interface PermissionOptionSnapshot {
  option_id: string;
  name: string;
  kind: PermissionOptionKind;
}

export interface AgentSnapshot {
  agent_id: string;
  node_name: string;
  state: AgentLifecycleState;
  provider: Provider;
  model: Model;
}

export interface ThreadStateSnapshot {
  thread_id: string;
  status: string;
  messages: MessageSnapshot[];
  tool_calls: ToolCallSnapshot[];
  pending_permissions: PermissionSnapshot[];
  artifacts: ArtifactSnapshot[];
  plan: PlanEntry[];
  agents: AgentSnapshot[];
  last_sequence: number;
  checkpoint_id: string | null;
}
