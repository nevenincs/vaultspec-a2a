<script lang="ts">
  import { Badge } from '$lib/components/ui/badge';
  import { Checkbox } from '$lib/components/ui/checkbox';
  import type { PlanEntry } from '$lib/api/types';
  import { PlanEntryStatus } from '$lib/api/types';

  let { entries }: { entries: PlanEntry[] } = $props();
</script>

<div class="space-y-2">
  {#each entries as entry, i (i)}
    <div class="flex items-center gap-3">
      <Checkbox checked={entry.status === PlanEntryStatus.COMPLETED} disabled />
      <span
        class="flex-1 text-sm {entry.status === PlanEntryStatus.COMPLETED
          ? 'text-muted-foreground line-through'
          : ''}"
      >
        {entry.content}
      </span>
      <Badge
        variant={entry.status === PlanEntryStatus.IN_PROGRESS ? 'default' : 'outline'}
        class="text-xs"
      >
        {entry.status}
      </Badge>
      <Badge variant="secondary" class="text-xs">{entry.priority}</Badge>
    </div>
  {/each}
</div>
