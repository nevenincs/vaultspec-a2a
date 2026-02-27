<script lang="ts">
  import type { AgentSummary } from '$lib/api/types';

  let { agents }: { agents: AgentSummary[] } = $props();
</script>

<div class="space-y-1">
  <div
    class="text-muted-foreground mb-2 text-xs font-semibold tracking-wider uppercase"
  >
    Team Status
  </div>
  {#each agents as agent (agent.agent_id)}
    <div class="flex items-center gap-2 text-sm">
      <span
        class="h-2 w-2 rounded-full {agent.state === 'working'
          ? 'animate-pulse bg-blue-500'
          : agent.state === 'idle'
            ? 'bg-green-500'
            : agent.state === 'failed'
              ? 'bg-red-500'
              : 'bg-gray-400'}"
      ></span>
      <span class="flex-1 truncate">{agent.node_name}</span>
      <span class="text-muted-foreground text-xs">{agent.state}</span>
    </div>
  {/each}
</div>
