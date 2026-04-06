import { useQuery } from '@tanstack/react-query';
import { useStore } from 'zustand';
import { restClient } from '../api/rest-client';
import { mapToolKind, mapToolCallStatus } from '../api/mappers';
import { appStore } from '../store/app-store';
import { queryClient } from './query-client';
import { queryKeys } from './query-keys';
import type { StreamEvent, ThreadSummary, PermissionRequest } from '../data/types';
import type { components } from '../data/wire-types';

type _PermissionSnapshot = components['schemas']['_PermissionSnapshot'];
type ToolCallContentText = components['schemas']['ToolCallContentText'];
type ToolCallContentDiff = components['schemas']['ToolCallContentDiff'];
type ToolCallContentTerminal = components['schemas']['ToolCallContentTerminal'];

type ToolCallContent =
  | ToolCallContentText
  | ToolCallContentDiff
  | ToolCallContentTerminal;

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

      // Step 3: Hydrate agents — populate display name cache and build local lookup
      const agentNames: Record<string, string> = {};
      if (snapshot.agents?.length) {
        appStore.getState().updateAgentDisplayNames(snapshot.agents);
        for (const a of snapshot.agents) {
          if (a.display_name) agentNames[a.agent_id] = a.display_name;
        }
      }
      const resolveAgent = (agentId: string | null | undefined): string => {
        const id = agentId ?? '';
        return agentNames[id] || id;
      };

      const events: StreamEvent[] = [];

      // Hydrate messages (step 4: use agent name lookup)
      for (const msg of snapshot.messages ?? []) {
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
            agent_name: resolveAgent(msg.agent_id),
            content: msg.content,
            streaming: false,
          });
        }
      }

      // Hydrate tool calls (step 4: agent names, step 5: content hydration)
      for (const tc of snapshot.tool_calls ?? []) {
        const loc = tc.locations?.[0];
        const contents = tc.content as ToolCallContent[] | undefined;
        const textC = contents?.find(
          (c): c is ToolCallContentText => c.content_type === 'text',
        );
        const diffC = contents?.find(
          (c): c is ToolCallContentDiff => c.content_type === 'diff',
        );
        const termC = contents?.find(
          (c): c is ToolCallContentTerminal => c.content_type === 'terminal',
        );
        const isCompleted = tc.status === 'completed';

        events.push({
          id: tc.tool_call_id,
          type: 'tool_call',
          timestamp: '',
          thread_id: threadId,
          agent_id: '',
          agent_name: resolveAgent(null),
          tool_call_id: tc.tool_call_id,
          tool_name: tc.title,
          tool_kind: mapToolKind(tc.kind),
          status: mapToolCallStatus(tc.status),
          location: loc ? { file: loc.path, line: loc.line ?? undefined } : undefined,
          input: textC && !isCompleted ? textC.text : undefined,
          output: textC && isCompleted ? textC.text : undefined,
          diff: diffC
            ? { old_content: diffC.old_text ?? '', new_content: diffC.new_text }
            : undefined,
          diff_path: diffC?.path,
          terminal_id: termC?.terminal_id,
        });
      }

      // Hydrate artifacts
      for (const art of snapshot.artifacts ?? []) {
        events.push({
          id: art.artifact_id,
          type: 'artifact',
          timestamp: '',
          thread_id: threadId,
          agent_id: '',
          agent_name: resolveAgent(null),
          artifact_id: art.artifact_id,
          filename: art.filename,
          content: art.content,
          complete: art.complete,
        });
      }

      // Step 2: Hydrate plan entries
      if (snapshot.plan?.length) {
        events.push({
          id: `plan-hydrated-${threadId}-${snapshot.last_sequence}`,
          type: 'plan_update',
          timestamp: '',
          thread_id: threadId,
          agent_id: '',
          agent_name: '',
          entries: snapshot.plan.map((e, i) => ({
            id: `plan-entry-${i}`,
            content: e.content,
            status: e.status,
            priority: e.priority,
          })),
        });
      }

      // Hydrate Zustand store — also updates WS lastSequence
      appStore.getState().hydrateThreadEvents(threadId, events, snapshot.last_sequence);

      // Step 1: Hydrate pending permissions — merge by thread_id
      // Remove stale entries for this thread, then add the snapshot's
      // permissions. This preserves permissions from other open threads.
      {
        const currentQueue = appStore.getState().permissionQueue;
        const otherThreads = currentQueue.filter((p) => p.thread_id !== threadId);

        if (snapshot.pending_permissions?.length) {
          const waitingAgent = (snapshot.agents ?? []).find(
            (a) => a.state === 'input_required',
          );
          const permAgentId = waitingAgent?.agent_id ?? '';
          const permAgentName = waitingAgent
            ? agentNames[waitingAgent.agent_id] || waitingAgent.agent_id
            : '';
          const mapped: PermissionRequest[] = snapshot.pending_permissions.map(
            (perm: _PermissionSnapshot) => ({
              id: perm.request_id,
              thread_id: threadId,
              agent_id: permAgentId,
              agent_name: permAgentName,
              tool_name: perm.tool_call ?? '',
              tool_kind: 'other' as const,
              message: perm.description,
              options: perm.options.map((o) => ({
                id: o.option_id,
                kind: o.kind,
                label: o.name,
              })),
            }),
          );
          appStore.getState().setPermissionQueue([...otherThreads, ...mapped]);
        } else {
          // No permissions for this thread — clear stale entries only
          appStore.getState().setPermissionQueue(otherThreads);
        }
      }

      // Step 6: Update thread list cache with snapshot status
      queryClient.setQueryData<ThreadSummary[]>(queryKeys.threads.list(), (prev) => {
        if (!prev) return prev;
        return prev.map((t) =>
          t.thread_id === threadId ? { ...t, status: snapshot.status } : t,
        );
      });

      return { events, lastSequence: snapshot.last_sequence };
    },
    staleTime: Infinity,
    enabled: !!threadId && !hasEvents,
  });
}
