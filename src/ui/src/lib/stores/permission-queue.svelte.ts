// ---------------------------------------------------------------------------
// Permission queue store — Svelte 5 Runes
// ---------------------------------------------------------------------------

import type { PermissionOptionKind, PermissionRequestEvent } from '$lib/api/types';
import { respondToPermission } from '$lib/api/rest';

// ---------------------------------------------------------------------------
// Permission queue store
// ---------------------------------------------------------------------------

export class PermissionQueueStore {
  #queue: PermissionRequestEvent[] = $state([]);

  /** The head of the queue (active permission request). */
  get current(): PermissionRequestEvent | null {
    return this.#queue.length > 0 ? this.#queue[0] : null;
  }

  /** Number of pending permission requests. */
  get length(): number {
    return this.#queue.length;
  }

  enqueue(event: PermissionRequestEvent): void {
    // Avoid duplicates by request_id
    if (this.#queue.some((e) => e.request_id === event.request_id)) return;
    this.#queue.push(event);
  }

  dequeue(): void {
    this.#queue.shift();
  }

  /**
   * Respond to the current permission request via REST, then dequeue.
   * MUST use REST, never WebSocket (per ADR-011).
   */
  async respond(optionId: string, kind?: PermissionOptionKind): Promise<void> {
    const current = this.current;
    if (!current) return;

    await respondToPermission(current.request_id, {
      option_id: optionId,
      kind: kind ?? null,
    });

    // Remove the responded request from the queue
    const index = this.#queue.findIndex((e) => e.request_id === current.request_id);
    if (index !== -1) {
      this.#queue.splice(index, 1);
    }
  }
}

// ---------------------------------------------------------------------------
// Singleton store instance
// ---------------------------------------------------------------------------

export const permissionQueue = new PermissionQueueStore();
