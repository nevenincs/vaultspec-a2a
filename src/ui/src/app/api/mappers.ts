/**
 * Wire-type → Frontend-type mappers.
 *
 * The backend (wire-types.ts) and UI components (types.ts) use slightly
 * different shapes and enum values. These mappers handle the translation.
 */

import type { components } from '../data/wire-types';

type WireThreadSummary = components['schemas']['ThreadSummary'];
type WireAgentSummary = components['schemas']['AgentSummary'];
type AgentStatusEntry = components['schemas']['AgentStatusEntry'];
type TeamPresetSummary = components['schemas']['TeamPresetSummary'];
type PermissionRequestEvent = components['schemas']['PermissionRequestEvent'];
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
    team_preset: wire.team_preset ?? undefined,
    created_at: wire.created_at,
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

export function mapPermissionRequest(wire: PermissionRequestEvent): PermissionRequest {
  return {
    id: wire.request_id,
    thread_id: wire.thread_id,
    agent_id: wire.agent_id ?? '',
    agent_name: wire.agent_id ?? 'Unknown',
    tool_name: wire.tool_call ?? '',
    tool_kind: wire.tool_kind ? mapToolKind(wire.tool_kind) : 'other',
    message: wire.description,
    options: wire.options.map((o) => ({
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
