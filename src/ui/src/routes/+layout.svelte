<script lang="ts">
  import '../app.css';
  import favicon from '$lib/assets/favicon.svg';
  import { onMount, onDestroy } from 'svelte';
  import { ServerEventType } from '$lib/api/types';
  import type {
    ServerEvent,
    TeamStatusEvent,
    PermissionRequestEvent,
  } from '$lib/api/types';
  import { wsClient } from '$lib/api/websocket.svelte';
  import { agentState, teamState, permissionQueue } from '$lib/stores';
  import { Toaster } from '$lib/components/ui/sonner';

  let { children } = $props();

  function handleTeamStatus(event: ServerEvent): void {
    teamState.applyTeamStatus(event as TeamStatusEvent);
  }

  function handlePermissionRequest(event: ServerEvent): void {
    permissionQueue.enqueue(event as PermissionRequestEvent);
  }

  function handleAllEvents(event: ServerEvent): void {
    agentState.applyEvent(event);
  }

  onMount(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    // Register event handlers
    wsClient.on(ServerEventType.TEAM_STATUS, handleTeamStatus);
    wsClient.on(ServerEventType.PERMISSION_REQUEST, handlePermissionRequest);

    // Route all events through the agent state store
    for (const type of Object.values(ServerEventType)) {
      wsClient.on(type, handleAllEvents);
    }

    wsClient.connect(wsUrl);
  });

  onDestroy(() => {
    wsClient.off(ServerEventType.TEAM_STATUS, handleTeamStatus);
    wsClient.off(ServerEventType.PERMISSION_REQUEST, handlePermissionRequest);

    for (const type of Object.values(ServerEventType)) {
      wsClient.off(type, handleAllEvents);
    }

    wsClient.disconnect();
  });
</script>

<svelte:head>
  <link rel="icon" href={favicon} />
</svelte:head>

<div class="bg-background text-foreground flex h-screen overflow-hidden">
  <!-- Sidebar: thread list -->
  <aside class="border-border w-64 shrink-0 overflow-y-auto border-r">
    <div class="p-4">
      <h1 class="text-lg font-semibold">VaultSpec</h1>
    </div>
  </aside>

  <!-- Main content area -->
  <main class="flex-1 overflow-hidden">
    {@render children()}
  </main>
</div>

<Toaster />
