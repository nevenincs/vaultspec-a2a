<script lang="ts">
  import { onMount } from 'svelte';
  import { Terminal } from '@xterm/xterm';
  import { FitAddon } from '@xterm/addon-fit';

  let {
    terminalId,
    content = '',
  }: {
    terminalId: string;
    content?: string;
  } = $props();

  let containerEl: HTMLDivElement;
  let terminal: Terminal | undefined;
  let fitAddon: FitAddon | undefined;
  let lastContent = '';

  onMount(() => {
    terminal = new Terminal({
      cursorBlink: false,
      disableStdin: true,
      fontSize: 12,
      fontFamily: '"Cascadia Code", "Menlo", "Monaco", "Courier New", monospace',
      scrollback: 2000,
      rows: 12,
      convertEol: true,
    });
    fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(containerEl);
    fitAddon.fit();

    if (content) {
      terminal.write(content);
      lastContent = content;
    }

    const observer = new ResizeObserver(() => fitAddon?.fit());
    observer.observe(containerEl);

    return () => {
      observer.disconnect();
      terminal?.dispose();
    };
  });

  // Append only new content (streaming support)
  $effect(() => {
    if (terminal && content.length > lastContent.length) {
      terminal.write(content.slice(lastContent.length));
      lastContent = content;
    }
  });
</script>

<div class="terminal-wrapper overflow-hidden rounded border">
  <div class="border-b bg-zinc-950 px-2 py-1 font-mono text-[10px] text-zinc-500">
    terminal:{terminalId}
  </div>
  <div bind:this={containerEl} class="p-1"></div>
</div>
