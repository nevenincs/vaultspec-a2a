import { useQuery } from '@tanstack/react-query';
import { restClient } from '../api/rest-client';
import { mapAgentSummary, mapTeamPreset } from '../api/mappers';
import { queryKeys } from './query-keys';

export function useTeamStatusQuery() {
  return useQuery({
    queryKey: queryKeys.team.status(),
    queryFn: async () => {
      const res = await restClient.getTeamStatus();
      return res.agents.map(mapAgentSummary);
    },
    staleTime: 10_000,
  });
}

export function useTeamPresetsQuery() {
  return useQuery({
    queryKey: queryKeys.team.presets(),
    queryFn: async () => {
      const res = await restClient.listTeamPresets();
      return res.presets.map(mapTeamPreset);
    },
    staleTime: 5 * 60 * 1000, // 5 minutes — near-static data
  });
}
