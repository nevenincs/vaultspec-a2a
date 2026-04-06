/**
 * Frontend presentation types.
 *
 * These are distinct from wire types (wire-types.ts). Mappers in
 * api/mappers.ts translate wire → frontend shapes. Components and
 * store slices consume only these types.
 */

// ---------------------------------------------------------------------------
// Enums / literal unions
// ---------------------------------------------------------------------------

export type AgentLifecycleState =
  | 'submitted'
  | 'idle'
  | 'working'
  | 'input_required'
  | 'auth_required'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type ToolKind =
  | 'read'
  | 'edit'
  | 'delete'
  | 'move'
  | 'search'
  | 'execute'
  | 'think'
  | 'fetch'
  | 'switch_mode'
  | 'other';

export type ToolCallStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

export type ThreadStatus =
  | 'submitted'
  | 'running'
  | 'input_required'
  | 'cancelling'
  | 'cancelled'
  | 'completed'
  | 'failed'
  | 'archived'
  | 'repair_needed'
  | 'reconciling';

export type RepairStatus =
  | 'healthy'
  | 'paused_resumable'
  | 'cancel_pending'
  | 'replay_gap'
  | 'checkpoint_unavailable'
  | 'needs_reconciliation'
  | 'operator_intervention_required';

export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'superseded';

export type PlanEntryStatus = 'pending' | 'in_progress' | 'completed';

export type PlanEntryPriority = 'high' | 'medium' | 'low';

export type ConnectionState = 'connected' | 'reconnecting' | 'disconnected';

export type ThemeMode = 'light' | 'dark' | 'system';

// ---------------------------------------------------------------------------
// Domain models (mapped from wire types)
// ---------------------------------------------------------------------------

export interface ThreadSummary {
  thread_id: string;
  title: string;
  status: ThreadStatus;
  agent_state: AgentLifecycleState;
  team_preset: string | null;
  created_at: string;
  updated_at: string;
  nickname: string | null;
  feature_tag: string | null;
  source_branch: string | null;
  callee: string | null;
  repair_status: RepairStatus | null;
  execution_readiness: RepairStatus | null;
  approval_status: ApprovalStatus | null;
  approval_request_id: string | null;
}

export interface AgentSummary {
  agent_id: string;
  node_name: string;
  state: AgentLifecycleState;
  provider: string | null;
  model: string | null;
  role: string;
  display_name: string;
  description: string;
}

export interface TeamPreset {
  id: string;
  name: string;
  topology: string;
  description: string;
  worker_count: number;
}

export interface PermissionRequest {
  id: string;
  thread_id: string;
  agent_id: string;
  agent_name: string;
  tool_name: string;
  tool_kind: ToolKind;
  message: string;
  options: PermissionOption[];
}

export interface PermissionOption {
  id: string;
  kind: string;
  label: string;
}

// ---------------------------------------------------------------------------
// UI state models
// ---------------------------------------------------------------------------

export interface EditorTab {
  threadId: string;
  isPinned: boolean;
}

export interface ContextDocument {
  id: string;
  title: string;
  content: string;
  type: 'file' | 'note' | 'reference';
  updated_at: string;
}

export type InspectorTarget =
  | { type: 'document'; document: ContextDocument }
  | { type: 'context_list'; documents: ContextDocument[] }
  | { type: 'tool_call'; event: ToolCallEvent }
  | { type: 'artifact'; event: ArtifactEvent }
  | { type: 'plan'; event: PlanUpdateEvent };

// ---------------------------------------------------------------------------
// Stream events (discriminated union for the timeline)
// ---------------------------------------------------------------------------

interface StreamEventBase {
  id: string;
  type: string;
  timestamp: string;
  thread_id: string;
}

export interface UserMessageEvent extends StreamEventBase {
  type: 'user_message';
  content: string;
}

export interface AgentMessageEvent extends StreamEventBase {
  type: 'agent_message';
  agent_id: string;
  agent_name: string;
  content: string;
  streaming: boolean;
}

export interface ThoughtEvent extends StreamEventBase {
  type: 'thought';
  agent_id: string;
  agent_name: string;
  content: string;
}

export interface ToolCallEvent extends StreamEventBase {
  type: 'tool_call';
  agent_id: string;
  agent_name: string;
  tool_call_id: string;
  tool_name: string;
  tool_kind: ToolKind;
  status: ToolCallStatus;
  location?: { file: string; line?: number };
  input?: string;
  output?: string;
  diff?: { old_content: string; new_content: string };
  diff_path?: string;
  terminal_id?: string;
}

export interface ArtifactEvent extends StreamEventBase {
  type: 'artifact';
  agent_id: string;
  agent_name: string;
  artifact_id: string;
  filename: string;
  content: string;
  complete: boolean;
}

export interface PlanUpdateEvent extends StreamEventBase {
  type: 'plan_update';
  agent_id: string;
  agent_name: string;
  entries: PlanEntry[];
}

export interface PlanEntry {
  id: string;
  content: string;
  status: PlanEntryStatus;
  priority: PlanEntryPriority;
}

export interface AgentStatusStreamEvent extends StreamEventBase {
  type: 'agent_status';
  agent_id: string;
  agent_name: string;
  state: AgentLifecycleState;
}

export interface ErrorStreamEvent extends StreamEventBase {
  type: 'error';
  message: string;
  code: string;
  agent_id?: string;
  recoverable?: boolean;
}

export type StreamEvent =
  | UserMessageEvent
  | AgentMessageEvent
  | ThoughtEvent
  | ToolCallEvent
  | ArtifactEvent
  | PlanUpdateEvent
  | AgentStatusStreamEvent
  | ErrorStreamEvent;
