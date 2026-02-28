<script lang="ts">
  import { Loader2, Check, X, Circle } from '@lucide/svelte';
  import type { ThreadToolCall } from '$lib/stores/agent-state.svelte';
  import type { InspectorTarget } from '$lib/data/types';

  let {
    toolCall,
    oninspect,
  }: {
    toolCall: ThreadToolCall;
    oninspect: (target: InspectorTarget) => void;
  } = $props();

  const borderColor = $derived(
    toolCall.status === 'failed' ? 'border-status-error/20' : 'border-border/50',
  );

  // Primary location for display (first location entry)
  const primaryLocation = $derived(toolCall.locations[0] ?? null);

  // First text content for inline preview when no location
  const firstTextContent = $derived(
    toolCall.content.find((c) => c.content_type === 'text') as
      | { content_type: 'text'; text: string }
      | undefined,
  );

  function handleInspect() {
    // Build a synthetic ToolCallEvent-shaped object for the inspector
    oninspect({
      type: 'tool_call',
      event: {
        id: toolCall.tool_call_id,
        type: 'tool_call',
        timestamp: new Date().toISOString(),
        thread_id: '',
        agent_id: '',
        agent_name: '',
        tool_call_id: toolCall.tool_call_id,
        tool_name: toolCall.title,
        tool_kind: toolCall.kind,
        status: toolCall.status,
        location: primaryLocation
          ? { file: primaryLocation.path, line: primaryLocation.line ?? undefined }
          : undefined,
      },
    });
  }
</script>

<div class="py-0.5">
  <button
    onclick={handleInspect}
    class="group rounded-terminal w-full border {borderColor} bg-muted/10 hover:bg-muted/20 px-3 py-1.5 text-left transition-colors"
  >
    <div class="flex items-center gap-2">
      <!-- Status icon -->
      {#if toolCall.status === 'in_progress'}
        <Loader2 class="text-status-info/70 h-3.5 w-3.5 shrink-0 animate-spin" />
      {:else if toolCall.status === 'completed'}
        <Check class="text-status-success/70 h-3.5 w-3.5 shrink-0" />
      {:else if toolCall.status === 'failed'}
        <X class="text-status-error/70 h-3.5 w-3.5 shrink-0" />
      {:else}
        <Circle class="text-muted-foreground/40 h-3.5 w-3.5 shrink-0" />
      {/if}

      <!-- Tool name -->
      <span class="text-muted-foreground/60 font-mono text-[0.75rem]">
        {toolCall.title}
      </span>

      <!-- Location hint -->
      {#if primaryLocation}
        <span class="text-muted-foreground/40 truncate font-mono text-[0.625rem]">
          {primaryLocation.path}{primaryLocation.line != null
            ? `:${primaryLocation.line}`
            : ''}
        </span>
      {:else if firstTextContent}
        <span
          class="text-muted-foreground/40 flex-1 truncate font-mono text-[0.625rem]"
        >
          {firstTextContent.text.slice(0, 60)}
        </span>
      {/if}
    </div>
  </button>
</div>
