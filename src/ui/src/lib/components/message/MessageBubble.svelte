<script lang="ts">
  import type { MessageSnapshot } from '$lib/api/types';
  import * as Card from '$lib/components/ui/card';

  let { message }: { message: MessageSnapshot } = $props();
</script>

<Card.Root
  class="mb-3 p-3 {message.role === 'user'
    ? 'bg-primary text-primary-foreground ml-auto max-w-[80%]'
    : 'mr-auto max-w-[80%]'}"
>
  {#if message.agent_id}
    <div class="text-muted-foreground mb-1 text-xs">{message.agent_id}</div>
  {/if}
  <div class="text-sm whitespace-pre-wrap">{message.content}</div>
</Card.Root>
