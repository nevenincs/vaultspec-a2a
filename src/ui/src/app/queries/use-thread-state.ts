import { useQuery } from '@tanstack/react-query';
import { useStore } from 'zustand';
import { restClient } from '../api/rest-client';
import { mapToolKind, mapToolCallStatus } from '../api/mappers';
import { appStore } from '../store/app-store';
import { queryKeys } from './query-keys';
import type { StreamEvent } from '../data/types';

/**
 * Fetches the thread state snapshot from the REST API.
 *
 * Enabled only when:
 * 1. threadId is provided (tab is active)
 * 2. Zustand store has no events for this thread (avoids re-fetch on revisit)
 *
 * On success, builds StreamEvent[] and hydrates the Zustand store so WS
 * events can append from the correct sequence number onwards.
 */
export function useThreadStateQuery(threadId: string | null) {
  const hasEvents = useStore(appStore, (s) =>
    threadId ? (s.streamEvents[threadId]?.length ?? 0) > 0 : false,
  );

  return useQuery({
    queryKey: queryKeys.threads.state(threadId ?? ''),
    queryFn: async () => {
      if (!threadId) throw new Error('No threadId');

      const snapshot = await restClient.getThreadState(threadId);

      const events: StreamEvent[] = [];

      for (const msg of snapshot.messages) {
        if (msg.role === 'human') {
          events.push({
            id: msg.message_id,
            type: 'user_message',
            timestamp: msg.timestamp,
            thread_id: threadId,
            content: msg.content,
          });
        } else {
          events.push({
            id: msg.message_id,
            type: 'agent_message',
            timestamp: msg.timestamp,
            thread_id: threadId,
            agent_id: msg.agent_id ?? '',
            agent_name: msg.agent_id ?? '',
            content: msg.content,
            streaming: false,
          });
        }
      }

      for (const tc of snapshot.tool_calls) {
        const loc = tc.locations[0];
        events.push({
          id: tc.tool_call_id,
          type: 'tool_call',
          timestamp: '',
          thread_id: threadId,
          agent_id: '',
          agent_name: '',
          tool_call_id: tc.tool_call_id,
          tool_name: tc.title,
          tool_kind: mapToolKind(tc.kind),
          status: mapToolCallStatus(tc.status),
          location: loc ? { file: loc.path, line: loc.line ?? undefined } : undefined,
        });
      }

      for (const art of snapshot.artifacts) {
        events.push({
          id: art.artifact_id,
          type: 'artifact',
          timestamp: '',
          thread_id: threadId,
          agent_id: '',
          agent_name: '',
          artifact_id: art.artifact_id,
          filename: art.filename,
          content: art.content,
          complete: art.complete,
        });
      }

      // Hydrate Zustand store — also updates WS lastSequence
      appStore.getState().hydrateThreadEvents(threadId, events, snapshot.last_sequence);

      return { events, lastSequence: snapshot.last_sequence };
    },
    staleTime: Infinity,
    enabled: !!threadId && !hasEvents,
  });
}
