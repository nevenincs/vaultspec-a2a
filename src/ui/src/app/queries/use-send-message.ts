import { useMutation } from '@tanstack/react-query';
import { restClient } from '../api/rest-client';
import { appStore } from '../store/app-store';
import { log } from '../utils/logger';
import type { UserMessageEvent } from '../data/types';

interface SendMessageArgs {
  threadId: string;
  content: string;
  agentId?: string;
}

export function useSendMessage() {
  return useMutation({
    mutationFn: ({ threadId, content, agentId }: SendMessageArgs) =>
      restClient.sendMessage(threadId, {
        content,
        agent_id: agentId ?? null,
      }),

    onMutate: ({ threadId, content }) => {
      // Optimistically append a user_message StreamEvent into Zustand
      const event: UserMessageEvent = {
        id: `user-${Date.now()}`,
        type: 'user_message',
        timestamp: new Date().toISOString(),
        thread_id: threadId,
        content,
      };

      appStore.setState((state) => {
        if (!state.streamEvents[threadId]) {
          state.streamEvents[threadId] = [];
        }
        state.streamEvents[threadId].push(event);
      });
    },

    onSuccess: (_res, { threadId }) => {
      log.info('thread.send', `Message sent to thread ${threadId}`);
    },

    onError: (err, { threadId }) => {
      log.error('api.send', `Failed to send message to ${threadId}`, err);
    },
  });
}
