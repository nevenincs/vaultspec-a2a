<script lang="ts">
  let {
    content,
    streaming = false,
  }: {
    content: string;
    streaming?: boolean;
  } = $props();
</script>

<!-- Placeholder: will use @humanspeak/svelte-markdown when installed -->
<div class="prose prose-sm dark:prose-invert max-w-none">
  <div class="whitespace-pre-wrap">{content}</div>
  {#if streaming}
    <span
      class="bg-foreground ml-0.5 inline-block h-4 w-0.5 animate-pulse"
      aria-hidden="true"
    ></span>
  {/if}
</div>
