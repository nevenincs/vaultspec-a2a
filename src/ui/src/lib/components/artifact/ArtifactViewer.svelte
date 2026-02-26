<script lang="ts">
  import * as Card from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';

  let {
    filename,
    content,
    complete,
  }: {
    filename: string;
    content: string;
    complete: boolean;
  } = $props();
</script>

<Card.Root>
  <Card.Header class="pb-2">
    <div class="flex items-center gap-2">
      <Card.Title class="font-mono text-sm">{filename}</Card.Title>
      {#if complete}
        <Badge variant="default" class="text-xs">Complete</Badge>
      {:else}
        <Badge variant="outline" class="text-xs">Streaming...</Badge>
      {/if}
    </div>
  </Card.Header>
  <Card.Content>
    <pre
      class="bg-muted max-h-80 overflow-auto rounded p-3 font-mono text-xs">{content}</pre>
  </Card.Content>
</Card.Root>
