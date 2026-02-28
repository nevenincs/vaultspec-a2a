<script lang="ts">
  import { page } from '$app/state';
  import { wsClient } from '$lib/api/websocket.svelte';
  import { agentState } from '$lib/stores';
  import { Button } from '$lib/components/ui/button';
  import { sendMessage } from '$lib/api/rest';
  import MarkdownRenderer from '$lib/components/markdown/MarkdownRenderer.svelte';
  import ThoughtBlock from '$lib/components/message/ThoughtBlock.svelte';
  import ToolCallCard from '$lib/components/tool-call/ToolCallCard.svelte';
  import ArtifactViewer from '$lib/components/artifact/ArtifactViewer.svelte';
  import type { ToolCallSnapshot } from '$lib/api/types';

  const threadId = $derived(page.params.id ?? '');
  const thread = $derived(agentState.threads.get(threadId));
  const isWorking = $derived(thread?.lifecycleState === 'working');
  const needsInput = $derived(thread?.lifecycleState === 'input_required');

  let messageInput = $state('');
  let scrollEl: HTMLDivElement | undefined;
  let atBottom = $state(true);

  // Subscribe/unsubscribe when navigating between threads
  $effect(() => {
    const id = threadId;
    wsClient.send({ type: 'subscribe', thread_ids: [id], request_id: null });
    return () => {
      wsClient.send({ type: 'unsubscribe', thread_ids: [id], request_id: null });
    };
  });

  // Auto-scroll when new stream items arrive (only if already at bottom)
  $effect(() => {
    // Create a dependency on stream length
    const _dep = thread?.streamItems.length;
    if (atBottom && scrollEl) {
      scrollEl.scrollTop = scrollEl.scrollHeight;
    }
  });

  function onScroll(): void {
    if (!scrollEl) return;
    const dist = scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight;
    atBottom = dist < 120;
  }

  function scrollToBottom(): void {
    if (!scrollEl) return;
    scrollEl.scrollTo({ top: scrollEl.scrollHeight, behavior: 'smooth' });
    atBottom = true;
  }

  async function handleSend(): Promise<void> {
    if (!messageInput.trim()) return;
    const content = messageInput;
    messageInput = '';
    await sendMessage(threadId, { content, agent_id: null });
  }

  function handleKeydown(e: KeyboardEvent): void {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
  }

  // Svelte action: auto-grow textarea up to 200px
  function autoGrow(node: HTMLTextAreaElement) {
    function resize() {
      node.style.height = 'auto';
      node.style.height = Math.min(node.scrollHeight, 200) + 'px';
    }
    node.addEventListener('input', resize);
    resize();
    return { destroy: () => node.removeEventListener('input', resize) };
  }
</script>

<div class="relative flex h-full flex-1 flex-col">
  <!-- Chronological event stream -->
  <div class="flex-1 overflow-y-auto p-4" bind:this={scrollEl} onscroll={onScroll}>
    {#if thread && thread.streamItems.length > 0}
      {#each thread.streamItems as item (item.id)}
        {#if item.kind === 'message'}
          {@const msg = thread.messages.find((m) => m.message_id === item.id)}
          {#if msg}
            {#if msg.role === 'thought'}
              <ThoughtBlock content={msg.content} agentId={msg.agent_id} />
            {:else}
              <div class="mb-4">
                <div class="text-muted-foreground mb-1 text-xs">
                  {msg.role}{msg.agent_id ? ` · ${msg.agent_id}` : ''}
                </div>
                <div
                  class="rounded-lg border p-3 text-sm
                    {msg.role === 'user'
                    ? 'bg-primary/5 border-primary/20 ml-8'
                    : 'mr-8'}"
                >
                  <MarkdownRenderer
                    content={msg.content}
                    streaming={msg.finish_reason === null && msg.role === 'assistant'}
                  />
                </div>
              </div>
            {/if}
          {/if}
        {:else if item.kind === 'tool'}
          {@const tc = thread.toolCalls.get(item.id)}
          {#if tc}
            <ToolCallCard toolCall={tc as ToolCallSnapshot} />
          {/if}
        {:else if item.kind === 'artifact'}
          {@const art = thread.artifacts.get(item.id)}
          {#if art}
            <ArtifactViewer artifact={art} />
          {/if}
        {/if}
      {/each}

      <!-- Working indicator -->
      {#if isWorking}
        <div class="text-muted-foreground mb-4 flex items-center gap-2 text-sm">
          <span class="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500"
          ></span>
          Working...
        </div>
      {/if}
    {:else if thread}
      <div
        class="text-muted-foreground flex h-full items-center justify-center text-sm"
      >
        Waiting for agent response...
      </div>
    {:else}
      <div
        class="text-muted-foreground flex h-full items-center justify-center text-sm"
      >
        Loading thread...
      </div>
    {/if}
  </div>

  <!-- New messages badge -->
  {#if !atBottom}
    <button
      class="bg-primary text-primary-foreground absolute right-6 bottom-20 z-10 rounded-full px-3 py-1 text-xs shadow-lg"
      onclick={scrollToBottom}
    >
      ▼ New messages
    </button>
  {/if}

  <!-- Input bar -->
  <div class="flex gap-2 border-t p-3">
    <textarea
      class="border-input bg-background min-h-[40px] flex-1 resize-none rounded-md border px-3 py-2 text-sm focus:outline-none"
      placeholder={needsInput
        ? 'Agent needs your input...'
        : isWorking
          ? 'Agent is working... (Ctrl+Enter to interrupt)'
          : 'Send a message (Ctrl+Enter)'}
      bind:value={messageInput}
      onkeydown={handleKeydown}
      use:autoGrow
    ></textarea>
    {#if isWorking}
      <Button
        variant="outline"
        size="sm"
        class="self-end"
        onclick={() => {
          /* TODO: emit stop command via wsClient */
        }}
      >
        Stop
      </Button>
    {/if}
    <Button class="self-end" onclick={handleSend} disabled={!messageInput.trim()}
      >Send</Button
    >
  </div>
</div>
