<script lang="ts">
  import * as Card from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import type { ThreadMessage } from '$lib/stores/agent-state.svelte';

  let { message }: { message: ThreadMessage } = $props();

  let isUser = $derived(message.role === 'user');
  let isThought = $derived(message.role === 'thought');
</script>

<div class="flex {isUser ? 'justify-end' : 'justify-start'}">
  <Card.Root class="max-w-[80%] {isThought ? 'border-dashed opacity-70' : ''}">
    <Card.Header class="pb-1">
      <div class="flex items-center gap-2">
        <Badge variant="secondary" class="text-xs">{message.role}</Badge>
        <span class="text-muted-foreground text-xs">{message.timestamp}</span>
        {#if message.finish_reason}
          <Badge variant="outline" class="text-xs">{message.finish_reason}</Badge>
        {/if}
      </div>
    </Card.Header>
    <Card.Content>
      <pre class="text-sm whitespace-pre-wrap">{message.content}</pre>
    </Card.Content>
  </Card.Root>
</div>
