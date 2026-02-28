<script lang="ts">
  import { appState } from '$lib/stores/app-state.svelte';
  import { threadState } from '$lib/stores/thread-state.svelte';

  const connDot = $derived(
    appState.connectionState === 'connected'
      ? 'bg-status-success'
      : appState.connectionState === 'reconnecting'
        ? 'bg-status-warning'
        : 'bg-status-error',
  );

  const connLabel = $derived(
    appState.connectionState === 'connected'
      ? 'Connected'
      : appState.connectionState === 'reconnecting'
        ? 'Reconnecting...'
        : 'Disconnected',
  );

  const barBg = $derived(
    appState.connectionState === 'reconnecting'
      ? 'bg-status-warning/5'
      : appState.connectionState === 'disconnected'
        ? 'bg-status-error/5'
        : '',
  );

  const activeCount = $derived(
    threadState.threads.filter(
      (t) => t.agent_state === 'working' || t.agent_state === 'submitted',
    ).length,
  );

  const heartbeatAgo = $derived(
    ((Date.now() - appState.lastHeartbeat) / 1000).toFixed(1),
  );
</script>

<div
  class="border-border text-oxide-metadata bg-oxide-sidebar-bg flex h-6 shrink-0 items-center justify-between border-t px-4 font-mono text-[0.625rem] tracking-wider uppercase select-none {barBg}"
>
  <div class="flex items-center gap-4">
    <div class="flex items-center gap-2">
      <span class="h-1.5 w-1.5 rounded-full {connDot}"></span>
      <span class="font-bold">{connLabel}</span>
    </div>
    <div class="flex items-center gap-1 opacity-60">
      <span class="text-[0.5625rem]">Latency</span>
      <span class="font-bold">42ms</span>
    </div>
  </div>
  <div class="flex items-center gap-4">
    <div>
      {threadState.threads.length} THREAD{threadState.threads.length !== 1 ? 'S' : ''} &middot;
      {activeCount} ACTIVE
    </div>
    <div class="flex items-center gap-1">
      <span class="text-[0.625rem] opacity-60">HEARTBEAT</span>
      <span class="font-bold">{heartbeatAgo}S</span>
    </div>
  </div>
</div>
