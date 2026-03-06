import { useCallback, useEffect, useState, useRef, useMemo } from 'react';
import { useStore } from 'zustand';
import { useShallow } from 'zustand/react/shallow';
import { Sidebar } from './sidebar';
import { StatusBar } from './status-bar';
import { TabBar } from './tab-bar';
import { MessageStream } from '../stream/message-stream';
import { InputBar } from '../stream/input-bar';
import { InspectorPanel } from '../inspector/inspector-panel';
import { useKeyboardNav } from '../../hooks/use-keyboard-nav';
import { log } from '../../utils/logger';
import { NotificationPills } from '../ui/notification-pills';
import { ShaderBackground } from '../ui/shader-background';
import { appStore } from '../../store/app-store';
import { initWsBridge } from '../../bridge/ws-bridge';
import {
  useThreadsQuery,
  useRespondToPermission,
  useCreateThread,
  useSendMessage,
  useCancelThread,
} from '../../queries';
import { useTeamPresetsQuery, useTeamStatusQuery } from '../../queries/use-team';
import { useThreadStateQuery } from '../../queries/use-thread-state';
import { wsClient } from '../../api/websocket-client';
import type { TeamPreset } from '../../data/types';

export function AppShell() {
  // ── Zustand store selectors ────────────────────────────────────────────
  const {
    activeTabId,
    tabs,
    streamEvents,
    permissionQueue,
    inspectorTarget,
    contextDocuments,
    themeMode,
    openTransient,
    openPinned,
    pinTab,
    closeTab,
    activateTab,
    clearActiveTab,
    toggleSidebar,
    openInspector,
    closeInspector,
    openDocument,
    toggleContextPanel,
  } = useStore(
    appStore,
    useShallow((s) => ({
      activeTabId: s.activeTabId,
      tabs: s.tabs,
      streamEvents: s.streamEvents,
      permissionQueue: s.permissionQueue,
      inspectorTarget: s.inspectorTarget,
      contextDocuments: s.contextDocuments,
      themeMode: s.themeMode,
      openTransient: s.openTransient,
      openPinned: s.openPinned,
      pinTab: s.pinTab,
      closeTab: s.closeTab,
      activateTab: s.activateTab,
      clearActiveTab: s.clearActiveTab,
      toggleSidebar: s.toggleSidebar,
      openInspector: s.openInspector,
      closeInspector: s.closeInspector,
      openDocument: s.openDocument,
      toggleContextPanel: s.toggleContextPanel,
    })),
  );

  const connectionState = useStore(appStore, (s) => s.connectionState);

  // ── TanStack Query hooks ───────────────────────────────────────────────
  const { data: threads = [] } = useThreadsQuery();
  const { data: teamPresets = [] } = useTeamPresetsQuery();
  const respondToPermissionMutation = useRespondToPermission();
  const createThreadMutation = useCreateThread();
  const sendMessageMutation = useSendMessage();
  const cancelThreadMutation = useCancelThread();

  // Snapshot hydration for active tab
  useThreadStateQuery(activeTabId);

  const { data: agents = [] } = useTeamStatusQuery();

  // ── Derived state ──────────────────────────────────────────────────────
  const activeThread = useMemo(() => {
    if (!activeTabId) return null;
    if (!tabs.some((t) => t.threadId === activeTabId)) return null;
    return threads.find((t) => t.thread_id === activeTabId) || null;
  }, [activeTabId, tabs, threads]);

  const activeEvents = useMemo(
    () => (activeTabId ? streamEvents[activeTabId] || [] : []),
    [activeTabId, streamEvents],
  );

  const isDark =
    themeMode === 'dark' ||
    (themeMode === 'system' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches);

  // Per-thread permission requests for the active thread
  const activeThreadPermissions = useMemo(
    () =>
      activeTabId ? permissionQueue.filter((p) => p.thread_id === activeTabId) : [],
    [permissionQueue, activeTabId],
  );

  // Set of thread IDs with pending permissions (for sidebar indicators)
  const threadsWithPermissions = useMemo(
    () => new Set(permissionQueue.map((p) => p.thread_id)),
    [permissionQueue],
  );

  // ── WS bridge init ─────────────────────────────────────────────────────
  useEffect(() => {
    const cleanup = initWsBridge();
    return cleanup;
  }, []);

  // ── Subscribe WS to active tab ─────────────────────────────────────────
  useEffect(() => {
    if (!activeTabId || connectionState !== 'connected') return;
    wsClient.subscribe([activeTabId]);
  }, [activeTabId, connectionState]);

  const [selectedPreset, setSelectedPreset] = useState<TeamPreset | null>(null);
  const [inspectorWidth, setInspectorWidth] = useState(420);
  const isResizingInspector = useRef(false);
  const sidebarSearchRef = useRef<(() => void) | null>(null);

  // ── Tab navigation helpers for keyboard shortcut hook ──────────────────
  const closeCurrentTab = useCallback(() => {
    if (activeTabId) closeTab(activeTabId);
  }, [activeTabId, closeTab]);

  const nextTab = useCallback(() => {
    if (tabs.length === 0) return;
    const idx = tabs.findIndex((t) => t.threadId === activeTabId);
    const nextIdx = (idx + 1) % tabs.length;
    activateTab(tabs[nextIdx].threadId);
  }, [tabs, activeTabId, activateTab]);

  const prevTab = useCallback(() => {
    if (tabs.length === 0) return;
    const idx = tabs.findIndex((t) => t.threadId === activeTabId);
    const prevIdx = (idx - 1 + tabs.length) % tabs.length;
    activateTab(tabs[prevIdx].threadId);
  }, [tabs, activeTabId, activateTab]);

  const activateTabByIndex = useCallback(
    (index: number) => {
      if (tabs.length === 0) return;
      if (index === -1) {
        activateTab(tabs[tabs.length - 1].threadId);
      } else if (index < tabs.length) {
        activateTab(tabs[index].threadId);
      }
    },
    [tabs, activateTab],
  );

  const focusSidebarSearch = useCallback(() => {
    sidebarSearchRef.current?.();
  }, []);

  // ── Centralized keyboard shortcuts ────────────────────────────────────
  useKeyboardNav({
    toggleSidebar,
    closeInspector,
    clearActiveTab,
    closeCurrentTab,
    nextTab,
    prevTab,
    activateTabByIndex,
    focusSidebarSearch,
    hasInspector: !!inspectorTarget,
  });

  // ── Boot log ──────────────────────────────────────────────────────────
  useEffect(() => {
    log.info(
      'app.boot',
      `VaultSpec initialized — ${threads.length} threads, ${agents.length} agents loaded`,
      undefined,
      { surface: true, dismissAfter: 3000 },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSend = useCallback(
    (
      message: string,
      opts?: {
        preset?: TeamPreset;
        repo?: string;
        branch?: string;
        featureTag?: string;
      },
    ) => {
      if (activeThread) {
        // Follow-up message into existing thread
        sendMessageMutation.mutate({
          threadId: activeThread.thread_id,
          content: message,
        });
      } else {
        // Create new thread
        createThreadMutation.mutate({
          message,
          preset: opts?.preset || selectedPreset || undefined,
          repo: opts?.repo,
          branch: opts?.branch,
          featureTag: opts?.featureTag,
        });
      }
    },
    [activeThread, createThreadMutation, sendMessageMutation, selectedPreset],
  );

  const isEmptyThread = activeThread && activeEvents.length === 0;
  const isNewThread = isEmptyThread || !activeThread;
  const activeTeam = activeThread
    ? teamPresets.find((p) => p.id === activeThread.team_preset)
    : null;

  const handleToggleContext = useCallback(() => {
    toggleContextPanel(contextDocuments);
  }, [toggleContextPanel, contextDocuments]);

  const isContextOpen = inspectorTarget?.type === 'context_list';
  const hasActiveTab = activeTabId !== null && activeThread !== null;

  // ── Inspector resize handler ───────────────────────────────────────────
  const handleInspectorMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isResizingInspector.current = true;
      const startX = e.clientX;
      const startWidth = inspectorWidth;

      const onMouseMove = (ev: MouseEvent) => {
        if (!isResizingInspector.current) return;
        const newWidth = Math.max(
          260,
          Math.min(700, startWidth - (ev.clientX - startX)),
        );
        setInspectorWidth(newWidth);
      };

      const onMouseUp = () => {
        isResizingInspector.current = false;
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
    [inspectorWidth],
  );

  return (
    <div className="bg-background text-foreground flex h-screen w-screen flex-col overflow-hidden">
      <ShaderBackground />
      <div className="flex min-h-0 flex-1">
        {/* Sidebar */}
        <Sidebar
          threads={threads}
          activeTabId={activeTabId}
          openTransient={openTransient}
          openPinned={openPinned}
          clearActiveTab={clearActiveTab}
          agents={agents}
          threadsWithPermissions={threadsWithPermissions}
          onFocusSearchRef={sidebarSearchRef}
        />

        {/* Main Content Area */}
        <main
          className="flex min-h-0 min-w-0 flex-1 flex-col"
          role="main"
          aria-label="Message stream"
        >
          {/* Tab Bar */}
          <TabBar
            tabs={tabs}
            activeTabId={activeTabId}
            threads={threads}
            activateTab={activateTab}
            pinTab={pinTab}
            closeTab={closeTab}
          />

          {/* Stream + Inspector row */}
          <div className="flex min-h-0 min-w-0 flex-1">
            {/* Stream Panel */}
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              {hasActiveTab ? (
                <>
                  <MessageStream
                    events={activeEvents}
                    onInspect={openInspector}
                    emptyState={isEmptyThread || false}
                    teamPreset={activeTeam || undefined}
                    agents={agents}
                    agentState={activeThread.agent_state}
                    onOpenDocument={openDocument}
                    onToggleContext={handleToggleContext}
                    isContextOpen={isContextOpen}
                    contextDocumentCount={contextDocuments.length}
                    isDark={isDark}
                    pendingPermissions={activeThreadPermissions}
                    onRespondPermission={(requestId, optionId) => {
                      respondToPermissionMutation.mutate({ requestId, optionId });
                    }}
                  />
                  <InputBar
                    agentState={activeThread.agent_state}
                    onSend={handleSend}
                    onStop={() => {
                      if (activeThread) {
                        cancelThreadMutation.mutate(activeThread.thread_id);
                      }
                    }}
                    teamPresets={teamPresets}
                    selectedPreset={activeTeam || selectedPreset}
                    onSelectPreset={setSelectedPreset}
                    isNewThread={!!isNewThread}
                    threads={threads}
                    activeThread={activeThread}
                    isDark={isDark}
                  />
                </>
              ) : (
                <>
                  {/* Empty state — no active tab */}
                  <div
                    className="flex flex-1 items-center justify-center"
                    data-focus-section="stream"
                  >
                    <div className="text-center select-none">
                      <h2 className="text-foreground/60 mb-1 text-[1rem] font-semibold">
                        VaultSpec
                      </h2>
                      <p className="text-muted-foreground text-[0.75rem]">
                        Select a task from the sidebar, or create a new one below.
                      </p>
                    </div>
                  </div>

                  {/* Input bar in create mode */}
                  <InputBar
                    agentState="idle"
                    onSend={handleSend}
                    teamPresets={teamPresets}
                    selectedPreset={selectedPreset}
                    onSelectPreset={setSelectedPreset}
                    isNewThread={true}
                    threads={threads}
                    isDark={isDark}
                  />
                </>
              )}
            </div>

            {/* Inspector Panel */}
            {inspectorTarget && (
              <div
                className="relative h-full shrink-0"
                style={{ width: `${inspectorWidth / 16}rem` }}
                role="complementary"
                aria-label="Inspector panel"
                data-focus-section="inspector"
              >
                {/* Resize handle — left edge */}
                <div
                  onMouseDown={handleInspectorMouseDown}
                  tabIndex={0}
                  className="hover:bg-primary/30 active:bg-primary/50 absolute top-0 left-0 z-30 h-full w-1 cursor-col-resize transition-colors"
                  role="separator"
                  aria-orientation="vertical"
                  aria-label="Resize inspector panel"
                />
                <InspectorPanel
                  target={inspectorTarget}
                  onClose={closeInspector}
                  isDark={isDark}
                  onOpenDocument={openDocument}
                />
              </div>
            )}
          </div>
        </main>
      </div>

      {/* Status Bar */}
      <StatusBar />

      {/* Notification Pills — surfaces logger warnings/errors/info */}
      <NotificationPills />
    </div>
  );
}
