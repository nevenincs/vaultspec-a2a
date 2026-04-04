import type { StateCreator } from 'zustand';
import type { StreamEvent } from '../../data/types';
import type { ServerEvent, WsToolCallContent, components } from '../../data/wire-types';
type WirePlanEntry = components['schemas']['PlanEntry'];
import { mapToolKind, mapToolCallStatus } from '../../api/mappers';
import { wsClient } from '../../api/websocket-client';
import type { AppStore } from '../app-store';

// O(1) lookup: message_id / tool_call_id → { threadId, idx in streamEvents[threadId] }
type ChunkIndex = Map<string, { threadId: string; idx: number }>;

export interface StreamSlice {
  streamEvents: Record<string, StreamEvent[]>;
  /** Internal chunk index — not for external consumers */
  _chunkIndex: ChunkIndex;
  /** agent_id → display_name, populated by team_status events */
  _agentDisplayNames: Record<string, string>;

  handleWireEvent: (threadId: string, event: ServerEvent) => void;
  updateAgentDisplayNames: (
    agents: Array<{ agent_id: string; display_name: string }>,
  ) => void;
  hydrateThreadEvents: (
    threadId: string,
    events: StreamEvent[],
    lastSequence: number,
  ) => void;
  clearThreadEvents: (threadId: string) => void;
}

export const createStreamSlice: StateCreator<
  AppStore,
  [['zustand/devtools', never], ['zustand/persist', unknown], ['zustand/immer', never]],
  [],
  StreamSlice
