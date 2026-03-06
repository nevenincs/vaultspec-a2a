import { useQuery } from '@tanstack/react-query';
import { restClient } from '../api/rest-client';
import { queryKeys } from './query-keys';

export function useThreadMetadataQuery(threadId: string | null) {
  return useQuery({
    queryKey: queryKeys.threads.metadata(threadId ?? ''),
    queryFn: () => {
      if (!threadId) throw new Error('No threadId');
      return restClient.getThreadMetadata(threadId);
    },
    enabled: !!threadId,
    staleTime: 60_000,
  });
}
