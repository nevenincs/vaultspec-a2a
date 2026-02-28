<script lang="ts">
  import MarkdownRenderer from '$lib/components/markdown/MarkdownRenderer.svelte';
  import type { ThreadMessage } from '$lib/stores/agent-state.svelte';

  let {
    message,
    isUser = false,
  }: {
    message: ThreadMessage;
    isUser?: boolean;
  } = $props();

  const timestamp = $derived(
    new Date(message.timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    }),
  );

  const streaming = $derived(
    message.finish_reason === null && message.role !== 'thought',
  );
</script>

{#if isUser}
  <!-- User bubble — same capsule shell as agent, grey left bar -->
  <div class="px-4 py-1.5">
    <div
      class="rounded-ui border-border/40 bg-oxide-terminal-bg flex overflow-hidden border"
    >
      <div class="bg-muted-foreground w-[0.1875rem] shrink-0"></div>
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2 px-4 pt-2.5 pb-1">
          <span
            class="text-muted-foreground font-mono text-[0.6875rem] font-bold tracking-wider uppercase"
          >
            User
          </span>
          <span class="text-muted-foreground font-mono text-[0.625rem] opacity-80">
            {timestamp}
          </span>
        </div>
        <div class="px-4 pb-3">
          <div class="font-mono text-[0.8125rem]">
            <MarkdownRenderer content={message.content} {streaming} />
          </div>
        </div>
      </div>
    </div>
  </div>
{:else}
  <!-- Agent message — rendered inside agent capsule, no outer shell -->
  <div class="py-1">
    <div class="font-mono text-[0.8125rem]">
      <MarkdownRenderer content={message.content} {streaming} />
    </div>
  </div>
{/if}
