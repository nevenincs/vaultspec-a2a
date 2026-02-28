<script lang="ts">
  import { AlertTriangle } from '@lucide/svelte';

  let {
    message,
    code = null,
  }: {
    message: string;
    code?: string | null;
  } = $props();
</script>

<div class="px-4 py-1.5">
  <div
    class="rounded-ui border-status-error/30 bg-status-error/5 relative w-full border px-4 py-3 text-[0.8125rem]"
  >
    <div class="flex items-start gap-3">
      <AlertTriangle class="text-status-error mt-0.5 h-4 w-4 shrink-0" />
      <div class="min-w-0 flex-1">
        <p class="text-status-error font-medium">Error</p>
        <p class="text-foreground/80 mt-0.5">{message}</p>
        {#if code}
          <span class="text-muted-foreground/70 mt-1 block font-mono text-[0.6875rem]">
            Code: {code}
          </span>
        {/if}
      </div>
    </div>
  </div>
</div>
