/**
 * Production WebSocket client for the VaultSpec A2A backend.
 *
 * Protocol:
 * - Connects to ws://host/ws (NOT /api/ws)
 * - Server sends ConnectedEvent immediately on connect
 * - Server sends HeartbeatEvent every 30s
 * - Client sends PingCommand every 30s as keepalive
 * - Client subscribes to thread events via SubscribeCommand
 * - Permission responses MUST go via REST (WS is rejected by server)
 */

import type {
  ServerEvent,
  ConnectedEvent,
  HeartbeatEvent,
  ClientMessage,
  SubscribeCommand,
  UnsubscribeCommand,
  SendMessageCommand,
  AgentControlCommand,
  PingCommand,
  AgentControlAction,
} from '../data/ws-types';

export type {
  ServerEvent,
  ConnectedEvent,
  HeartbeatEvent,
  ClientMessage,
  SubscribeCommand,
  UnsubscribeCommand,
  SendMessageCommand,
  AgentControlCommand,
  PingCommand,
  AgentControlAction,
};

export type ConnectionState =
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'disconnected';

export type EventCallback = (threadId: string, event: ServerEvent) => void;
export type ConnectionCallback = (state: ConnectionState) => void;
export type ConnectedCallback = (event: ConnectedEvent) => void;
export type HeartbeatCallback = (event: HeartbeatEvent) => void;

const PING_INTERVAL = 30_000;
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000];
const HEARTBEAT_TIMEOUT = 65_000; // ~2x 30s interval + margin

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private clientId: string | null = null;
  private connectionState: ConnectionState = 'disconnected';
  private subscribedThreads: Set<string> = new Set();
  private lastSequences: Map<string, number> = new Map();
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;

  // Callbacks
  private onEvent: EventCallback | null = null;
  private onConnectionChange: ConnectionCallback | null = null;
  private onConnected: ConnectedCallback | null = null;
  private onHeartbeat: HeartbeatCallback | null = null;

  constructor(url?: string) {
    const baseUrl = url || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
    // Convert http(s) to ws(s)
    this.url = baseUrl.replace(/^http/, 'ws').replace(/\/$/, '') + '/ws';
  }

  // --- Public API ---

  setEventCallback(cb: EventCallback): void {
    this.onEvent = cb;
  }
  setConnectionCallback(cb: ConnectionCallback): void {
    this.onConnectionChange = cb;
  }
  setConnectedCallback(cb: ConnectedCallback): void {
    this.onConnected = cb;
  }
  setHeartbeatCallback(cb: HeartbeatCallback): void {
    this.onHeartbeat = cb;
  }

  getConnectionState(): ConnectionState {
    return this.connectionState;
  }
  getClientId(): string | null {
    return this.clientId;
  }
  getLastSequence(threadId: string): number {
    return this.lastSequences.get(threadId) ?? 0;
  }

  connect(): void {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;
    this.setConnectionState('connecting');
    this.ws = new WebSocket(this.url);
    this.ws.onopen = () => this.handleOpen();
    this.ws.onmessage = (e) => this.handleMessage(e);
    this.ws.onclose = () => this.handleClose();
    this.ws.onerror = () => {}; // onclose will fire
  }

  disconnect(): void {
    this.clearTimers();
    this.reconnectAttempt = 0;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.setConnectionState('disconnected');
  }

  subscribe(threadIds: string[]): void {
    threadIds.forEach((id) => this.subscribedThreads.add(id));
    if (this.connectionState === 'connected') {
      this.send({ type: 'subscribe', thread_ids: threadIds } as SubscribeCommand);
    }
  }

  unsubscribe(threadIds: string[]): void {
    threadIds.forEach((id) => {
      this.subscribedThreads.delete(id);
      this.lastSequences.delete(id);
    });
    if (this.connectionState === 'connected') {
      this.send({ type: 'unsubscribe', thread_ids: threadIds } as UnsubscribeCommand);
    }
  }

  sendMessage(threadId: string, content: string, agentId?: string): void {
    this.send({
      type: 'send_message',
      thread_id: threadId,
      content,
      agent_id: agentId ?? null,
    } as SendMessageCommand);
  }

  sendAgentControl(
    threadId: string,
    agentId: string,
    action: AgentControlAction,
  ): void {
    this.send({
      type: 'agent_control',
      thread_id: threadId,
      agent_id: agentId,
      action,
    } as AgentControlCommand);
  }

  updateLastSequence(threadId: string, sequence: number): void {
    this.lastSequences.set(threadId, sequence);
  }

  // --- Internal ---

  private send(msg: ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  private handleOpen(): void {
    this.reconnectAttempt = 0;
    this.startPingInterval();
  }

  private handleMessage(e: MessageEvent): void {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let data: any;
    try {
      data = JSON.parse(e.data as string);
    } catch {
      return;
    }

    // Remove trace context injected by server
    // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
    delete data._trace;

    // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
    const eventType = data.type as string;

    if (eventType === 'connected') {
      // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
      this.clientId = data.client_id as string;
      this.setConnectionState('connected');
      this.onConnected?.(data as ConnectedEvent);
      // Re-subscribe to all threads
      if (this.subscribedThreads.size > 0) {
        this.send({
          type: 'subscribe',
          thread_ids: [...this.subscribedThreads],
        } as SubscribeCommand);
      }
      this.resetHeartbeatTimer();
      return;
    }

    if (eventType === 'heartbeat') {
      this.onHeartbeat?.(data as HeartbeatEvent);
      this.resetHeartbeatTimer();
      return;
    }

    // Thread-scoped events — check sequence for gap detection
    // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
    const threadId = data.thread_id as string | undefined;
    // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
    const sequence = data.sequence as number | undefined;
    if (threadId && typeof sequence === 'number') {
      const lastSeq = this.lastSequences.get(threadId) ?? 0;
      if (sequence <= lastSeq) return; // Skip stale events
      this.lastSequences.set(threadId, sequence);
    }

    if (threadId) {
      this.onEvent?.(threadId, data as ServerEvent);
    }
  }

  private handleClose(): void {
    this.ws = null;
    this.clearTimers();
    if (this.connectionState !== 'disconnected') {
      this.setConnectionState('reconnecting');
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    const delay =
      RECONNECT_DELAYS[Math.min(this.reconnectAttempt, RECONNECT_DELAYS.length - 1)];
    this.reconnectAttempt++;
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  private startPingInterval(): void {
    this.clearPingTimer();
    this.pingTimer = setInterval(() => {
      this.send({ type: 'ping' } as PingCommand);
    }, PING_INTERVAL);
  }

  private resetHeartbeatTimer(): void {
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    this.heartbeatTimer = setTimeout(() => {
      // No heartbeat in 65s — assume connection dead
      this.ws?.close();
    }, HEARTBEAT_TIMEOUT);
  }

  private clearPingTimer(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private clearTimers(): void {
    this.clearPingTimer();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.heartbeatTimer) {
      clearTimeout(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private setConnectionState(state: ConnectionState): void {
    if (this.connectionState === state) return;
    this.connectionState = state;
    this.onConnectionChange?.(state);
  }
}

// Singleton
export const wsClient = new WebSocketClient();
