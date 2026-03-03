import { X } from 'lucide-react';
import { useRef } from 'react';
import { agentStateDot } from './state-indicators';
import type { EditorTab, ThreadSummary } from '../../data/types';

interface TabBarProps {
  tabs: EditorTab[];
  activeTabId: string | null;
  threads: ThreadSummary[];
  activateTab: (threadId: string) => void;
  pinTab: (threadId: string) => void;
  closeTab: (threadId: string) => void;
}

export function TabBar({
  tabs,
  activeTabId,
  threads,
  activateTab,
  pinTab,
  closeTab,
}: TabBarProps) {
  if (tabs.length === 0) return null;

  return (
    <div
      className="border-border bg-oxide-sidebar-bg flex h-9 shrink-0 items-end overflow-x-auto border-b"
      role="tablist"
      aria-label="Open tasks"
      data-focus-section="tab-bar"
    >
      {tabs.map((tab) => {
        const thread = threads.find((t) => t.thread_id === tab.threadId);
        const isActive = activeTabId === tab.threadId;
        const label = thread?.nickname || thread?.title || tab.threadId;
        const dot = thread ? agentStateDot(thread.agent_state) : null;

        return (
          <TabItem
            key={tab.threadId}
            label={label}
            isActive={isActive}
            isPinned={tab.isPinned}
            dot={dot}
            onActivate={() => activateTab(tab.threadId)}
            onPin={() => pinTab(tab.threadId)}
            onClose={() => closeTab(tab.threadId)}
          />
        );
      })}
    </div>
  );
}

function TabItem({
  label,
  isActive,
  isPinned,
  dot,
  onActivate,
  onPin,
  onClose,
}: {
  label: string;
  isActive: boolean;
  isPinned: boolean;
  dot: React.ReactNode;
  onActivate: () => void;
  onPin: () => void;
  onClose: () => void;
}) {
  const clickTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clickCount = useRef(0);

  const handleMouseDown = (e: React.MouseEvent) => {
    // Middle-click closes
    if (e.button === 1) {
      e.preventDefault();
      onClose();
    }
  };

  const handleClick = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    clickCount.current += 1;

    if (clickCount.current === 1) {
      // Activate immediately on first click
      onActivate();
      clickTimeout.current = setTimeout(() => {
        clickCount.current = 0;
      }, 300);
    } else if (clickCount.current === 2) {
      // Double-click: pin
      if (clickTimeout.current) clearTimeout(clickTimeout.current);
      clickCount.current = 0;
      onPin();
    }
  };

  const handleCloseClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onClose();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onActivate();
      return;
    }
    if (e.key === 'Delete' || (e.key === 'w' && (e.ctrlKey || e.metaKey))) {
      e.preventDefault();
      onClose();
      return;
    }
    // Arrow key navigation between sibling tabs
    const target = e.currentTarget as HTMLElement;
    const container = target.parentElement;
    if (!container) return;
    const tabs = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]'));
    const idx = tabs.indexOf(target);
    if (idx === -1) return;
    let nextIdx: number | null = null;
    if (e.key === 'ArrowRight') nextIdx = Math.min(idx + 1, tabs.length - 1);
    if (e.key === 'ArrowLeft') nextIdx = Math.max(idx - 1, 0);
    if (e.key === 'Home') nextIdx = 0;
    if (e.key === 'End') nextIdx = tabs.length - 1;
    if (nextIdx !== null) {
      e.preventDefault();
      tabs[nextIdx].focus();
    }
  };

  return (
    <div
      onMouseDown={handleMouseDown}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      role="tab"
      aria-selected={isActive}
      aria-label={`${label}${isPinned ? '' : ' (transient)'}${isActive ? ', active' : ''}`}
      className={`group border-border/40 relative flex h-full max-w-[14rem] shrink-0 cursor-pointer items-center gap-1.5 border-r px-4 font-mono tracking-tight transition-all select-none ${
        isActive
          ? 'bg-oxide-terminal-bg text-foreground shadow-[inset_0_2px_0_var(--primary)]'
          : 'bg-oxide-sidebar-bg text-oxide-metadata hover:text-foreground hover:bg-oxide-terminal-bg/50'
      }`}
    >
      {/* Status dot */}
      {dot && (
        <span className="flex shrink-0 items-center justify-center [&>span]:h-2 [&>span]:w-2 [&>svg]:h-3 [&>svg]:w-3">
          {dot}
        </span>
      )}

      {/* Label — italic when transient */}
      <span
        className={`truncate text-[0.6875rem] font-bold uppercase ${
          isPinned ? '' : 'italic opacity-60'
        }`}
      >
        {label}
      </span>

      {/* Close button */}
      <button
        onClick={handleCloseClick}
        aria-label={`Close tab: ${label}`}
        className="rounded-control hover:bg-muted ml-1.5 shrink-0 p-0.5 opacity-60 transition-all hover:opacity-100"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}
