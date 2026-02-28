<script lang="ts">
  import { goto } from '$app/navigation';
  import { Button } from '$lib/components/ui/button';
  import { createThread } from '$lib/api/rest';

  let messageInput = $state('');

  async function handleCreate(): Promise<void> {
    const msg = messageInput.trim();
    if (!msg) return;
    const response = await createThread({
      title: null,
      initial_message: msg,
      provider: null,
      model: null,
    });
    await goto(`/thread/${response.thread_id}`);
  }

  function handleKeydown(e: KeyboardEvent): void {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleCreate();
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

<div class="flex flex-1 items-center justify-center p-8">
  <div class="w-full max-w-xl space-y-4">
    <h2 class="text-center text-xl font-semibold">Start a conversation</h2>
    <p class="text-muted-foreground text-center text-sm">
      Describe your task and a new thread will be created.
    </p>
    <div class="flex gap-2">
      <textarea
        class="border-input bg-background min-h-[40px] flex-1 resize-none rounded-md border px-3 py-2 text-sm focus:outline-none"
        placeholder="What would you like to do? (Ctrl+Enter to start)"
        bind:value={messageInput}
        onkeydown={handleKeydown}
        use:autoGrow
      ></textarea>
      <Button class="self-end" onclick={handleCreate} disabled={!messageInput.trim()}>
        Start
      </Button>
    </div>
  </div>
</div>
