<script lang="ts">
  import type { ToolCallSnapshot } from '$lib/api/types';
  import * as Card from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';

  let { toolCall }: { toolCall: ToolCallSnapshot } = $props();

  const statusVariant = $derived(
    toolCall.status === 'completed'
      ? ('secondary' as const)
      : toolCall.status === 'failed'
        ? ('destructive' as const)
        : ('default' as const),
  );
</script>

<Card.Root class="mb-3 p-3">
  <div class="flex items-center justify-between">
    <span class="text-sm font-medium">{toolCall.title}</span>
    <Badge variant={statusVariant}>{toolCall.status}</Badge>
  </div>
  {#if toolCall.locations.length > 0}
    <div class="text-muted-foreground mt-1 text-xs">
      {toolCall.locations
        .map((l) => (l.line ? `${l.path}:${l.line}` : l.path))
        .join(', ')}
    </div>
  {/if}
</Card.Root>
