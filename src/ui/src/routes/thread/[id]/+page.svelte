<script lang="ts">
  import { page } from '$app/state';
  import { onMount, onDestroy } from 'svelte';
  import * as Card from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import { Button } from '$lib/components/ui/button';
  import { Separator } from '$lib/components/ui/separator';
  import { Textarea } from '$lib/components/ui/textarea';
  import { agentState, permissionQueue, type ThreadState } from '$lib/stores';
  import { sendMessage, getThreadState } from '$lib/api/rest';

  let threadId = $derived(page.params.id ?? '');
  let thread: ThreadState = $derived(agentState.getOrCreateThread(threadId));
  let messageInput = $state('');

  // Permission modal state
  let currentPermission = $derived(permissionQueue.current);
  let showPermission = $derived(
    currentPermission !== null && currentPermission.thread_id === threadId,
  );

  async function handleSendMessage(): Promise<void> {
    if (!messageInput.trim()) return;
    const content = messageInput;
    messageInput = '';
    await sendMessage(threadId, { content, agent_id: null });
  }

  async function handleKeydown(e: KeyboardEvent): Promise<void> {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      await handleSendMessage();
    }
  }

  async function handlePermissionRespond(optionId: string): Promise<void> {
    await permissionQueue.respond(optionId);
  }

  onMount(async () => {
    // Load initial state via REST snapshot
    try {
      const snapshot = await getThreadState(threadId);
      agentState.restoreFromSnapshot(snapshot);
    } catch {
      // Thread may not exist yet
    }
  });
</script>

<div class="flex h-full flex-col">
  <!-- Thread header -->
  <header class="border-border flex items-center gap-3 border-b px-6 py-4">
    <a href="/" class="text-muted-foreground hover:text-foreground">&larr;</a>
    <h2 class="text-lg font-semibold">Thread {threadId}</h2>
    {#if thread.lifecycleState}
      <Badge variant="outline">{thread.lifecycleState}</Badge>
    {/if}
    {#if thread.nodeName}
      <span class="text-muted-foreground text-sm">{thread.nodeName}</span>
    {/if}
  </header>

  <!-- Message stream -->
  <div class="flex-1 space-y-4 overflow-y-auto p-6">
    {#each thread.messages as message (message.message_id)}
      <div class="flex {message.role === 'user' ? 'justify-end' : 'justify-start'}">
        <Card.Root
          class="max-w-[80%] {message.role === 'thought'
            ? 'border-dashed opacity-70'
            : ''}"
        >
          <Card.Header class="pb-1">
            <div class="flex items-center gap-2">
              <Badge variant="secondary" class="text-xs">
                {message.role}
              </Badge>
              <span class="text-muted-foreground text-xs">
                {message.timestamp}
              </span>
            </div>
          </Card.Header>
          <Card.Content>
            <pre class="text-sm whitespace-pre-wrap">{message.content}</pre>
          </Card.Content>
        </Card.Root>
      </div>
    {/each}

    <!-- Tool calls -->
    {#each [...thread.toolCalls.values()] as toolCall (toolCall.tool_call_id)}
      <Card.Root class="border-l-primary/50 border-l-4">
        <Card.Header class="pb-2">
          <div class="flex items-center gap-2">
            <Card.Title class="text-sm">{toolCall.title}</Card.Title>
            <Badge variant="outline" class="text-xs">{toolCall.kind}</Badge>
            <Badge variant="secondary" class="text-xs">{toolCall.status}</Badge>
          </div>
        </Card.Header>
        {#if toolCall.locations.length > 0}
          <Card.Content class="pt-0">
            <p class="text-muted-foreground text-xs">
              {toolCall.locations
                .map((l) => `${l.path}${l.line ? `:${l.line}` : ''}`)
                .join(', ')}
            </p>
          </Card.Content>
        {/if}
      </Card.Root>
    {/each}

    <!-- Artifacts -->
    {#each [...thread.artifacts.values()] as artifact (artifact.artifact_id)}
      <Card.Root>
        <Card.Header class="pb-2">
          <div class="flex items-center gap-2">
            <Card.Title class="text-sm">{artifact.filename}</Card.Title>
            {#if artifact.complete}
              <Badge variant="default" class="text-xs">Complete</Badge>
            {:else}
              <Badge variant="outline" class="text-xs">Streaming...</Badge>
            {/if}
          </div>
        </Card.Header>
        <Card.Content>
          <pre
            class="bg-muted max-h-60 overflow-auto rounded p-3 text-xs">{artifact.content}</pre>
        </Card.Content>
      </Card.Root>
    {/each}
  </div>

  <!-- Plan entries -->
  {#if thread.plan.length > 0}
    <Separator />
    <div class="px-6 py-2">
      <p class="text-muted-foreground mb-1 text-xs font-medium">Plan</p>
      <div class="space-y-1">
        {#each thread.plan as entry}
          <div class="flex items-center gap-2 text-sm">
            <Badge variant="outline" class="text-xs">{entry.status}</Badge>
            <span>{entry.content}</span>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Permission modal overlay -->
  {#if showPermission && currentPermission}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <Card.Root class="w-full max-w-md">
        <Card.Header>
          <Card.Title>Permission Required</Card.Title>
          <Card.Description>{currentPermission.description}</Card.Description>
        </Card.Header>
        <Card.Content>
          <div class="flex flex-wrap gap-2">
            {#each currentPermission.options as option (option.option_id)}
              <Button
                variant={option.kind.startsWith('allow') ? 'default' : 'destructive'}
                onclick={() => handlePermissionRespond(option.option_id)}
              >
                {option.name}
              </Button>
            {/each}
          </div>
        </Card.Content>
      </Card.Root>
    </div>
  {/if}

  <!-- Input bar -->
  <Separator />
  <div class="px-6 py-4">
    <div class="flex gap-2">
      <Textarea
        bind:value={messageInput}
        placeholder="Type a message..."
        class="min-h-10 resize-none"
        onkeydown={handleKeydown}
      />
      <Button onclick={handleSendMessage}>Send</Button>
    </div>
  </div>
</div>
