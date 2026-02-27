// src/ui/src/lib/api/websocket.svelte.ts

import type { ClientMessage, ServerEvent, ServerEventType } from './types';

type ConnectionStatus = 'disconnected' | 'connecting' | 'connected';
type EventHandler = (event: ServerEvent) => void;

/**
 * Multiplexed, backpressure-aware WebSocket client with reconnection.
 *
 * Public $state fields are reactive — components reading them will
 * automatically re-render on change. Private fields use # prefix
 * for internal state that doesn't need UI reactivity.
 */
export class WebSocketClient {
  // Public reactive state (components can bind to these)
  status = $state<ConnectionStatus>('disconnected');
  clientId = $state<string | null>(null);

  // Private internal state
  #ws: WebSocket | null = null;
  #url = '';
  #attempt = 0;
  #maxDelay = 30_000;
  #heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  #reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  #handlers = new Map<string, EventHandler[]>();
  #sendQueue: string[] = [];
  #lastSequences = new Map<string, number>();

  /**
   * Connect to the WebSocket server.
   */
  connect(url: string): void {
    this.#url = url;
    this.status = 'connecting';
    this.#attempt = 0;
    this.#open();
  }

  /**
   * Disconnect and stop reconnection attempts.
   */
  disconnect(): void {
    this.#clearTimers();
    if (this.#ws) {
      this.#ws.onclose = null; // prevent reconnection trigger
      this.#ws.close();
      this.#ws = null;
    }
    this.status = 'disconnected';
    this.clientId = null;
  }

  /**
   * Send a client command. Queues if not connected.
   */
  send(command: ClientMessage): void {
    const json = JSON.stringify(command);
    if (this.#ws?.readyState === WebSocket.OPEN) {
      this.#ws.send(json);
    } else {
      this.#sendQueue.push(json);
    }
  }

  /**
   * Register an event handler for a specific event type.
   * Multiple handlers per type are supported.
   */
  on(type: ServerEventType, handler: EventHandler): void {
    const existing = this.#handlers.get(type) ?? [];
    existing.push(handler);
    this.#handlers.set(type, existing);
  }

  /**
   * Remove an event handler.
   */
  off(type: ServerEventType, handler: EventHandler): void {
    const existing = this.#handlers.get(type);
    if (existing) {
      this.#handlers.set(
        type,
        existing.filter((h) => h !== handler),
      );
    }
  }

  /**
   * Get the last known sequence number for a thread.
   * Used for gap detection on reconnect per ADR-011 §2.3.
   */
  getLastSequence(threadId: string): number {
    return this.#lastSequences.get(threadId) ?? -1;
  }

  /**
   * Update the last known sequence for a thread.
   */
  updateSequence(threadId: string, sequence: number): void {
    const current = this.#lastSequences.get(threadId) ?? 0;
    if (sequence > current) {
      this.#lastSequences.set(threadId, sequence);
    }
  }

  /**
   * Check if an event should be discarded (stale after reconnect).
   */
  isStaleEvent(threadId: string, sequence: number): boolean {
    return sequence <= (this.#lastSequences.get(threadId) ?? -1);
  }

  // --- Private methods ---

  #open(): void {
    this.status = 'connecting';
    this.#ws = new WebSocket(this.#url);

    this.#ws.onopen = () => {
      this.status = 'connected';
      this.#attempt = 0;
      this.#resetHeartbeat();
      this.#flushQueue();
    };

    this.#ws.onmessage = (ev: MessageEvent) => {
      this.#resetHeartbeat();
      try {
        const event: ServerEvent = JSON.parse(ev.data as string);

        // Track and filter thread-scoped events by sequence number
        if ('thread_id' in event && 'sequence' in event) {
          const threadId = (event as unknown as { thread_id: string }).thread_id;
          const sequence = (event as unknown as { sequence: number }).sequence;

          // Discard stale events on reconnect (ADR-011 §2.3)
          if (this.isStaleEvent(threadId, sequence)) {
            return;
          }

          this.updateSequence(threadId, sequence);
        }

        // Dispatch to registered handlers
        const handlers = this.#handlers.get(event.type);
        if (handlers) {
          for (const handler of handlers) {
            handler(event);
          }
        }
      } catch {
        // Malformed message — silently ignore
      }
    };

    this.#ws.onclose = () => {
      this.status = 'disconnected';
      this.#scheduleReconnect();
    };

    this.#ws.onerror = () => {
      // onerror is always followed by onclose, which handles reconnection
      this.#ws?.close();
    };
  }

  #scheduleReconnect(): void {
    // Exponential backoff: 1s, 2s, 4s, 8s, ..., max 30s (with jitter)
    const delay = Math.min(
      1000 * 2 ** this.#attempt + Math.random() * 1000,
      this.#maxDelay,
    );
    this.#attempt++;
    this.#reconnectTimer = setTimeout(() => this.#open(), delay);
  }

  #resetHeartbeat(): void {
    if (this.#heartbeatTimer) clearTimeout(this.#heartbeatTimer);
    // 90s without any message = dead connection (3 missed 30s heartbeats)
    this.#heartbeatTimer = setTimeout(() => {
      this.#ws?.close();
    }, 90_000);
  }

  #flushQueue(): void {
    while (this.#sendQueue.length > 0) {
      const msg = this.#sendQueue.shift()!;
      this.#ws?.send(msg);
    }
  }

  #clearTimers(): void {
    if (this.#heartbeatTimer) {
      clearTimeout(this.#heartbeatTimer);
      this.#heartbeatTimer = null;
    }
    if (this.#reconnectTimer) {
      clearTimeout(this.#reconnectTimer);
      this.#reconnectTimer = null;
    }
  }
}

// Singleton instance — safe for SPA (no SSR, no cross-request leakage)
export const wsClient = new WebSocketClient();
