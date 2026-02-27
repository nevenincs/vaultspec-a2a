<script lang="ts">
  import type { PlanEntry } from '$lib/api/types';
  import { Badge } from '$lib/components/ui/badge';

  let { entries }: { entries: PlanEntry[] } = $props();
</script>

<div class="space-y-2">
  {#each entries as entry (entry.content)}
    <div class="flex items-center gap-2">
      <span class="text-sm">
        {entry.status === 'completed'
          ? '☑'
          : entry.status === 'in_progress'
            ? '■'
            : '☐'}
      </span>
      <span
        class="flex-1 text-sm {entry.status === 'completed'
          ? 'text-muted-foreground line-through'
          : ''}"
      >
        {entry.content}
      </span>
      <Badge
        variant={entry.priority === 'high'
          ? 'destructive'
          : entry.priority === 'low'
            ? 'outline'
            : 'secondary'}
        class="text-xs"
      >
        {entry.priority.toUpperCase()}
      </Badge>
    </div>
  {/each}
</div>
