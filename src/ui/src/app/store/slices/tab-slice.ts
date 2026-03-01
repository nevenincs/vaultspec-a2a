import type { StateCreator } from 'zustand';
import type { EditorTab } from '../../data/types';
import { wsClient } from '../../api/websocket-client';
import type { AppStore } from '../app-store';

export interface TabSlice {
  tabs: EditorTab[];
  activeTabId: string | null;
  openTransient: (threadId: string) => void;
  openPinned: (threadId: string) => void;
  pinTab: (threadId: string) => void;
  closeTab: (threadId: string) => void;
  activateTab: (threadId: string) => void;
  clearActiveTab: () => void;
}

export const createTabSlice: StateCreator<
  AppStore,
  [['zustand/devtools', never], ['zustand/persist', unknown], ['zustand/immer', never]],
  [],
  TabSlice
> = (set, get) => ({
  tabs: [],
  activeTabId: null,

  openTransient: (threadId) =>
    set(
      (draft) => {
        if (!draft.tabs.some((t) => t.threadId === threadId)) {
          // Replace any existing transient tab, preserving pinned tabs
          const pinned = draft.tabs.filter((t) => t.isPinned);
          draft.tabs = [...pinned, { threadId, isPinned: false }];
        }
        draft.activeTabId = threadId;
      },
      false,
      'tabs/openTransient',
    ),

  openPinned: (threadId) =>
    set(
      (draft) => {
        const existing = draft.tabs.find((t) => t.threadId === threadId);
        if (existing) {
          existing.isPinned = true;
        } else {
          // Remove transient tabs, add as pinned
          const withoutTransient = draft.tabs.filter((t) => t.isPinned);
          draft.tabs = [...withoutTransient, { threadId, isPinned: true }];
        }
        draft.activeTabId = threadId;
      },
      false,
      'tabs/openPinned',
    ),

  pinTab: (threadId) =>
    set(
      (draft) => {
        const tab = draft.tabs.find((t) => t.threadId === threadId);
        if (tab) tab.isPinned = true;
      },
      false,
      'tabs/pin',
    ),

  closeTab: (threadId) => {
    wsClient.unsubscribe([threadId]);
    set(
      (draft) => {
        const idx = draft.tabs.findIndex((t) => t.threadId === threadId);
        draft.tabs = draft.tabs.filter((t) => t.threadId !== threadId);
        if (threadId === draft.activeTabId) {
          if (draft.tabs.length === 0) {
            draft.activeTabId = null;
          } else {
            draft.activeTabId =
              draft.tabs[Math.min(idx, draft.tabs.length - 1)].threadId;
          }
        }
      },
      false,
      'tabs/close',
    );
    // Clean up stream events for the closed tab
    get().clearThreadEvents(threadId);
  },

  activateTab: (threadId) =>
    set(
      (draft) => {
        draft.activeTabId = threadId;
      },
      false,
      'tabs/activate',
    ),

  clearActiveTab: () =>
    set(
      (draft) => {
        draft.activeTabId = null;
      },
      false,
      'tabs/clearActive',
    ),
});
