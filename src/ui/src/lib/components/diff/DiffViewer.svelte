<script lang="ts">
  import * as Card from '$lib/components/ui/card';
  import type { ToolCallContentDiff } from '$lib/api/types';

  let { diff }: { diff: ToolCallContentDiff } = $props();
</script>

<Card.Root>
  <Card.Header class="pb-2">
    <Card.Title class="font-mono text-sm">{diff.path}</Card.Title>
  </Card.Header>
  <Card.Content>
    <!-- Deferred: will use CodeMirror merge view for proper diff rendering -->
    {#if diff.old_text}
      <div class="mb-2">
        <p class="text-destructive mb-1 text-xs font-medium">Removed</p>
        <pre
          class="bg-destructive/10 rounded p-3 font-mono text-xs">{diff.old_text}</pre>
      </div>
    {/if}
    <div>
      <p class="mb-1 text-xs font-medium text-green-600 dark:text-green-400">Added</p>
      <pre class="rounded bg-green-500/10 p-3 font-mono text-xs">{diff.new_text}</pre>
    </div>
  </Card.Content>
</Card.Root>
