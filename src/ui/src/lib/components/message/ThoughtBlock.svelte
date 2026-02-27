<script lang="ts">
  import type { MessageSnapshot } from '$lib/api/types';
  import * as Collapsible from '$lib/components/ui/collapsible';

  let { message }: { message: MessageSnapshot } = $props();
  let open = $state(false);
</script>

<Collapsible.Root bind:open class="mb-3 opacity-60">
  <Collapsible.Trigger
    class="text-muted-foreground flex cursor-pointer items-center gap-2 text-sm italic"
  >
    <span>{open ? '▼' : '▶'}</span>
    <span>Thinking...</span>
  </Collapsible.Trigger>
  <Collapsible.Content>
    <div
      class="text-muted-foreground border-muted mt-1 rounded border-l-2 pl-3 text-sm italic"
    >
      {message.content}
    </div>
  </Collapsible.Content>
</Collapsible.Root>
