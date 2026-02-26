<script lang="ts">
  import { goto } from '$app/navigation';
  import { Button } from '$lib/components/ui/button';
  import * as Card from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import { Skeleton } from '$lib/components/ui/skeleton';
  import { createThread, listThreads } from '$lib/api/rest';
  import type { ThreadSummary } from '$lib/api/types';

  let threads: ThreadSummary[] = $state([]);
  let loading = $state(true);

  async function loadThreads(): Promise<void> {
    try {
      const response = await listThreads();
      threads = response.threads;
    } finally {
      loading = false;
    }
  }

  async function handleNewThread(): Promise<void> {
    const response = await createThread({
      title: null,
      initial_message: 'Hello',
      provider: null,
      model: null,
    });
    await goto(`/thread/${response.thread_id}`);
  }

  $effect(() => {
    loadThreads();
  });
</script>

<div class="flex h-full flex-col">
  <header class="border-border flex items-center justify-between border-b px-6 py-4">
    <h2 class="text-xl font-semibold">Threads</h2>
    <Button onclick={handleNewThread}>New Thread</Button>
  </header>

  <div class="flex-1 overflow-y-auto p-6">
    {#if loading}
      <div class="space-y-3">
        {#each Array(3) as _}
          <Skeleton class="h-20 w-full" />
        {/each}
      </div>
    {:else if threads.length === 0}
      <div class="flex h-full items-center justify-center">
        <p class="text-muted-foreground">No threads yet. Create one to get started.</p>
      </div>
    {:else}
      <div class="space-y-3">
        {#each threads as thread (thread.thread_id)}
          <a href="/thread/{thread.thread_id}" class="block">
            <Card.Root class="hover:bg-accent/50 transition-colors">
              <Card.Header class="pb-2">
                <div class="flex items-center justify-between">
                  <Card.Title class="text-base">
                    {thread.title ?? thread.thread_id}
                  </Card.Title>
                  <Badge variant="outline">{thread.status}</Badge>
                </div>
              </Card.Header>
              <Card.Content>
                <p class="text-muted-foreground text-sm">
                  {#if thread.agent_state}
                    Agent: {thread.agent_state}
                  {/if}
                </p>
              </Card.Content>
            </Card.Root>
          </a>
        {/each}
      </div>
    {/if}
  </div>
</div>
