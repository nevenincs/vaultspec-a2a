<script lang="ts">
  import { page } from '$app/state';
  import { wsClient } from '$lib/api/websocket.svelte';
  import { agentState } from '$lib/stores';
  import { ScrollArea } from '$lib/components/ui/scroll-area';
  import { Button } from '$lib/components/ui/button';
  import { Badge } from '$lib/components/ui/badge';
  import { sendMessage } from '$lib/api/rest';

  const threadId = $derived(page.params.id ?? '');
  const thread = $derived(agentState.threads.get(threadId));

  let messageInput = $state('');

  // Subscribe/unsubscribe to thread events
  $effect(() => {
    const id = threadId;
    wsClient.send({ type: 'subscribe', thread_ids: [id], request_id: null });
    return () => {
      wsClient.send({ type: 'unsubscribe', thread_ids: [id], request_id: null });
    };
  });

  async function handleSend(): Promise<void> {
    if (!messageInput.trim()) return;
    await sendMessage(threadId, { content: messageInput, agent_id: null });
    messageInput = '';
  }
</script>

<div class="flex h-full flex-1 flex-col">
  <!-- Message stream -->
  <ScrollArea class="flex-1 p-4">
    {#if thread}
      {#each thread.messages as msg (msg.message_id)}
        <div class="mb-3 {msg.role === 'thought' ? 'italic opacity-60' : ''}">
          <div class="text-muted-foreground mb-1 text-xs">
            {msg.role}{msg.agent_id ? ` (${msg.agent_id})` : ''}
          </div>
          <div class="rounded-lg border p-3 text-sm">
            {msg.content}
          </div>
        </div>
      {/each}

      <!-- Tool calls inline -->
      {#each [...thread.toolCalls.values()] as tc (tc.tool_call_id)}
        <div class="mb-3 rounded-lg border p-3 text-sm">
          <div class="flex items-center justify-between">
            <span class="font-medium">{tc.title}</span>
            <Badge variant="secondary">{tc.status}</Badge>
          </div>
          <div class="text-muted-foreground text-xs">{tc.kind}</div>
          {#if tc.locations.length > 0}
            <div class="text-muted-foreground mt-1 text-xs">
              {tc.locations
                .map((l) => (l.line ? `${l.path}:${l.line}` : l.path))
                .join(', ')}
            </div>
          {/if}
        </div>
      {/each}

      <!-- Artifacts inline -->
      {#each [...thread.artifacts.values()] as artifact (artifact.artifact_id)}
        <div class="mb-3 rounded-lg border p-3 text-sm">
          <div class="flex items-center justify-between">
            <span class="font-medium">{artifact.filename}</span>
            <Badge variant={artifact.complete ? 'secondary' : 'default'}>
              {artifact.complete ? 'complete' : 'streaming...'}
            </Badge>
          </div>
        </div>
      {/each}
    {:else}
      <div class="text-muted-foreground flex h-full items-center justify-center">
        Loading thread...
      </div>
    {/if}
  </ScrollArea>

  <!-- Input bar -->
  <div class="flex gap-2 border-t p-3">
    <input
      type="text"
      class="flex-1 rounded-md border px-3 py-2 text-sm"
      placeholder="Type a message..."
      bind:value={messageInput}
      onkeydown={(e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          handleSend();
        }
      }}
    />
    <Button onclick={handleSend} disabled={!messageInput.trim()}>Send</Button>
  </div>
</div>
