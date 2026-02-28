<script lang="ts">
  import type { ToolCallSnapshot, ToolCallContent } from '$lib/api/types';
  import * as Card from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import DiffViewer from '$lib/components/diff/DiffViewer.svelte';
  import TerminalOutput from '$lib/components/terminal/TerminalOutput.svelte';
  import MarkdownRenderer from '$lib/components/markdown/MarkdownRenderer.svelte';
  import * as Collapsible from '$lib/components/ui/collapsible';

  let { toolCall }: { toolCall: ToolCallSnapshot } = $props();

  const statusVariant = $derived(
    toolCall.status === 'completed'
      ? ('secondary' as const)
      : toolCall.status === 'failed'
        ? ('destructive' as const)
        : ('default' as const),
  );

  const hasContent = $derived(toolCall.content && toolCall.content.length > 0);

  let contentOpen = $state(false);

  function renderContent(item: ToolCallContent) {
    return item;
  }
</script>

<Card.Root class="mb-3">
  <div class="flex items-center justify-between p-3">
    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-2">
        <span class="text-sm font-medium">{toolCall.title}</span>
        <Badge variant={statusVariant}>{toolCall.status}</Badge>
      </div>
      {#if toolCall.locations.length > 0}
        <div class="text-muted-foreground mt-0.5 truncate text-xs">
          {toolCall.locations
            .map((l) => (l.line ? `${l.path}:${l.line}` : l.path))
            .join(', ')}
        </div>
      {/if}
    </div>
  </div>

  {#if hasContent}
    <Collapsible.Root bind:open={contentOpen}>
      <Collapsible.Trigger
        class="text-muted-foreground hover:bg-accent/50 w-full border-t px-3 py-1.5 text-left text-xs"
      >
        {contentOpen ? '▼' : '▶'}
        {toolCall.content.length} output block{toolCall.content.length > 1 ? 's' : ''}
      </Collapsible.Trigger>
      <Collapsible.Content>
        <div class="space-y-2 border-t p-3 pt-2">
          {#each toolCall.content as item (renderContent(item))}
            {#if item.content_type === 'diff'}
              <DiffViewer diff={item} />
            {:else if item.content_type === 'terminal'}
              <TerminalOutput terminalId={item.terminal_id} />
            {:else if item.content_type === 'text'}
              <div class="text-sm">
                <MarkdownRenderer content={item.text} />
              </div>
            {/if}
          {/each}
        </div>
      </Collapsible.Content>
    </Collapsible.Root>
  {/if}
</Card.Root>
