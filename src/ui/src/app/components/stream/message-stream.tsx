import { useRef, useEffect, useState, useMemo, useCallback } from 'react';
import {
  ChevronDown, Search, Check,
  FileText, X, Loader2,
} from 'lucide-react';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { UserBubble, AgentBubble } from './message-bubble';
import { ThoughtBlock } from './thought-block';
import { ToolCallCard } from './tool-call-card';
import { ArtifactCard } from './artifact-card';
import { PlanUpdateCard } from './plan-update-card';
import { ErrorAlert } from './error-alert';
import { PermissionCard } from './permission-card';
import { Popover, PopoverContent, PopoverTrigger } from '../ui/popover';
import type { StreamEvent, InspectorTarget, TeamPreset, AgentSummary, ContextDocument, AgentLifecycleState, PermissionRequest } from '../../data/types';
import { getAgentColor } from '../../utils/agent-colors';

// ── Working Indicator (spinning circle) ──

function WorkingIndicator() {
  return (
    <div className="px-4 py-3" role="status" aria-label="Team is working">
      <div className="flex items-center gap-3 px-4 py-2.5">
        <Loader2 className="w-4 h-4 text-status-info animate-spin" />
        <span className="text-[0.75rem] text-muted-foreground">
          Team is working&hellip;
        </span>
      </div>
    </div>
  );
}

// ── Grouping logic ──
// Consecutive events from the same agent are grouped into a "capsule".
// User messages, errors, and events without an agent break the group.

type AgentGroup = {
  kind: 'agent';
  agentName: string;
  agentId: string;
  events: StreamEvent[];
};

type StandaloneItem = {
  kind: 'standalone';
  event: StreamEvent;
};

type GroupedItem = AgentGroup | StandaloneItem;

function getAgentInfo(event: StreamEvent): { agentId: string; agentName: string } | null {
  if (event.type === 'user_message' || event.type === 'error') return null;
  if ('agent_id' in event && event.agent_id && 'agent_name' in event) {
    return { agentId: event.agent_id, agentName: (event as any).agent_name };
  }
  return null;
}

function groupEvents(events: StreamEvent[]): GroupedItem[] {
  const groups: GroupedItem[] = [];
  let currentGroup: AgentGroup | null = null;

  for (const event of events) {
    const agentInfo = getAgentInfo(event);

    if (agentInfo) {
      if (currentGroup && currentGroup.agentId === agentInfo.agentId) {
        currentGroup.events.push(event);
      } else {
        if (currentGroup) groups.push(currentGroup);
        currentGroup = {
          kind: 'agent',
          agentName: agentInfo.agentName,
          agentId: agentInfo.agentId,
          events: [event],
        };
      }
    } else {
      if (currentGroup) {
        groups.push(currentGroup);
        currentGroup = null;
      }
      groups.push({ kind: 'standalone', event });
    }
  }

  if (currentGroup) groups.push(currentGroup);

  return groups;
}

// ── Agent Capsule ──

