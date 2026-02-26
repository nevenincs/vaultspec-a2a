<script lang="ts">
  import * as Card from '$lib/components/ui/card';
  import * as Collapsible from '$lib/components/ui/collapsible';
  import { Badge } from '$lib/components/ui/badge';
  import type { ThreadToolCall } from '$lib/stores/agent-state.svelte';

  let { toolCall }: { toolCall: ThreadToolCall } = $props();
  let open = $state(false);
</script>

<Collapsible.Root bind:open>
  <Card.Root class="border-l-primary/50 border-l-4">
    <Collapsible.Trigger class="w-full text-left">
      <Card.Header class="pb-2">
        <div class="flex items-center gap-2">
          <Card.Title class="text-sm">{toolCall.title}</Card.Title>
          <Badge variant="outline" class="text-xs">{toolCall.kind}</Badge>
          <Badge variant="secondary" class="text-xs">{toolCall.status}</Badge>
        </div>
        {#if toolCall.locations.length > 0}
          <p class="text-muted-foreground text-xs">
            {toolCall.locations
              .map((l) => `${l.path}${l.line ? `:${l.line}` : ''}`)
              .join(', ')}
          </p>
        {/if}
      </Card.Header>
    </Collapsible.Trigger>

    <Collapsible.Content>
      <Card.Content>
        {#each toolCall.content as block}
          {#if block.content_type === 'text'}
            <pre
              class="bg-muted rounded p-3 text-xs whitespace-pre-wrap">{block.text}</pre>
          {:else if block.content_type === 'diff'}
            <div class="bg-muted rounded p-3 text-xs">
              <p class="text-muted-foreground font-medium">{block.path}</p>
              <pre class="whitespace-pre-wrap">{block.new_text}</pre>
            </div>
          {:else if block.content_type === 'terminal'}
            <div class="bg-muted rounded p-3 text-xs">
              <p class="text-muted-foreground font-medium">
                Terminal: {block.terminal_id}
              </p>
            </div>
          {/if}
        {/each}
      </Card.Content>
    </Collapsible.Content>
  </Card.Root>
</Collapsible.Root>