> = (set, get) => ({
  streamEvents: {},
  _chunkIndex: new Map(),
  _agentDisplayNames: {},

  handleWireEvent: (threadId, event) => {
    const resolveAgentName = (agentId: string | null): string => {
      const id = agentId ?? '';
      return get()._agentDisplayNames[id] || id;
    };
    switch (event.type) {
      case 'message_chunk': {
        const key = event.message_id;
        // Read index BEFORE entering immer draft (Maps are passed unproxied)
        const existing = get()._chunkIndex.get(key);
        if (existing) {
          set(
            (draft) => {
              const arr = draft.streamEvents[threadId];
              if (!arr || existing.idx >= arr.length) return;
              const entry = arr[existing.idx];
              if (entry && entry.type === 'agent_message') {
                entry.content += event.content;
                entry.streaming = !event.finish_reason;
              }
            },
            false,
            'stream/messageChunk/update',
          );
        } else {
          set(
            (draft) => {
              if (!draft.streamEvents[threadId]) {
                draft.streamEvents[threadId] = [];
              }
              const arr = draft.streamEvents[threadId];
              const idx = arr.length;
              draft._chunkIndex.set(key, { threadId, idx });
              arr.push({
                id: key,
                type: 'agent_message',
                timestamp: event.timestamp,
                thread_id: threadId,
                agent_id: event.agent_id ?? '',
                agent_name: resolveAgentName(event.agent_id),
                content: event.content,
                streaming: !event.finish_reason,
              });
            },
            false,
            'stream/messageChunk/new',
          );
        }
        break;
      }

      case 'thought_chunk': {
        const key = `thought-${event.message_id}`;
        const existing = get()._chunkIndex.get(key);
        if (existing) {
          set(
            (draft) => {
              const arr = draft.streamEvents[threadId];
              if (!arr || existing.idx >= arr.length) return;
              const entry = arr[existing.idx];
              if (entry && entry.type === 'thought') {
                entry.content += event.content;
              }
            },
            false,
            'stream/thoughtChunk/update',
          );
        } else {
          set(
            (draft) => {
              if (!draft.streamEvents[threadId]) {
                draft.streamEvents[threadId] = [];
              }
              const arr = draft.streamEvents[threadId];
              const idx = arr.length;
              draft._chunkIndex.set(key, { threadId, idx });
              arr.push({
                id: key,
                type: 'thought',
                timestamp: event.timestamp,
                thread_id: threadId,
                agent_id: event.agent_id ?? '',
                agent_name: resolveAgentName(event.agent_id),
                content: event.content,
              });
            },
            false,
            'stream/thoughtChunk/new',
          );
        }
        break;
      }

      case 'tool_call_start': {
        const loc = event.locations?.[0];
        const textC = event.content?.find((c: WsToolCallContent) => c.content_type === 'text');
        const diffC = event.content?.find((c: WsToolCallContent) => c.content_type === 'diff');
        const termC = event.content?.find((c: WsToolCallContent) => c.content_type === 'terminal');
        set(
          (draft) => {
            if (!draft.streamEvents[threadId]) {
              draft.streamEvents[threadId] = [];
            }
            const arr = draft.streamEvents[threadId];
            const idx = arr.length;
            draft._chunkIndex.set(event.tool_call_id, { threadId, idx });
            arr.push({
              id: event.tool_call_id,
              type: 'tool_call',
              timestamp: event.timestamp,
              thread_id: threadId,
              agent_id: event.agent_id ?? '',
              agent_name: resolveAgentName(event.agent_id),
              tool_call_id: event.tool_call_id,
              tool_name: event.title,
              tool_kind: mapToolKind(event.kind),
              status: mapToolCallStatus(event.status),
              location: loc
                ? { file: loc.path, line: loc.line ?? undefined }
                : undefined,
              input: textC?.content_type === 'text' ? textC.text : undefined,
              diff:
                diffC?.content_type === 'diff'
                  ? { old_content: diffC.old_text ?? '', new_content: diffC.new_text }
                  : undefined,
              diff_path: diffC?.content_type === 'diff' ? diffC.path : undefined,
              terminal_id: termC?.content_type === 'terminal' ? termC.terminal_id : undefined,
            });
          },
          false,
          'stream/toolCallStart',
        );
        break;
      }

      case 'tool_call_update': {
        const existing = get()._chunkIndex.get(event.tool_call_id);
        if (existing) {
          set(
            (draft) => {
              const arr = draft.streamEvents[threadId];
              if (!arr || existing.idx >= arr.length) return;
              const entry = arr[existing.idx];
              if (entry && entry.type === 'tool_call') {
                if (event.status) entry.status = mapToolCallStatus(event.status);
                if (event.title) entry.tool_name = event.title;
                if (event.kind) entry.tool_kind = mapToolKind(event.kind);
                if (event.locations?.[0]) {
                  const loc = event.locations[0];
                  entry.location = { file: loc.path, line: loc.line ?? undefined };
                }
                if (event.content) {
                  const t = event.content.find((c: WsToolCallContent) => c.content_type === 'text');
                  const d = event.content.find((c: WsToolCallContent) => c.content_type === 'diff');
                  const term = event.content.find((c: WsToolCallContent) => c.content_type === 'terminal');
                  if (t?.content_type === 'text') entry.output = t.text;
                  if (d?.content_type === 'diff') {
                    entry.diff = {
                      old_content: d.old_text ?? '',
                      new_content: d.new_text,
                    };
                    entry.diff_path = d.path;
                  }
                  if (term?.content_type === 'terminal') entry.terminal_id = term.terminal_id;
                }
              }
            },
            false,
            'stream/toolCallUpdate',
          );
        }
        break;
      }

      case 'artifact_update': {
        set(
          (draft) => {
            if (!draft.streamEvents[threadId]) {
              draft.streamEvents[threadId] = [];
            }
            const arr = draft.streamEvents[threadId];
            const existingIdx = arr.findIndex(
              (e) => e.type === 'artifact' && e.id === event.artifact_id,
            );
            if (existingIdx >= 0 && event.append) {
              const entry = arr[existingIdx];
              if (entry.type === 'artifact') {
                entry.content += event.content;
                entry.complete = event.last_chunk;
              }
            } else {
              arr.push({
                id: event.artifact_id,
                type: 'artifact',
                timestamp: event.timestamp,
                thread_id: threadId,
                agent_id: event.agent_id ?? '',
                agent_name: resolveAgentName(event.agent_id),
                artifact_id: event.artifact_id,
                filename: event.filename,
                content: event.content,
                complete: event.last_chunk,
              });
            }
          },
          false,
          'stream/artifactUpdate',
        );
        break;
      }

      case 'plan_update': {
        set(
          (draft) => {
            if (!draft.streamEvents[threadId]) {
              draft.streamEvents[threadId] = [];
            }
            draft.streamEvents[threadId].push({
              id: `plan-${event.timestamp}`,
              type: 'plan_update',
              timestamp: event.timestamp,
              thread_id: threadId,
              agent_id: event.agent_id ?? '',
              agent_name: resolveAgentName(event.agent_id),
              entries: event.entries.map((e: WirePlanEntry, i: number) => ({
                id: `plan-entry-${i}`,
                content: e.content,
                status: e.status,
                priority: e.priority,
              })),
            });
          },
          false,
          'stream/planUpdate',
        );
        break;
      }

      case 'agent_status': {
        set(
          (draft) => {
            if (!draft.streamEvents[threadId]) {
              draft.streamEvents[threadId] = [];
            }
            draft.streamEvents[threadId].push({
              id: `status-${event.agent_id}-${event.timestamp}`,
              type: 'agent_status',
              timestamp: event.timestamp,
              thread_id: threadId,
              agent_id: event.agent_id ?? '',
              agent_name: resolveAgentName(event.agent_id) || event.node_name,
              state: event.state,
            });
          },
          false,
          'stream/agentStatus',
        );
        break;
      }

      case 'error': {
        set(
          (draft) => {
            if (!draft.streamEvents[threadId]) {
              draft.streamEvents[threadId] = [];
            }
            draft.streamEvents[threadId].push({
              id: `error-${event.timestamp}`,
              type: 'error',
              timestamp: event.timestamp,
              thread_id: threadId,
              message: event.message,
              code: event.code,
              agent_id: event.agent_id ?? undefined,
              recoverable: event.recoverable,
            });
          },
          false,
          'stream/error',
        );
        break;
      }

      // permission_request, team_status, connected, heartbeat handled by bridge/ws-bridge.ts
      default:
        break;
    }
  },

  updateAgentDisplayNames: (agents) => {
    set(
      (draft) => {
        for (const agent of agents) {
          if (agent.display_name) {
            draft._agentDisplayNames[agent.agent_id] = agent.display_name;
          }
        }
      },
      false,
      'stream/updateAgentDisplayNames',
    );
  },

  hydrateThreadEvents: (threadId, events, lastSequence) => {
    // Rebuild the chunk index from the hydrated events.
    // Note: thought event ids are already prefixed with "thought-" (set in handleWireEvent),
    // so we use ev.id directly as the key for all accumulable event types.
    const newIndex: ChunkIndex = new Map(get()._chunkIndex);
    events.forEach((ev, idx) => {
      if (
        ev.type === 'agent_message' ||
        ev.type === 'thought' ||
        ev.type === 'tool_call'
      ) {
        newIndex.set(ev.id, { threadId, idx });
      }
    });

    set(
      (draft) => {
        draft.streamEvents[threadId] = events;
        // Replace the Map entirely (immer passes Maps unproxied)
        draft._chunkIndex = newIndex;
      },
      false,
      'stream/hydrate',
    );

    // Update last sequence on WS client so gaps are bridged
    wsClient.updateLastSequence(threadId, lastSequence);
  },

  clearThreadEvents: (threadId) => {
    const index = get()._chunkIndex;
    // Remove all chunk index entries for this thread
    const newIndex: ChunkIndex = new Map();
    for (const [key, val] of index) {
      if (val.threadId !== threadId) {
        newIndex.set(key, val);
      }
    }
    set(
      (draft) => {
        delete draft.streamEvents[threadId];
        draft._chunkIndex = newIndex;
      },
      false,
      'stream/clear',
    );
  },
});
