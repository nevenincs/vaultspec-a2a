import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30s default; hooks override per-endpoint
      gcTime: 5 * 60 * 1000, // 5min
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});
