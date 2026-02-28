<script lang="ts">
  import { marked } from 'marked';

  let {
    content,
    streaming = false,
  }: {
    content: string;
    streaming?: boolean;
  } = $props();

  const html = $derived(marked.parse(content) as string);
</script>

<div class="prose prose-sm dark:prose-invert max-w-none break-words">
  <!-- eslint-disable-next-line svelte/no-at-html-tags -->
  {@html html}
  {#if streaming}
    <span
      class="bg-foreground ml-0.5 inline-block h-4 w-0.5 animate-pulse"
      aria-hidden="true"
    ></span>
  {/if}
</div>
