<script lang="ts">
  let {
    terminalId,
    content = '',
  }: {
    terminalId: string;
    content?: string;
  } = $props();
</script>

<!-- Placeholder: will use xterm.js when installed -->
<div class="rounded bg-black p-3 font-mono text-xs text-green-400">
  <div class="text-muted-foreground mb-1 text-[10px]">Terminal: {terminalId}</div>
  <pre class="whitespace-pre-wrap">{content}</pre>
</div>
