/**
 * Wire-type → Frontend-type mappers.
 *
 * The backend (wire-types.ts) and UI components (types.ts) use slightly
 * different shapes and enum values. These mappers handle the translation.
 */

import type { components } from '../data/wire-types';
import type {
  AgentSummary as WsAgentSummary,
  PermissionRequestEvent,
  PermissionOption as WsPermissionOption,
} from '../data/ws-types';

type WireThreadSummary = components['schemas']['ThreadSummary'];
type AgentStatusEntry = components['schemas']['AgentStatusEntry'];
type TeamPresetSummary = components['schemas']['TeamPresetSummary'];
type WireToolCallStatus = components['schemas']['ToolCallStatus'];
type WireToolKind = components['schemas']['ToolKind'];

import type {
  ThreadSummary,
  AgentSummary,
  TeamPreset,
  PermissionRequest,
  ToolCallStatus,
  ToolKind,
} from '../data/types';

export function mapThreadSummary(wire: WireThreadSummary): ThreadSummary {
  return {
    thread_id: wire.thread_id,
    title: wire.title ?? 'Untitled',
    status: wire.status,
    agent_state: wire.agent_state ?? 'submitted',
    team_preset: wire.team_preset ?? null,
    created_at: wire.created_at,
    updated_at: wire.updated_at,
    nickname: wire.nickname ?? null,
    feature_tag: wire.feature_tag ?? null,
    source_branch: wire.source_branch ?? null,
    callee: wire.callee ?? null,
    repair_status: wire.repair_status ?? null,
    execution_readiness: wire.execution_readiness ?? null,
    approval_status: wire.approval_status ?? null,
    approval_request_id: wire.approval_request_id ?? null,
  };
}

export function mapAgentSummary(
  wire: WsAgentSummary | AgentStatusEntry,
): AgentSummary {
  return {
    agent_id: wire.agent_id,
    node_name: wire.node_name,
    state: wire.state,
    provider: wire.provider ?? null,
    model: wire.model ?? null,
    role: wire.role ?? '',
    display_name: wire.display_name ?? '',
    description: wire.description ?? '',
  };
}

export function mapTeamPreset(wire: TeamPresetSummary): TeamPreset {
  return {
    id: wire.id,
    name: wire.display_name,
    topology: wire.topology as TeamPreset['topology'],
    description: wire.description,
    worker_count: wire.worker_count,
  };
}

export function mapPermissionRequest(
  wire: PermissionRequestEvent,
  agentDisplayNames?: Record<string, string>,
): PermissionRequest {
  const agentId = wire.agent_id ?? '';
  return {
    id: wire.request_id,
    thread_id: wire.thread_id,
    agent_id: agentId,
    agent_name: (agentId && agentDisplayNames?.[agentId]) || agentId || 'Unknown',
    tool_name: wire.tool_call ?? '',
    tool_kind: wire.tool_kind ? mapToolKind(wire.tool_kind) : 'other',
    message: wire.description,
    options: wire.options.map((o: WsPermissionOption) => ({
      id: o.option_id,
      kind: o.kind,
      label: o.name,
    })),
  };
}

const FRONTEND_TOOL_KINDS = new Set<string>([
  'read',
  'edit',
  'delete',
  'move',
  'search',
  'execute',
  'think',
  'fetch',
  'switch_mode',
  'other',
]);

export function mapToolCallStatus(wire: WireToolCallStatus): ToolCallStatus {
  return wire as ToolCallStatus;
}

export function mapToolKind(wire: WireToolKind): ToolKind {
  return FRONTEND_TOOL_KINDS.has(wire) ? (wire as ToolKind) : 'other';
}
