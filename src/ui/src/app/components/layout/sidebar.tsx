import {
  Plus, PanelLeftClose, PanelLeft, Sun, Moon, Monitor,
  Settings, Search, X, GitBranch, ShieldAlert,
} from 'lucide-react';
import { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import type { MutableRefObject } from 'react';
import { useStore } from 'zustand';
import { useShallow } from 'zustand/react/shallow';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { ScrollArea } from '../ui/scroll-area';
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from '../ui/tooltip';
import { agentStateDot } from './state-indicators';
import { ShaderBackground } from '../ui/shader-background';
import { appStore } from '../../store/app-store';
import type { ThreadSummary, TeamTopology, AgentSummary } from '../../data/types';

interface SidebarProps {
  threads: ThreadSummary[];
  activeTabId: string | null;
  openTransient: (threadId: string) => void;
  openPinned: (threadId: string) => void;
  clearActiveTab: () => void;
  /** Agent summaries for tooltip team composition display */
  agents?: AgentSummary[];
  /** Set of thread IDs that have pending permission requests */
  threadsWithPermissions?: Set<string>;
  /** Ref callback exposed so AppShell can trigger sidebar search via Ctrl+K */
  onFocusSearchRef?: MutableRefObject<(() => void) | null>;
}

/** Human-readable topology label */
function topologyLabel(topology?: TeamTopology): string {
  switch (topology) {
    case 'star': return 'Star';
    case 'pipeline': return 'Pipeline';
    case 'pipeline_loop': return 'Loop';
    default: return '';
  }
}

/** Relative time label */
function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
}

const MIN_WIDTH = 180;
const MAX_WIDTH = 420;

