// ---------------------------------------------------------------------------
// Tab state store — Svelte 5 Runes
// VS Code-style preview/transient + pinned tab system
// ---------------------------------------------------------------------------

import type { EditorTab } from '$lib/data/types';

export class TabStateStore {
  tabs: EditorTab[] = $state([]);
  activeTabId: string | null = $state(null);

  // Derived: the thread ID currently active in the editor area
  get activeThreadId(): string | null {
    if (!this.activeTabId) return null;
    const hasTab = this.tabs.some((t) => t.threadId === this.activeTabId);
    return hasTab ? this.activeTabId : null;
  }

  /**
   * Single-click: open as transient (preview).
   * Replaces any existing transient tab; already-open tabs are just activated.
   */
  openTransient(threadId: string): void {
    const existing = this.tabs.find((t) => t.threadId === threadId);
    if (existing) {
      this.activeTabId = threadId;
      return;
    }
    // Remove any existing transient tab, append new transient
    const pinned = this.tabs.filter((t) => t.isPinned);
    this.tabs = [...pinned, { threadId, isPinned: false }];
    this.activeTabId = threadId;
  }

  /**
   * Double-click: open and immediately pin.
   * If tab already exists, just pin it and activate.
   */
  openPinned(threadId: string): void {
    const existing = this.tabs.find((t) => t.threadId === threadId);
    if (existing) {
      this.tabs = this.tabs.map((t) =>
        t.threadId === threadId ? { ...t, isPinned: true } : t,
      );
      this.activeTabId = threadId;
      return;
    }
    // Remove transient, add as pinned
    const withoutTransient = this.tabs.filter((t) => t.isPinned);
    this.tabs = [...withoutTransient, { threadId, isPinned: true }];
    this.activeTabId = threadId;
  }

  /** Pin the tab for a given threadId (e.g. double-click on tab label). */
  pinTab(threadId: string): void {
    this.tabs = this.tabs.map((t) =>
      t.threadId === threadId ? { ...t, isPinned: true } : t,
    );
  }

  /**
   * Close a tab. Activates adjacent tab if closing the active one.
   */
  closeTab(threadId: string): void {
    const idx = this.tabs.findIndex((t) => t.threadId === threadId);
    const next = this.tabs.filter((t) => t.threadId !== threadId);
    if (threadId === this.activeTabId) {
      if (next.length === 0) {
        this.activeTabId = null;
      } else {
        const newIdx = Math.min(idx, next.length - 1);
        this.activeTabId = next[newIdx].threadId;
      }
    }
    this.tabs = next;
  }

  /** Activate an already-open tab by threadId. */
  activateTab(threadId: string): void {
    this.activeTabId = threadId;
  }

  /** Deselect all tabs — show the welcome/empty state. */
  clearActiveTab(): void {
    this.activeTabId = null;
  }

  /**
   * Open a new thread as a pinned tab.
   * Used when creating new threads (user committed to it).
   */
  openNewThread(threadId: string): void {
    this.tabs = [...this.tabs, { threadId, isPinned: true }];
    this.activeTabId = threadId;
  }
}

// ---------------------------------------------------------------------------
// Singleton store instance
// ---------------------------------------------------------------------------

export const tabState = new TabStateStore();
