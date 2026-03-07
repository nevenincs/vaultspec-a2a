import { useMutation } from '@tanstack/react-query';
import { restClient } from '../api/rest-client';
import { queryClient } from './query-client';
import { queryKeys } from './query-keys';
import { log } from '../utils/logger';
import type { ThreadSummary } from '../data/types';

export function useCancelThread() {
  return useMutation({
    mutationFn: (threadId: string) => restClient.cancelThread(threadId),

    onMutate: async (threadId) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.threads.list() });
      const previous = queryClient.getQueryData<ThreadSummary[]>(
        queryKeys.threads.list(),
      );

      // Optimistically set agent_state to cancelled
      queryClient.setQueryData<ThreadSummary[]>(queryKeys.threads.list(), (prev = []) =>
        prev.map((t) =>
          t.thread_id === threadId ? { ...t, agent_state: 'cancelled' as const } : t,
        ),
      );

      return { previous };
    },

    onError: (err, threadId, context) => {
      // Rollback on failure
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.threads.list(), context.previous);
      }
      log.error('api.cancel', `Failed to cancel thread ${threadId}`, err);
    },

    onSuccess: (_res, threadId) => {
      log.info('thread.cancel', `Thread ${threadId} cancelled`);
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.threads.list() });
    },
  });
}
