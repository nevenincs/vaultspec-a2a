/**
 * State indicator utilities — pure functions, no visual component.
 * Returns Tailwind class strings and icon component references for
 * agent lifecycle states and tool call states.
 */

import type {
  AgentLifecycleStateStr,
  ToolCallStatusStr,
  ToolKindStr,
} from '$lib/data/types';

// ── Agent state ───────────────────────────────────────────────────────────────

export function agentStateColor(state: AgentLifecycleStateStr): string {
  switch (state) {
    case 'submitted':
      return 'text-muted-foreground';
    case 'idle':
      return 'text-status-success';
    case 'working':
      return 'text-status-info';
    case 'input_required':
      return 'text-status-warning';
    case 'auth_required':
      return 'text-status-warning';
    case 'completed':
      return 'text-status-success';
    case 'failed':
      return 'text-status-error';
    case 'cancelled':
      return 'text-muted-foreground';
  }
}

export function agentStateLabel(state: AgentLifecycleStateStr): string {
  switch (state) {
    case 'submitted':
      return 'submitted';
    case 'idle':
      return 'idle';
    case 'working':
      return 'working';
    case 'input_required':
      return 'input needed';
    case 'auth_required':
      return 'auth needed';
    case 'completed':
      return 'completed';
    case 'failed':
      return 'failed';
    case 'cancelled':
      return 'cancelled';
  }
}

/**
 * Returns a descriptor for how to render the agent state dot.
 * Components use this to render the appropriate icon/dot.
 */
export type AgentDotDescriptor =
  | { kind: 'spinner'; colorClass: string }
  | { kind: 'dot'; colorClass: string }
  | { kind: 'none' };

export function agentStateDot(state: AgentLifecycleStateStr): AgentDotDescriptor {
  switch (state) {
    case 'working':
    case 'submitted':
      return { kind: 'spinner', colorClass: 'text-status-info' };
    case 'input_required':
    case 'auth_required':
      return { kind: 'spinner', colorClass: 'text-status-warning' };
    case 'failed':
    case 'cancelled':
      return { kind: 'dot', colorClass: 'bg-status-error' };
    case 'completed':
    case 'idle':
      return { kind: 'none' };
  }
}

// ── Tool state ────────────────────────────────────────────────────────────────

export function toolStatusColor(status: ToolCallStatusStr): string {
  switch (status) {
    case 'pending':
      return 'text-muted-foreground';
    case 'in_progress':
      return 'text-status-info';
    case 'completed':
      return 'text-status-success';
    case 'failed':
      return 'text-status-error';
  }
}

/**
 * Returns the lucide icon name for a tool kind.
 * Components import the specific lucide icon by name.
 */
export function toolKindIconName(kind: ToolKindStr): string {
  switch (kind) {
    case 'read':
      return 'FileText';
    case 'edit':
      return 'FileEdit';
    case 'delete':
      return 'Trash2';
    case 'move':
      return 'FolderInput';
    case 'search':
      return 'Search';
    case 'execute':
      return 'Terminal';
    case 'think':
      return 'Brain';
    case 'fetch':
      return 'Globe';
    case 'switch_mode':
      return 'ArrowLeftRight';
    case 'other':
      return 'Wrench';
  }
}

// ── Time formatting ───────────────────────────────────────────────────────────

export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
}

export function formatRelativeTime(isoString: string): string {
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// ── Team topology ─────────────────────────────────────────────────────────────

export function topologyLabel(topology?: string): string {
  switch (topology) {
    case 'star':
      return 'Star';
    case 'pipeline':
      return 'Pipeline';
    case 'pipeline_loop':
      return 'Loop';
    default:
      return '';
  }
}
