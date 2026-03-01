import { useMutation } from '@tanstack/react-query';
import { restClient } from '../api/rest-client';
import { appStore } from '../store/app-store';
import { log } from '../utils/logger';

interface RespondToPermissionArgs {
  requestId: string;
  optionId: string;
}

export function useRespondToPermission() {
  return useMutation({
    mutationFn: ({ requestId, optionId }: RespondToPermissionArgs) =>
      restClient.respondToPermission(requestId, { option_id: optionId }),

    onMutate: ({ requestId }) => {
      // Optimistic removal from Zustand queue
      appStore.getState().removePermission(requestId);
    },

    onError: (err, { requestId }) => {
      log.error('api.permission', `Failed to respond to permission ${requestId}`, err);
    },
  });
}
