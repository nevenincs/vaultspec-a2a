<script lang="ts">
  let {
    content,
    streaming = false,
  }: {
    content: string;
    streaming?: boolean;
  } = $props();
</script>

<!-- Deferred: raw pre during streaming, will use Shiki for syntax highlighting on completion -->
<div class="prose prose-sm dark:prose-invert max-w-none">
  <pre class="text-sm whitespace-pre-wrap">{content}{#if streaming}<span
        class="animate-pulse">|</span
      >{/if}</pre>
</div>
