/**
 * WS Bridge — connects the WebSocket client to Zustand + TanStack Query.
 *
 * `initWsBridge()` is called once from AppShell's mount useEffect.
 * It runs entirely outside React's render cycle via the vanilla Zustand store
 * and the module-level queryClient singleton.
 */

import type { ServerEvent } from '../data/ws-types';
import {
  wsClient,
  type ConnectionState as WsConnectionState,
} from '../api/websocket-client';
import {
  sseClient,
  type ConnectionState as SseConnectionState,
} from '../api/sse-client';
import { mapAgentSummary } from '../api/mappers';
import { appStore } from '../store/app-store';
import { queryClient } from '../queries/query-client';
import { queryKeys } from '../queries/query-keys';
import type { ConnectionState as FrontendConnectionState } from '../data/types';
import type { AgentSummary, ThreadSummary } from '../data/types';

/**
 * When true, incoming thread events are received via SSE instead of WS.
 * WS remains connected for sending commands (subscribe, send_message, etc.).
 * Flip to `true` to switch the read transport to SSE.
 */
export const USE_SSE = false;

function toFrontendConnectionState(ws: WsConnectionState): FrontendConnectionState {
  if (ws === 'connecting') return 'reconnecting';
  return ws;
}

function sseToFrontendConnectionState(sse: SseConnectionState): FrontendConnectionState {
  return sse;
}

/**
 * Dispatch a single thread-scoped event to the Zustand store and TQ caches.
 * Shared by both the WS and SSE transport paths.
 */
function dispatchEvent(threadId: string, event: ServerEvent): void {
  switch (event.type) {
    case 'message_chunk':
    case 'thought_chunk':
    case 'tool_call_start':
    case 'tool_call_update':
    case 'artifact_update':
    case 'plan_update':
    case 'error': {
      appStore.getState().handleWireEvent(threadId, event);
      break;
    }

    case 'agent_status': {
      appStore.getState().handleWireEvent(threadId, event);
      queryClient.setQueryData<AgentSummary[]>(
        queryKeys.team.status(),
        (prev = []) => {
          const idx = prev.findIndex((a) => a.agent_id === event.agent_id);
          if (idx >= 0) {
            const updated = [...prev];
            updated[idx] = { ...updated[idx], state: event.state };
            return updated;
          }
          return prev;
        },
      );
      queryClient.setQueryData<ThreadSummary[]>(
        queryKeys.threads.list(),
        (prev = []) =>
          prev.map((t) =>
            t.thread_id === threadId
              ? { ...t, agent_state: event.state }
              : t,
          ),
      );
      break;
    }

    case 'team_status': {
      queryClient.setQueryData<AgentSummary[]>(
        queryKeys.team.status(),
        event.agents.map(mapAgentSummary),
      );
      appStore.getState().updateAgentDisplayNames(event.agents);
      break;
    }

    case 'permission_request': {
      appStore.getState().pushPermission(event);
      break;
    }

    // connected / heartbeat are handled by their own callbacks
    default:
      break;
  }
}

/**
 * Initialize the WS bridge. Call once on app mount.
 * Returns a cleanup function that disconnects the WS client.
 */
export function initWsBridge(): () => void {
  // 1. Connection state → Zustand (only when WS is the read transport)
  if (!USE_SSE) {
    wsClient.setConnectionCallback((wsState) => {
      appStore.getState().setConnectionState(toFrontendConnectionState(wsState));
    });
  }

  // 2. Connected → log bootstrap info (progressive enhancement)
  wsClient.setConnectedCallback((event) => {
    console.info(
      `[ws-bridge] connected — server ${event.server_version}, ` +
        `${(event.active_threads ?? []).length} active thread(s)`,
    );
  });

  // 3. Heartbeat → Zustand
  wsClient.setHeartbeatCallback(() => {
    appStore.getState().setLastHeartbeat(Date.now());
  });

  // 4. Wire events → Zustand + TQ cache (only when WS is the read transport)
  if (!USE_SSE) {
    wsClient.setEventCallback((threadId, event) => {
      dispatchEvent(threadId, event);
      if ('sequence' in event && typeof event.sequence === 'number') {
        wsClient.updateLastSequence(threadId, event.sequence);
      }
    });
  }

  wsClient.connect();

  // When USE_SSE is enabled, wire SSE callbacks for read-side events.
  if (USE_SSE) {
    sseClient.setConnectionCallback((sseState) => {
      appStore.getState().setConnectionState(sseToFrontendConnectionState(sseState));
    });
    sseClient.setEventCallback((threadId, event) => {
      dispatchEvent(threadId, event);
    });
  }

  return () => {
    wsClient.disconnect();
    sseClient.disconnect();
  };
}
