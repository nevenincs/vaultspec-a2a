import type { AgentLifecycleState, ToolCallStatus, ToolKind } from '../../data/types';
import {
  Loader2,
  FileText,
  FileEdit,
  Search,
  Terminal,
  Globe,
  Plug,
  Wrench,
} from 'lucide-react';

export function agentStateColor(state: AgentLifecycleState): string {
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

export function agentStateDot(state: AgentLifecycleState) {
  switch (state) {
    case 'working':
    case 'submitted':
      return <Loader2 className="text-status-info h-3.5 w-3.5 animate-spin" />;
    case 'input_required':
    case 'auth_required':
      return <Loader2 className="text-status-warning h-3.5 w-3.5 animate-spin" />;
    case 'failed':
    case 'cancelled':
      return <span className="bg-status-error h-2.5 w-2.5 rounded-full" />;
    case 'completed':
    case 'idle':
      return null;
  }
}

export function agentStateLabel(state: AgentLifecycleState): string {
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

export function toolStatusColor(status: ToolCallStatus): string {
  switch (status) {
    case 'pending':
      return 'text-muted-foreground';
    case 'running':
      return 'text-status-info';
    case 'completed':
      return 'text-status-success';
    case 'failed':
      return 'text-status-error';
  }
}

export function toolKindIcon(kind: ToolKind, className = 'w-4 h-4') {
  switch (kind) {
    case 'read':
      return <FileText className={className} />;
    case 'edit':
      return <FileEdit className={className} />;
    case 'search':
      return <Search className={className} />;
    case 'execute':
      return <Terminal className={className} />;
    case 'browser':
      return <Globe className={className} />;
    case 'mcp':
      return <Plug className={className} />;
    case 'other':
      return <Wrench className={className} />;
  }
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
