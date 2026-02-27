<script lang="ts">
  import type { ToolCallContentDiff } from '$lib/api/types';

  let { diff }: { diff: ToolCallContentDiff } = $props();
</script>

<!-- Placeholder: will use diff2html when installed -->
<div class="rounded border p-3 font-mono text-xs">
  <div class="text-muted-foreground mb-1">{diff.path}</div>
  {#if diff.old_text}
    <pre class="mb-1 rounded bg-red-500/10 p-1 text-red-500">- {diff.old_text}</pre>
  {/if}
  <pre class="rounded bg-green-500/10 p-1 text-green-500">+ {diff.new_text}</pre>
</div>
