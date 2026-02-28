<script lang="ts">
  import * as Collapsible from '$lib/components/ui/collapsible';

  let {
    content,
    agentId = null,
  }: {
    content: string;
    agentId?: string | null;
  } = $props();

  let open = $state(false);
</script>

<Collapsible.Root bind:open class="mb-3 opacity-60">
  <Collapsible.Trigger
    class="text-muted-foreground flex cursor-pointer items-center gap-2 text-sm italic"
  >
    <span>{open ? '▼' : '▶'}</span>
    <span>Thinking{agentId ? ` (${agentId})` : ''}...</span>
  </Collapsible.Trigger>
  <Collapsible.Content>
    <div
      class="text-muted-foreground border-muted mt-1 rounded border-l-2 pl-3 text-sm italic"
    >
      {content}
    </div>
  </Collapsible.Content>
</Collapsible.Root>