export function Sidebar({
  threads,
  activeTabId,
  openTransient,
  openPinned,
  clearActiveTab,
  agents = [],
  threadsWithPermissions = new Set(),
  onFocusSearchRef,
}: SidebarProps) {
  const {
    sidebarCollapsed,
    toggleSidebar,
    themeMode,
    setThemeMode,
    sidebarWidth,
    setSidebarWidth,
  } = useStore(
    appStore,
    useShallow(s => ({
      sidebarCollapsed: s.sidebarCollapsed,
      toggleSidebar: s.toggleSidebar,
      themeMode: s.themeMode,
      setThemeMode: s.setThemeMode,
      sidebarWidth: s.sidebarWidth,
      setSidebarWidth: s.setSidebarWidth,
    })),
  );

  const [searchOpen, setSearchOpen] = useState(false);
  const [taskFilter, setTaskFilter] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const isResizing = useRef(false);

  useEffect(() => {
    if (searchOpen) setTimeout(() => searchRef.current?.focus(), 50);
    else setTaskFilter('');
  }, [searchOpen]);

  // Register Ctrl+K handler for parent
  useEffect(() => {
    if (onFocusSearchRef) {
      onFocusSearchRef.current = () => {
        setSearchOpen(true);
      };
    }
    return () => {
      if (onFocusSearchRef) onFocusSearchRef.current = null;
    };
  }, [onFocusSearchRef]);

  const filteredThreads = useMemo(() => {
    if (!taskFilter) return threads;
    const q = taskFilter.toLowerCase();
    return threads.filter(t => {
      const searchable = [
        t.nickname,
        t.title,
        t.feature_tag,
        t.source_branch,
        t.source_repo,
      ].filter(Boolean).join(' ').toLowerCase();
      return searchable.includes(q);
    });
  }, [threads, taskFilter]);

  // Drag-to-resize handler
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isResizing.current = true;
      const startX = e.clientX;
      const startWidth = sidebarWidth;

      const onMouseMove = (ev: MouseEvent) => {
        if (!isResizing.current) return;
        const newWidth = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, startWidth + (ev.clientX - startX)));
        setSidebarWidth(newWidth);
      };

      const onMouseUp = () => {
        isResizing.current = false;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
      };

      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    },
    [sidebarWidth, setSidebarWidth],
  );

  if (sidebarCollapsed) {
    return (
      <nav className="flex flex-col items-center py-2 px-1 border-r border-border bg-oxide-sidebar-bg h-full w-12 shrink-0" aria-label="Sidebar" data-focus-section="sidebar">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={toggleSidebar} aria-label="Expand sidebar">
                <PanelLeft className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">Expand sidebar (Ctrl+.)</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </nav>
    );
  }

  return (
    <nav className="relative flex flex-col border-r border-border bg-oxide-sidebar-bg h-full shrink-0" style={{ width: `${sidebarWidth / 16}rem` }} aria-label="Sidebar" data-focus-section="sidebar">
      {/* Header */}
      <div className="relative flex items-center justify-between px-3 py-2.5 border-b border-border overflow-hidden">
        <ShaderBackground preset="soft" opacity={0.5} speed={1.0} brightness={3.0} colorSlots={[0, 2, 5, 7]} />
        <div className="relative z-10 flex items-center gap-2">
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={toggleSidebar} aria-label="Collapse sidebar">
            <PanelLeftClose className="h-4 w-4 text-oxide-icon" />
          </Button>
          <span className="text-[0.8125rem] font-bold tracking-tight text-foreground uppercase">VaultSpec</span>
        </div>
        <div className="relative z-10 flex items-center gap-0.5">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-oxide-icon"
                  onClick={() => setThemeMode(themeMode === 'dark' ? 'light' : themeMode === 'light' ? 'system' : 'dark')}
                  aria-label={`Switch theme, current: ${themeMode}`}
                >
                  {themeMode === 'dark' ? <Moon className="h-3.5 w-3.5" /> : themeMode === 'light' ? <Sun className="h-3.5 w-3.5" /> : <Monitor className="h-3.5 w-3.5" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">Theme: {themeMode}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <Button variant="ghost" size="icon" className="h-7 w-7 text-oxide-icon" aria-label="Settings">
            <Settings className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Section header */}
      <div className="px-3 pt-3 pb-1.5">
        <div className="flex items-center justify-between h-7">
          <div className="flex-1 min-w-0 mr-1">
            {searchOpen ? (
              <div className="relative flex items-center">
                <Search className="absolute left-2 h-3 w-3 text-muted-foreground pointer-events-none z-10" />
                <Input
                  ref={searchRef}
                  value={taskFilter}
                  onChange={(e) => setTaskFilter(e.target.value)}
                  onKeyDown={(e) => e.key === 'Escape' && setSearchOpen(false)}
                  placeholder="Filter tasks..."
                  className="h-6 pl-6 pr-2 text-[0.6875rem]"
                  aria-label="Filter tasks"
                />
              </div>
            ) : (
              <span className="text-[0.625rem] font-bold uppercase tracking-widest text-text-dimmed px-1 select-none">
                Tasks
              </span>
            )}
          </div>

          <div className="flex items-center gap-0.5 shrink-0">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 text-text-dimmed hover:text-foreground transition-colors"
                    onClick={() => clearActiveTab()}
                    aria-label="New task"
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">New task</TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className={`h-6 w-6 transition-colors ${searchOpen ? 'text-primary bg-primary/10' : 'text-text-dimmed hover:text-foreground'}`}
                    onClick={() => setSearchOpen(v => !v)}
                    aria-label={searchOpen ? 'Close search' : 'Search tasks'}
                    aria-expanded={searchOpen}
                  >
                    {searchOpen ? <X className="h-3 w-3" /> : <Search className="h-3 w-3" />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">{searchOpen ? 'Close search' : 'Search tasks'}</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>
      </div>

      <ScrollArea className="flex-1 min-h-0">
        <div className="px-2 py-1 space-y-0.5" role="listbox" aria-label="Task list">
          {filteredThreads.length === 0 && taskFilter && (
            <div className="px-3 py-4 text-center text-[0.6875rem] text-text-subtle italic">
              No tasks match &ldquo;{taskFilter}&rdquo;
            </div>
          )}
          {filteredThreads.length === 0 && !taskFilter && (
            <div className="px-3 py-4 text-center text-[0.6875rem] text-text-subtle italic">
              No tasks yet. Click &ldquo;New Task&rdquo; to start.
            </div>
          )}
          {filteredThreads.map((thread) => (
            <TaskItem
              key={thread.thread_id}
              thread={thread}
              agents={agents}
              isActive={activeTabId === thread.thread_id}
              hasPermissionPending={threadsWithPermissions.has(thread.thread_id)}
              onSelect={() => openTransient(thread.thread_id)}
              onDoubleClick={() => openPinned(thread.thread_id)}
            />
          ))}
        </div>
      </ScrollArea>

      {/* Resize handle */}
      <div
        onMouseDown={handleMouseDown}
        tabIndex={0}
        className="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-30"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
      />
    </nav>
  );
}

