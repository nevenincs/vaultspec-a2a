import {
  Plus,
  PanelLeftClose,
  PanelLeft,
  Sun,
  Moon,
  Monitor,
  Settings,
  Search,
  X,
  GitBranch,
  ShieldAlert,
} from 'lucide-react';
import { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import type { MutableRefObject } from 'react';
import { useStore } from 'zustand';
import { useShallow } from 'zustand/react/shallow';
import { Button } from '../ui/button';
import { Input } from '../ui/input';
import { ScrollArea } from '../ui/scroll-area';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
  TooltipProvider,
} from '../ui/tooltip';
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
    useShallow((s) => ({
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
    return threads.filter((t) => {
      const searchable = [
        t.nickname,
        t.title,
        t.feature_tag,
        t.source_branch,
        t.source_repo,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
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
        const newWidth = Math.max(
          MIN_WIDTH,
          Math.min(MAX_WIDTH, startWidth + (ev.clientX - startX)),
        );
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
      <nav
        className="border-border bg-oxide-sidebar-bg flex h-full w-12 shrink-0 flex-col items-center border-r px-1 py-2"
        aria-label="Sidebar"
        data-focus-section="sidebar"
      >
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={toggleSidebar}
                aria-label="Expand sidebar"
              >
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
    <nav
      className="border-border bg-oxide-sidebar-bg relative flex h-full shrink-0 flex-col border-r"
      style={{ width: `${sidebarWidth / 16}rem` }}
      aria-label="Sidebar"
      data-focus-section="sidebar"
    >
      {/* Header */}
      <div className="border-border relative flex items-center justify-between overflow-hidden border-b px-3 py-2.5">
        <ShaderBackground
          preset="soft"
          opacity={0.5}
          speed={1.0}
          brightness={3.0}
          colorSlots={[0, 2, 5, 7]}
        />
        <div className="relative z-10 flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={toggleSidebar}
            aria-label="Collapse sidebar"
          >
            <PanelLeftClose className="text-oxide-icon h-4 w-4" />
          </Button>
          <span className="text-foreground text-[0.8125rem] font-bold tracking-tight uppercase">
            VaultSpec
          </span>
        </div>
        <div className="relative z-10 flex items-center gap-0.5">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-oxide-icon h-7 w-7"
                  onClick={() =>
                    setThemeMode(
                      themeMode === 'dark'
                        ? 'light'
                        : themeMode === 'light'
                          ? 'system'
                          : 'dark',
                    )
                  }
                  aria-label={`Switch theme, current: ${themeMode}`}
                >
                  {themeMode === 'dark' ? (
                    <Moon className="h-3.5 w-3.5" />
                  ) : themeMode === 'light' ? (
                    <Sun className="h-3.5 w-3.5" />
                  ) : (
                    <Monitor className="h-3.5 w-3.5" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom">Theme: {themeMode}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <Button
            variant="ghost"
            size="icon"
            className="text-oxide-icon h-7 w-7"
            aria-label="Settings"
          >
            <Settings className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Section header */}
      <div className="px-3 pt-3 pb-1.5">
        <div className="flex h-7 items-center justify-between">
          <div className="mr-1 min-w-0 flex-1">
            {searchOpen ? (
              <div className="relative flex items-center">
                <Search className="text-muted-foreground pointer-events-none absolute left-2 z-10 h-3 w-3" />
                <Input
                  ref={searchRef}
                  value={taskFilter}
                  onChange={(e) => setTaskFilter(e.target.value)}
                  onKeyDown={(e) => e.key === 'Escape' && setSearchOpen(false)}
                  placeholder="Filter tasks..."
                  className="h-6 pr-2 pl-6 text-[0.6875rem]"
                  aria-label="Filter tasks"
                />
              </div>
            ) : (
              <span className="text-text-dimmed px-1 text-[0.625rem] font-bold tracking-widest uppercase select-none">
                Tasks
              </span>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-0.5">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-text-dimmed hover:text-foreground h-6 w-6 transition-colors"
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
                    onClick={() => setSearchOpen((v) => !v)}
                    aria-label={searchOpen ? 'Close search' : 'Search tasks'}
                    aria-expanded={searchOpen}
                  >
                    {searchOpen ? (
                      <X className="h-3 w-3" />
                    ) : (
                      <Search className="h-3 w-3" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  {searchOpen ? 'Close search' : 'Search tasks'}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-0.5 px-2 py-1" role="listbox" aria-label="Task list">
          {filteredThreads.length === 0 && taskFilter && (
            <div className="text-text-subtle px-3 py-4 text-center text-[0.6875rem] italic">
              No tasks match &ldquo;{taskFilter}&rdquo;
            </div>
          )}
          {filteredThreads.length === 0 && !taskFilter && (
            <div className="text-text-subtle px-3 py-4 text-center text-[0.6875rem] italic">
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
        className="hover:bg-primary/30 active:bg-primary/50 absolute top-0 right-0 z-30 h-full w-1 cursor-col-resize transition-colors"
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
  const needsAction =
    thread.agent_state === 'input_required' ||
    thread.agent_state === 'auth_required' ||
    hasPermissionPending;
  const displayName = thread.nickname || thread.title;
  const topoLabel = topologyLabel(thread.topology);
  const teamComposition = agents.map((a) => a.node_name).join(' · ');
  const diskPath =
    thread.source_repo && thread.source_branch
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
              const items = Array.from(
                container.querySelectorAll<HTMLElement>('button[role="option"]'),
              );
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
            className={`rounded-ui group w-full px-2.5 py-2 text-left transition-colors ${
              isActive
                ? 'bg-accent text-accent-foreground border-border/10 border shadow-sm'
                : 'hover:bg-accent/40 text-foreground/70'
            }`}
          >
            {/* Row 1: status dot + nickname + time */}
            <div className="flex items-start gap-2">
              {needsAction ? (
                <span className="mt-0.5 flex w-4 shrink-0 items-center justify-center">
                  <ShieldAlert className="text-status-warning h-3.5 w-3.5" />
                </span>
              ) : dot ? (
                <span className="mt-0.5 flex w-4 shrink-0 items-center justify-center">
                  {dot}
                </span>
              ) : (
                <span className="mt-0.5 w-4 shrink-0" />
              )}
              <span
                className={`text-foreground min-w-0 flex-1 text-[0.75rem] break-words ${isActive ? 'font-bold' : 'font-normal'}`}
              >
                {displayName}
              </span>
              <span className="text-oxide-metadata mt-0.5 shrink-0 text-[0.625rem] tabular-nums">
                {timeAgo(thread.updated_at)}
              </span>
            </div>

            {/* Row 2: metadata — action needed + feature tag + branch */}
            {(thread.feature_tag || thread.source_branch || needsAction) && (
              <div className="mt-1 ml-6 flex flex-wrap items-center gap-1.5">
                {needsAction && (
                  <span className="bg-status-warning/15 text-status-warning border-status-warning/30 inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 font-sans text-[0.5625rem]">
                    Action needed
                  </span>
                )}
                {thread.feature_tag && (
                  <span className="text-oxide-metadata font-mono text-[0.625rem]">
                    #{thread.feature_tag}
                  </span>
                )}
                {thread.source_branch && (
                  <span className="text-oxide-metadata flex items-center gap-0.5 font-mono text-[0.625rem]">
                    <GitBranch className="h-2.5 w-2.5 shrink-0" />
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
          className="bg-oxide-terminal-bg border-border rounded-ui max-w-[280px] p-0 shadow-lg"
        >
          <div className="space-y-2 px-3 py-2.5 font-sans">
            <div>
              <span className="text-oxide-metadata text-[0.625rem] tracking-widest uppercase">
                Task
              </span>
              <p className="text-foreground mt-0.5 text-[0.75rem] font-bold">
                {thread.title}
              </p>
              {thread.nickname && thread.nickname !== thread.title && (
                <p className="text-oxide-metadata mt-0.5 font-mono text-[0.6875rem]">
                  {thread.nickname}
                </p>
              )}
            </div>
            {(thread.team_preset || topoLabel) && (
              <div>
                <span className="text-oxide-metadata text-[0.625rem] tracking-widest uppercase">
                  Team
                </span>
                <p className="text-foreground mt-0.5 text-[0.6875rem]">
                  {thread.team_preset || '—'}
                  {topoLabel && (
                    <span className="text-oxide-metadata ml-1.5">({topoLabel})</span>
                  )}
                </p>
              </div>
            )}
            {agents.length > 0 && (
              <div>
                <span className="text-oxide-metadata text-[0.625rem] tracking-widest uppercase">
                  Agents
                </span>
                <p className="text-foreground mt-0.5 text-[0.6875rem]">
                  {teamComposition}
                </p>
              </div>
            )}
            {thread.feature_tag && (
              <div>
                <span className="text-oxide-metadata text-[0.625rem] tracking-widest uppercase">
                  Feature
                </span>
                <p className="text-foreground mt-0.5 font-mono text-[0.6875rem]">
                  #{thread.feature_tag}
                </p>
              </div>
            )}
            {thread.source_branch && (
              <div>
                <span className="text-oxide-metadata text-[0.625rem] tracking-widest uppercase">
                  Branch
                </span>
                <p className="text-foreground mt-0.5 font-mono text-[0.6875rem]">
                  {thread.source_branch}
                </p>
              </div>
            )}
            {diskPath && (
              <div>
                <span className="text-oxide-metadata text-[0.625rem] tracking-widest uppercase">
                  Path
                </span>
                <p className="text-foreground mt-0.5 font-mono text-[0.625rem] break-all opacity-80">
                  {diskPath}
                </p>
              </div>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
