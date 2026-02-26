<script lang="ts">
  import * as Card from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import * as Tooltip from '$lib/components/ui/tooltip';
  import type { AgentSummary } from '$lib/api/types';

  let { agents }: { agents: AgentSummary[] } = $props();
</script>

<div class="space-y-2">
  {#each agents as agent (agent.agent_id)}
    <Card.Root class="p-3">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <Tooltip.Root>
            <Tooltip.Trigger>
              <span class="text-sm font-medium">{agent.node_name}</span>
            </Tooltip.Trigger>
            <Tooltip.Content>
              <p>{agent.agent_id}</p>
            </Tooltip.Content>
          </Tooltip.Root>
        </div>
        <div class="flex items-center gap-1">
          <Badge variant="outline" class="text-xs">{agent.state}</Badge>
          <Badge variant="secondary" class="text-xs">
            {agent.provider}/{agent.model}
          </Badge>
        </div>
      </div>
    </Card.Root>
  {/each}
</div>