/** Single task row in the flat sidebar list */
function TaskItem({
  thread,
  agents,
  isActive,
  hasPermissionPending,
  onSelect,
  onDoubleClick,
}: {
  thread: ThreadSummary;
  agents: AgentSummary[];
  isActive: boolean;
  hasPermissionPending?: boolean;
  onSelect: () => void;
  onDoubleClick: () => void;
}) {
  const clickTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clickCount = useRef(0);

  const handleClick = () => {
    clickCount.current += 1;

    if (clickCount.current === 1) {
      // Single-click: open transient immediately
      onSelect();
      clickTimeout.current = setTimeout(() => {
        clickCount.current = 0;
      }, 300);
    } else if (clickCount.current === 2) {
      // Double-click: pin
      if (clickTimeout.current) clearTimeout(clickTimeout.current);
      clickCount.current = 0;
      onDoubleClick();
    }
  };

  const dot = agentStateDot(thread.agent_state);
  const needsAction = thread.agent_state === 'input_required' || thread.agent_state === 'auth_required' || hasPermissionPending;
  const displayName = thread.nickname || thread.title;
  const topoLabel = topologyLabel(thread.topology);
  const teamComposition = agents.map(a => a.node_name).join(' · ');
  const diskPath = thread.source_repo && thread.source_branch
    ? `~/${thread.source_repo}/.git/refs/heads/${thread.source_branch}`
    : null;

  return (
    <TooltipProvider delayDuration={500}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={handleClick}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelect();
                return;
              }
              // ArrowUp / ArrowDown navigation within the task list
              const target = e.currentTarget as HTMLElement;
              const container = target.parentElement;
              if (!container) return;
              const items = Array.from(container.querySelectorAll<HTMLElement>('button[role="option"]'));
              const idx = items.indexOf(target);
              if (idx === -1) return;
              let nextIdx: number | null = null;
              if (e.key === 'ArrowDown') nextIdx = Math.min(idx + 1, items.length - 1);
              if (e.key === 'ArrowUp') nextIdx = Math.max(idx - 1, 0);
              if (e.key === 'Home') nextIdx = 0;
              if (e.key === 'End') nextIdx = items.length - 1;
              if (nextIdx !== null) {
                e.preventDefault();
                items[nextIdx].focus();
              }
            }}
            role="option"
            aria-selected={isActive}
            aria-label={`Task: ${displayName}, ${thread.agent_state}, updated ${timeAgo(thread.updated_at)} ago`}
            className={`w-full text-left rounded-ui px-2.5 py-2 transition-colors group ${
              isActive
                ? 'bg-accent text-accent-foreground shadow-sm border border-border/10'
                : 'hover:bg-accent/40 text-foreground/70'
            }`}
          >
            {/* Row 1: status dot + nickname + time */}
            <div className="flex items-start gap-2">
              {needsAction ? (
                <span className="shrink-0 w-4 flex items-center justify-center mt-0.5">
                  <ShieldAlert className="w-3.5 h-3.5 text-status-warning" />
                </span>
              ) : dot ? (
                <span className="shrink-0 w-4 flex items-center justify-center mt-0.5">{dot}</span>
              ) : (
                <span className="shrink-0 w-4 mt-0.5" />
              )}
              <span className={`flex-1 text-[0.75rem] break-words min-w-0 text-foreground ${isActive ? 'font-bold' : 'font-normal'}`}>
                {displayName}
              </span>
              <span className="text-[0.625rem] text-oxide-metadata shrink-0 tabular-nums mt-0.5">
                {timeAgo(thread.updated_at)}
              </span>
            </div>

            {/* Row 2: metadata — action needed + feature tag + branch */}
            {(thread.feature_tag || thread.source_branch || needsAction) && (
              <div className="flex items-center gap-1.5 mt-1 ml-6 flex-wrap">
                {needsAction && (
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[0.5625rem] font-sans bg-status-warning/15 text-status-warning border border-status-warning/30">
                    Action needed
                  </span>
                )}
                {thread.feature_tag && (
                  <span className="text-[0.625rem] text-oxide-metadata font-mono">
                    #{thread.feature_tag}
                  </span>
                )}
                {thread.source_branch && (
                  <span className="flex items-center gap-0.5 text-[0.625rem] text-oxide-metadata font-mono">
                    <GitBranch className="w-2.5 h-2.5 shrink-0" />
                    {thread.source_branch}
                  </span>
                )}
              </div>
            )}
          </button>
        </TooltipTrigger>
        <TooltipContent
          side="right"
          align="start"
          sideOffset={8}
          className="max-w-[280px] p-0 bg-oxide-terminal-bg border-border rounded-ui shadow-lg"
        >
          <div className="px-3 py-2.5 space-y-2 font-sans">
            <div>
              <span className="text-[0.625rem] text-oxide-metadata uppercase tracking-widest">Task</span>
              <p className="text-[0.75rem] text-foreground font-bold mt-0.5">{thread.title}</p>
              {thread.nickname && thread.nickname !== thread.title && (
                <p className="text-[0.6875rem] text-oxide-metadata font-mono mt-0.5">{thread.nickname}</p>
              )}
            </div>
            {(thread.team_preset || topoLabel) && (
              <div>
                <span className="text-[0.625rem] text-oxide-metadata uppercase tracking-widest">Team</span>
                <p className="text-[0.6875rem] text-foreground mt-0.5">
                  {thread.team_preset || '—'}
                  {topoLabel && <span className="text-oxide-metadata ml-1.5">({topoLabel})</span>}
                </p>
              </div>
            )}
            {agents.length > 0 && (
              <div>
                <span className="text-[0.625rem] text-oxide-metadata uppercase tracking-widest">Agents</span>
                <p className="text-[0.6875rem] text-foreground mt-0.5">{teamComposition}</p>
              </div>
            )}
            {thread.feature_tag && (
              <div>
                <span className="text-[0.625rem] text-oxide-metadata uppercase tracking-widest">Feature</span>
                <p className="text-[0.6875rem] text-foreground font-mono mt-0.5">#{thread.feature_tag}</p>
              </div>
            )}
            {thread.source_branch && (
              <div>
                <span className="text-[0.625rem] text-oxide-metadata uppercase tracking-widest">Branch</span>
                <p className="text-[0.6875rem] text-foreground font-mono mt-0.5">{thread.source_branch}</p>
              </div>
            )}
            {diskPath && (
              <div>
                <span className="text-[0.625rem] text-oxide-metadata uppercase tracking-widest">Path</span>
                <p className="text-[0.625rem] text-foreground font-mono mt-0.5 break-all opacity-80">{diskPath}</p>
              </div>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
