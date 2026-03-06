import { useQuery, useMutation } from '@tanstack/react-query';
import { useStore } from 'zustand';
import { restClient } from '../api/rest-client';
import { mapThreadSummary } from '../api/mappers';
import { wsClient } from '../api/websocket-client';
import { appStore } from '../store/app-store';
import { queryClient } from './query-client';
import { queryKeys } from './query-keys';
import type { ThreadSummary, TeamPreset } from '../data/types';
import { log } from '../utils/logger';

export function useThreadsQuery() {
  return useQuery({
    queryKey: queryKeys.threads.list(),
    queryFn: async () => {
      const res = await restClient.listThreads();
      return res.threads.map(mapThreadSummary);
    },
    staleTime: 30_000,
  });
}

interface CreateThreadOptions {
  message: string;
  preset?: TeamPreset;
  repo?: string;
  branch?: string;
  featureTag?: string;
}

export function useCreateThread() {
  const openPinned = useStore(appStore, (s) => s.openPinned);

  return useMutation({
    mutationFn: async (opts: CreateThreadOptions) => {
      const { message, preset, repo, branch, featureTag } = opts;
      return restClient.createThread({
        initial_message: message,
        title: message.slice(0, 40) + (message.length > 40 ? '...' : ''),
        team_preset: preset?.id,
        metadata: repo
          ? {
              workspace_root: repo,
              feature_tag: featureTag ?? '',
              source_branch: branch ?? '',
              nickname: '',
              source_repo: '',
              callee: '',
            }
          : undefined,
      });
    },
    onSuccess: (res, opts) => {
      const { message } = opts;
      const newThread: ThreadSummary = {
        thread_id: res.thread_id,
        title: message.slice(0, 40) + (message.length > 40 ? '...' : ''),
        agent_state: 'submitted',
        updated_at: new Date().toISOString(),
        nickname: res.nickname ?? undefined,
      };

      // Optimistic prepend to thread list cache
      queryClient.setQueryData<ThreadSummary[]>(queryKeys.threads.list(), (prev) =>
        prev ? [newThread, ...prev] : [newThread],
      );

      // Open as pinned tab + subscribe to WS events
      openPinned(res.thread_id);
      wsClient.subscribe([res.thread_id]);

      log.info('thread.create', `Thread created: ${res.thread_id}`);
    },
    onError: (err) => {
      log.error('api.thread', 'Failed to create thread', err);
    },
  });
}
