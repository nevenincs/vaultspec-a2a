/**
 * SSE client for thread-scoped event streaming.
 *
 * Connects to GET /api/threads/{thread_id}/stream using the browser
 * EventSource API. Read-only transport — server pushes named SSE events
 * that map to ServerEvent types plus the ad-hoc `thread_terminal` event.
 *
 * EventSource handles automatic reconnection with the browser's built-in
 * backoff, so no custom retry logic is needed.
 */

import type { ServerEvent } from '../data/ws-types';
import { log } from '../utils/logger';

export type ConnectionState = 'connected' | 'reconnecting' | 'disconnected';
export type EventCallback = (threadId: string, event: ServerEvent) => void;
export type ConnectionCallback = (state: ConnectionState) => void;

/**
 * Ad-hoc terminal event emitted by the SSE endpoint when the thread
 * has already reached a terminal status. Not part of ServerEventType.
 */
export interface ThreadTerminalEvent {
  type: 'thread_terminal';
  event_type: 'thread_terminal';
  thread_id: string;
  status: string;
  replay: boolean;
}

export class SSEClient {
  private source: EventSource | null = null;
  private baseUrl: string;
  private activeThreadId: string | null = null;
  private connectionState: ConnectionState = 'disconnected';
  private lastSequence = 0;

  private onEvent: EventCallback | null = null;
  private onConnectionChange: ConnectionCallback | null = null;

  constructor(url?: string) {
    this.baseUrl = (
      url ||
      import.meta.env.VITE_API_BASE_URL ||
      'http://localhost:8000'
    ).replace(/\/$/, '');
  }

  // --- Public API ---

  setEventCallback(cb: EventCallback): void {
    this.onEvent = cb;
  }

  setConnectionCallback(cb: ConnectionCallback): void {
    this.onConnectionChange = cb;
  }

  getConnectionState(): ConnectionState {
    return this.connectionState;
  }

  getActiveThreadId(): string | null {
    return this.activeThreadId;
  }

  /** Set the last seen sequence number (e.g. from a REST snapshot). */
  updateLastSequence(seq: number): void {
    this.lastSequence = seq;
  }

  /**
   * Open an SSE connection for a single thread. Closes any existing
   * connection first — only one thread can be streamed at a time.
   */
  connect(threadId: string): void {
    if (this.source) {
      this.disconnect();
    }

    this.lastSequence = 0;
    this.activeThreadId = threadId;
    const url = `${this.baseUrl}/api/threads/${encodeURIComponent(threadId)}/stream`;
    const es = new EventSource(url);
    this.source = es;

    es.onopen = () => {
      this.setConnectionState('connected');
    };

    // The SSE endpoint uses named events (event: <type>), so we
    // Listen for thread-scoped event types. The SSE endpoint does NOT emit
    // `connected` (that's WS-only — connection state is handled by onopen).
    // `heartbeat` and `thread_terminal` have dedicated listeners below.
    const knownEvents = [
      'agent_status',
      'message_chunk',
      'thought_chunk',
      'tool_call_start',
      'tool_call_update',
      'permission_request',
      'artifact_update',
      'plan_update',
      'team_status',
      'error',
    ] as const;

    for (const eventType of knownEvents) {
      es.addEventListener(eventType, (e: MessageEvent) => {
        this.dispatchEvent(threadId, e);
      });
    }

    // Ad-hoc event not in ServerEventType — thread was already in a
    // terminal state when the SSE connection opened. Log it but don't
    // dispatch through the ServerEvent pipeline (it doesn't conform to
    // the discriminated union).
    es.addEventListener('thread_terminal', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data as string) as ThreadTerminalEvent;
        log.info('[SSE] thread_terminal:', data.thread_id, data.status);
      } catch {
        /* skip malformed */
      }
      // Terminal means the server will close the stream. Disconnect now to
      // prevent EventSource from auto-reconnecting in a loop.
      this.disconnect();
    });

    // Heartbeat — just reset connection state, no dispatch to store
    es.addEventListener('heartbeat', () => {
      // Heartbeats confirm the connection is alive. If we were
      // reconnecting the browser already fired onopen, so this
      // is a no-op under normal conditions.
    });

    es.onerror = () => {
      // EventSource auto-reconnects. If readyState is CONNECTING the
      // browser is retrying; if CLOSED the connection is dead.
      if (es.readyState === EventSource.CONNECTING) {
        this.setConnectionState('reconnecting');
      } else if (es.readyState === EventSource.CLOSED) {
        this.setConnectionState('disconnected');
      }
    };
  }

  /** Close the EventSource and reset state. */
  disconnect(): void {
    if (this.source) {
      this.source.close();
      this.source = null;
    }
    this.activeThreadId = null;
    this.lastSequence = 0;
    this.setConnectionState('disconnected');
  }

  // --- Internal ---

  private dispatchEvent(threadId: string, e: MessageEvent): void {
    try {
      const data = JSON.parse(e.data as string) as ServerEvent;
      // Sequence dedup — drop events already seen (EventSource may replay on reconnect)
      if ('sequence' in data && typeof data.sequence === 'number') {
        if (data.sequence <= this.lastSequence) return;
        this.lastSequence = data.sequence;
      }
      this.onEvent?.(threadId, data);
    } catch {
      // Malformed payload — skip silently
    }
  }

  private setConnectionState(state: ConnectionState): void {
    if (this.connectionState === state) return;
    this.connectionState = state;
    this.onConnectionChange?.(state);
  }
}

// Singleton
export const sseClient = new SSEClient();
