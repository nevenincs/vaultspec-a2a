<script lang="ts">
  import { goto } from '$app/navigation';
  import { Button } from '$lib/components/ui/button';
  import { createThread } from '$lib/api/rest';

  async function handleNewThread(): Promise<void> {
    const response = await createThread({
      title: null,
      initial_message: '',
      provider: null,
      model: null,
    });
    await goto(`/thread/${response.thread_id}`);
  }
</script>

<div class="flex flex-1 items-center justify-center">
  <div class="space-y-4 text-center">
    <h2 class="text-xl font-semibold">Start a conversation</h2>
    <p class="text-muted-foreground">Create a new thread to get started</p>
    <Button onclick={handleNewThread}>+ New Thread</Button>
  </div>
</div>
