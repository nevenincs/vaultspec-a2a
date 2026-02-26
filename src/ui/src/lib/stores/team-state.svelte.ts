// ---------------------------------------------------------------------------
// Team state store — Svelte 5 Runes
// ---------------------------------------------------------------------------

import { type AgentSummary, type TeamStatusEvent } from '$lib/api/types';

// ---------------------------------------------------------------------------
// Team state store
// ---------------------------------------------------------------------------

export class TeamStateStore {
  agents: AgentSummary[] = $state([]);
  activeThreadIds: string[] = $state([]);

  applyTeamStatus(event: TeamStatusEvent): void {
    this.agents = [...event.agents];
    this.activeThreadIds = [...event.active_thread_ids];
  }
}

// ---------------------------------------------------------------------------
// Singleton store instance
// ---------------------------------------------------------------------------

export const teamState = new TeamStateStore();
