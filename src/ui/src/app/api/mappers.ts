/**
 * Wire-type → Frontend-type mappers.
 *
 * The backend (wire-types.ts) and UI components (types.ts) use slightly
 * different shapes and enum values. These mappers handle the translation.
 */

import type {
  WireThreadSummary,
  WireAgentSummary,
  AgentStatusEntry,
  TeamPresetSummary,
  PermissionRequestEvent,
  ToolCallStatus as WireToolCallStatus,
  ToolKind as WireToolKind,
} from '../data/wire-types';
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
    agent_state: wire.agent_state ?? 'submitted',
    updated_at: wire.updated_at,
    nickname: wire.nickname ?? undefined,
    feature_tag: wire.feature_tag ?? undefined,
    source_branch: wire.source_branch ?? undefined,
    callee: wire.callee ?? undefined,
  };
}

export function mapAgentSummary(
  wire: WireAgentSummary | AgentStatusEntry,
): AgentSummary {
  return {
    agent_id: wire.agent_id,
    node_name: wire.node_name,
    state: wire.state,
  };
}

export function mapTeamPreset(wire: TeamPresetSummary): TeamPreset {
  return {
    id: wire.id,
    name: wire.display_name,
    topology: wire.topology as TeamPreset['topology'],
    agents: [],
    description: wire.description,
  };
}

export function mapPermissionRequest(wire: PermissionRequestEvent): PermissionRequest {
  return {
    id: wire.request_id,
    thread_id: wire.thread_id,
    agent_id: wire.agent_id ?? '',
    agent_name: wire.agent_id ?? '',
    tool_name: wire.tool_call ?? '',
    tool_kind: 'other',
    message: wire.description,
    options: wire.options.map((o) => ({
      id: o.option_id,
      kind: o.kind as PermissionRequest['options'][0]['kind'],
      label: o.name,
    })),
  };
}

const FRONTEND_TOOL_KINDS = new Set<string>([
  'read',
  'edit',
  'search',
  'execute',
  'browser',
  'mcp',
  'other',
]);

export function mapToolCallStatus(wire: WireToolCallStatus): ToolCallStatus {
  return wire === 'in_progress' ? 'running' : wire;
}

export function mapToolKind(wire: WireToolKind): ToolKind {
  return FRONTEND_TOOL_KINDS.has(wire) ? (wire as ToolKind) : 'other';
}
