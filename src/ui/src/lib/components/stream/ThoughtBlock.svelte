<script lang="ts">
  import { ChevronRight, ChevronDown } from '@lucide/svelte';

  let {
    content,
  }: {
    content: string;
  } = $props();

  let expanded = $state(false);
</script>

<div class="py-0.5">
  <button
    onclick={() => (expanded = !expanded)}
    class="text-muted-foreground hover:text-foreground flex w-full items-center gap-1.5 text-left text-[0.75rem] transition-colors"
  >
    {#if expanded}
      <ChevronDown class="h-3 w-3 shrink-0" />
    {:else}
      <ChevronRight class="h-3 w-3 shrink-0" />
    {/if}
    <span class="italic">Thinking&hellip;</span>
  </button>
  {#if expanded}
    <div class="rounded-terminal border-border/50 bg-muted/20 mt-1 border px-3 py-2">
      <p
        class="text-muted-foreground font-mono text-[0.75rem] whitespace-pre-wrap italic"
      >
        {content}
      </p>
    </div>
  {/if}
</div>
