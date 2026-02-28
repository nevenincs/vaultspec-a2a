// ---------------------------------------------------------------------------
// Thread state store — Svelte 5 Runes
// Thread lifecycle: list, CRUD, creation
// ---------------------------------------------------------------------------

import type { ThreadSummary, TeamPreset } from '$lib/data/types';
import {
  createThread as apiCreateThread,
  listThreads as apiListThreads,
} from '$lib/api/rest';
import { tabState } from './tab-state.svelte';

export class ThreadStateStore {
  threads: ThreadSummary[] = $state([]);
  loading: boolean = $state(false);
  error: string | null = $state(null);

  // Derived: get active thread based on tab state
  getActiveThread(activeTabId: string | null): ThreadSummary | null {
    if (!activeTabId) return null;
    return this.threads.find((t) => t.thread_id === activeTabId) ?? null;
  }

  getThread(threadId: string): ThreadSummary | null {
    return this.threads.find((t) => t.thread_id === threadId) ?? null;
  }

  /**
   * Load threads from the REST API.
   */
  async loadThreads(): Promise<void> {
    this.loading = true;
    this.error = null;
    try {
      const response = await apiListThreads();
      this.threads = response.threads.map((t) => ({
        thread_id: t.thread_id,
        title: t.title ?? '',
        agent_state: t.agent_state ?? 'idle',
        updated_at: t.updated_at,
      }));
    } catch (err) {
      this.error = err instanceof Error ? err.message : 'Failed to load threads';
    } finally {
      this.loading = false;
    }
  }

  /**
   * Create a new thread via REST API and open it as a pinned tab.
   */
  async createThread(
    message: string,
    opts?: {
      preset?: TeamPreset;
      repo?: string;
      branch?: string;
      featureTag?: string;
    },
  ): Promise<string | null> {
    const featureSlug = (opts?.featureTag ?? message)
      .slice(0, 30)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
    const topology = opts?.preset?.topology ?? 'star';

    try {
      const response = await apiCreateThread({
        title: message.slice(0, 40) + (message.length > 40 ? '...' : ''),
        initial_message: message,
        provider: null,
        model: null,
      });

      const threadId = response.thread_id;
      const shortHash = threadId.slice(-4);
      const nickname = featureSlug
        ? `${featureSlug}-${topology}-${shortHash}`
        : `task-${topology}-${shortHash}`;

      const newThread: ThreadSummary = {
        thread_id: threadId,
        title: message.slice(0, 40) + (message.length > 40 ? '...' : ''),
        agent_state: 'submitted',
        updated_at: new Date().toISOString(),
        team_preset: opts?.preset?.id,
        nickname,
        feature_tag: opts?.featureTag ?? featureSlug ?? undefined,
        source_repo: opts?.repo,
        source_branch: opts?.branch,
        topology,
        callee: 'api',
      };

      this.threads = [newThread, ...this.threads];
      tabState.openNewThread(threadId);

      return threadId;
    } catch (err) {
      this.error = err instanceof Error ? err.message : 'Failed to create thread';
      return null;
    }
  }

  /**
   * Update a thread summary in-place (e.g. after receiving a status event).
   */
  updateThread(partial: Partial<ThreadSummary> & { thread_id: string }): void {
    this.threads = this.threads.map((t) =>
      t.thread_id === partial.thread_id ? { ...t, ...partial } : t,
    );
  }

  /**
   * Add a locally-created thread summary without API call.
   * Used for optimistic UI in mock/dev mode.
   */
  addThread(thread: ThreadSummary): void {
    this.threads = [thread, ...this.threads];
  }

  /**
   * Remove a thread from the local list.
   */
  removeThread(threadId: string): void {
    this.threads = this.threads.filter((t) => t.thread_id !== threadId);
  }
}

// ---------------------------------------------------------------------------
// Singleton store instance
// ---------------------------------------------------------------------------

export const threadState = new ThreadStateStore();