function AgentCapsule({
  group,
  onInspect,
  isDark,
}: {
  group: AgentGroup;
  onInspect: (e: StreamEvent) => void;
  isDark?: boolean;
}) {
  const color = getAgentColor(group.agentName);
 
  return (
    <div className="px-4 py-1.5">
      <div className="flex rounded-ui border border-border/40 bg-oxide-terminal-bg overflow-hidden">
        <div className={`w-[0.1875rem] shrink-0 ${color.dot}`} />
 
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 px-4 pt-2.5 pb-1">
            <span
              className={`text-[0.6875rem] font-bold uppercase tracking-wider font-mono ${color.text}`}
            >
              {group.agentName}
            </span>
            <span className="text-[0.625rem] text-muted-foreground opacity-80 font-mono">
              {new Date(group.events[0].timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
 
          <div className="px-4 pb-3 space-y-0.5">
            {group.events.map((event) => {
              switch (event.type) {
                case 'agent_message':
                  return <AgentBubble key={event.id} event={event} isDark={isDark} />;
                case 'thought':
                  return <ThoughtBlock key={event.id} event={event} />;
                case 'tool_call':
                  return <ToolCallCard key={event.id} event={event} onInspect={() => onInspect(event)} />;
                case 'artifact':
                  return <ArtifactCard key={event.id} event={event} onInspect={() => onInspect(event)} />;
                case 'plan_update':
                  return <PlanUpdateCard key={event.id} event={event} onInspect={() => onInspect(event)} />;
                case 'agent_status':
                  return null;
                default:
                  return null;
              }
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
 
// ── Main Component ──
 
interface MessageStreamProps {
  events: StreamEvent[];
  onInspect: (target: InspectorTarget) => void;
  emptyState?: boolean;
  teamPreset?: TeamPreset;
  agents?: AgentSummary[];
  agentState?: AgentLifecycleState;
  onOpenDocument?: (doc: ContextDocument) => void;
  onToggleContext?: () => void;
  isContextOpen?: boolean;
  contextDocumentCount?: number;
  isDark?: boolean;
  /** Pending permission requests for this thread */
  pendingPermissions?: PermissionRequest[];
  onRespondPermission?: (requestId: string, optionId: string) => void;
}
 
export function MessageStream({
  events,
  onInspect,
  emptyState,
  teamPreset,
  agents = [],
  agentState,
  onOpenDocument,
  onToggleContext,
  isContextOpen,
  contextDocumentCount = 0,
  isDark,
  pendingPermissions = [],
  onRespondPermission,
}: MessageStreamProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [showNewBadge, setShowNewBadge] = useState(false);
  const [isNearBottom, setIsNearBottom] = useState(true);

  const isWorking = agentState === 'working' || agentState === 'submitted';

  const handleInspect = useCallback((e: StreamEvent) => {
    const doc: ContextDocument = {
      id: e.id,
      title: e.type === 'tool_call' ? `Tool: ${(e as any).tool_name}` : e.type === 'artifact' ? (e as any).filename : 'Event Detail',
      content: 'agent_id' in e ? `Agent: ${(e as any).agent_name}\n\n${JSON.stringify(e, null, 2)}` : JSON.stringify(e, null, 2),
      type: e.type === 'artifact' ? 'file' : 'note',
      updated_at: e.timestamp,
    };
    onOpenDocument?.(doc);
  }, [onOpenDocument]);

  // ── Filter / Search state ──
  const [selectedAgentIds, setSelectedAgentIds] = useState<Set<string>>(new Set());
  const [showThoughts, setShowThoughts] = useState(true);
  const [showToolCalls, setShowToolCalls] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (searchOpen) setTimeout(() => searchInputRef.current?.focus(), 50);
  }, [searchOpen]);

  const availableAgents = useMemo(() => {
    const map = new Map<string, string>();
    events.forEach((e) => {
      if ('agent_id' in e && e.agent_id && (e as any).agent_name) {
        map.set(e.agent_id, (e as any).agent_name);
      }
    });
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  }, [events]);

  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      if (e.type === 'user_message') {
        if (searchQuery && !e.content.toLowerCase().includes(searchQuery.toLowerCase())) return false;
        return true;
      }
      if (e.type === 'thought' && !showThoughts) return false;
      if (e.type === 'tool_call' && !showToolCalls) return false;
      if (selectedAgentIds.size > 0 && 'agent_id' in e && e.agent_id) {
        if (!selectedAgentIds.has(e.agent_id)) return false;
      }
      if (searchQuery && 'content' in e && typeof e.content === 'string') {
        if (!e.content.toLowerCase().includes(searchQuery.toLowerCase())) return false;
      }
      return true;
    });
  }, [events, selectedAgentIds, showThoughts, showToolCalls, searchQuery]);

  const groupedItems = useMemo(() => groupEvents(filteredEvents), [filteredEvents]);

  const toggleAgent = (id: string) => {
    setSelectedAgentIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const clearAllFilters = () => {
    setSelectedAgentIds(new Set());
    setShowThoughts(true);
    setShowToolCalls(true);
    setSearchQuery('');
  };

  const hasActiveFilters = selectedAgentIds.size > 0 || !showThoughts || !showToolCalls || searchQuery.length > 0;

  useEffect(() => {
    if (isNearBottom) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    } else {
      setShowNewBadge(true);
    }
  }, [filteredEvents.length, isNearBottom]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    setIsNearBottom(nearBottom);
    if (nearBottom) setShowNewBadge(false);
  };

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    setShowNewBadge(false);
    setIsNearBottom(true);
  };

  if (emptyState) {
    return (
      <div className="flex-1 flex items-center justify-center bg-oxide-sidebar-bg">
        <div className="text-center max-w-sm">
          <div className="w-12 h-12 rounded-bubble bg-muted flex items-center justify-center mx-auto mb-4">
            <FileText className="w-6 h-6 text-primary" />
          </div>
          <h3 className="text-[0.9375rem] font-medium mb-1">VaultSpec Orchestrator</h3>
          <p className="text-muted-foreground text-[0.8125rem]">
            Ready to deploy multi-agent workflows. Type a message to begin or select a team preset from the sidebar.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 relative min-h-0 flex flex-col bg-background" data-focus-section="stream">
      {/* ── Stream Toolbar ── */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-oxide-sidebar-bg sticky top-0 z-20" role="toolbar" aria-label="Stream filters">
        <div className="flex items-center gap-3">
          {/* Active filter badges */}
          {selectedAgentIds.size > 0 && (
            <div className="flex gap-1">
              {Array.from(selectedAgentIds).map(id => {
                const agent = availableAgents.find(a => a.id === id);
                const color = getAgentColor(agent?.name || id);
                return (
                  <button
                    key={id}
                    onClick={() => toggleAgent(id)}
                    aria-label={`Remove filter: ${agent?.name || id}`}
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[0.625rem] border ${color.badge} hover:opacity-70 transition-opacity`}
                  >
                    {agent?.name || id}
                    <X className="w-2.5 h-2.5" />
                  </button>
                );
              })}
            </div>
          )}
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              aria-label={`Clear search: ${searchQuery}`}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[0.625rem] border border-primary/40 bg-primary/10 text-primary hover:opacity-70 transition-opacity"
            >
              &ldquo;{searchQuery.slice(0, 16)}{searchQuery.length > 16 ? '…' : ''}&rdquo;
              <X className="w-2.5 h-2.5" />
            </button>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          {/* Plans button */}
          <Button
            variant="ghost"
            size="sm"
            className={`h-7 text-[0.6875rem] gap-1.5 px-2.5 transition-colors ${
              isContextOpen
                ? 'bg-accent text-accent-foreground border border-border'
                : 'text-muted-foreground hover:text-foreground'
            }`}
            onClick={onToggleContext}
            aria-label={`Toggle plans panel${contextDocumentCount > 0 ? `, ${contextDocumentCount} documents` : ''}`}
            aria-pressed={isContextOpen}
          >
            <FileText className="w-3 h-3" />
            Plans
            {contextDocumentCount > 0 && (
              <span className={`flex items-center justify-center min-w-[1rem] h-4 rounded-full text-[0.5625rem] font-bold px-1 ${
                isContextOpen ? 'bg-muted text-foreground' : 'bg-muted-foreground/20 text-muted-foreground'
              }`}>
                {contextDocumentCount}
              </span>
            )}
          </Button>

          {/* Search & Filter */}
          <Popover open={searchOpen} onOpenChange={setSearchOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className={`h-7 text-[0.6875rem] gap-1.5 px-2.5 transition-colors ${
                  hasActiveFilters
                    ? 'bg-accent text-accent-foreground border border-border'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <Search className="w-3 h-3" />
                Search
                {hasActiveFilters && (
                  <span className="flex items-center justify-center w-4 h-4 rounded-full bg-muted text-foreground text-[0.5625rem] font-bold">
                    {selectedAgentIds.size + (searchQuery ? 1 : 0) + (!showThoughts ? 1 : 0) + (!showToolCalls ? 1 : 0)}
                  </span>
                )}
              </Button>
            </PopoverTrigger>

            <PopoverContent
              align="end"
              className="w-80 p-0 border border-border shadow-2xl bg-background"
              sideOffset={6}
            >
              {/* Search input */}
              <div className="p-3 border-b border-border">
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground opacity-60 pointer-events-none z-10" />
                  <Input
                    ref={searchInputRef}
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search messages…"
                    className="h-8 pl-8 pr-8 text-[0.75rem] font-mono"
                    aria-label="Search messages"
                  />
                  {searchQuery && (
                    <button
                      onClick={() => setSearchQuery('')}
                      aria-label="Clear search"
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  )}
                </div>
              </div>

              {/* Agent filter — no icon in header */}
              <div className="p-3 border-b border-border">
                <span className="text-[0.625rem] font-bold uppercase tracking-wider text-muted-foreground opacity-80 mb-2 block">
                  Filter by Agent
                </span>
                {availableAgents.length === 0 ? (
                  <p className="text-[0.6875rem] text-muted-foreground italic">No agents in this thread</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {availableAgents.map((agent) => {
                      const color = getAgentColor(agent.name);
                      const isSelected = selectedAgentIds.has(agent.id);
                      return (
                        <button
                          key={agent.id}
                          onClick={() => toggleAgent(agent.id)}
                          aria-label={`Filter by agent: ${agent.name}`}
                          aria-pressed={isSelected}
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[0.6875rem] border font-mono font-medium transition-all ${color.badge} ${
                            isSelected ? 'ring-1 ring-current opacity-100' : 'opacity-70 hover:opacity-100'
                          }`}
                        >
                          {agent.name}
                          {isSelected && <Check className="w-2.5 h-2.5" />}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Visibility toggles — no icon in header */}
              <div className="p-3 border-b border-border">
                <span className="text-[0.625rem] font-bold uppercase tracking-wider text-muted-foreground opacity-80 mb-2 block">
                  Visibility
                </span>
                <div className="space-y-1.5">
                  {[
                    { label: 'Agent Thoughts', value: showThoughts, toggle: () => setShowThoughts(v => !v) },
                    { label: 'Tool Calls', value: showToolCalls, toggle: () => setShowToolCalls(v => !v) },
                  ].map(({ label, value, toggle }) => (
                    <button
                      key={label}
                      onClick={toggle}
                      role="switch"
                      aria-checked={value}
                      aria-label={`Toggle ${label}`}
                      className="w-full flex items-center justify-between px-2 py-1.5 rounded-control hover:bg-muted/40 transition-colors"
                    >
                      <span className="text-[0.75rem] text-foreground/80">{label}</span>
                      <div className={`w-8 h-4 rounded-full transition-colors relative ${value ? 'bg-primary' : 'bg-muted-foreground/30'}`}>
                        <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-background shadow-sm transition-transform ${value ? 'translate-x-4' : 'translate-x-0.5'}`} />
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Footer */}
              <div className="p-2 flex items-center justify-between">
                <span className="text-[0.625rem] text-muted-foreground px-1">
                  {filteredEvents.length} / {events.length} messages
                </span>
                {hasActiveFilters && (
                  <button
                    onClick={clearAllFilters}
                    aria-label="Clear all filters"
                    className="text-[0.6875rem] text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded hover:bg-muted/40"
                  >
                    Clear all
                  </button>
                )}
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </div>

      {/* ── Message list — grouped ── */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto"
        onScroll={handleScroll}
      >
        <div className="py-6 space-y-1">
          {groupedItems.map((item) => {
            if (item.kind === 'agent') {
              const key = `grp-${item.events[0].id}`;
              return (
                <AgentCapsule
                  key={key}
                  group={item}
                  onInspect={handleInspect}
                  isDark={isDark}
                />
              );
            }
            const event = item.event;
            switch (event.type) {
              case 'user_message':
                return <UserBubble key={event.id} event={event} isDark={isDark} />;
              case 'error':
                return <ErrorAlert key={event.id} event={event} />;
              default:
                return null;
            }
          })}

          {/* Working indicator — Claude-style, at bottom of stream */}
          {isWorking && <WorkingIndicator />}

          {/* Inline permission requests — rendered in-thread, not as a modal */}
          {pendingPermissions.length > 0 && onRespondPermission && (
            pendingPermissions.map((perm) => (
              <PermissionCard
                key={perm.id}
                request={perm}
                onRespond={onRespondPermission}
                queueLength={pendingPermissions.length}
              />
            ))
          )}

          <div ref={bottomRef} className="h-4" />
        </div>
      </div>

      {/* New Messages badge */}
      {showNewBadge && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10">
          <Button
            variant="secondary"
            size="sm"
            className="shadow-xl gap-1 text-[0.75rem] h-8 rounded-full border border-border"
            onClick={scrollToBottom}
            aria-label="Scroll to new messages"
          >
            <ChevronDown className="w-3.5 h-3.5" />
            New messages
          </Button>
        </div>
      )}
    </div>
  );
}