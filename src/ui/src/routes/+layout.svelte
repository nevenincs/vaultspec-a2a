<script lang="ts">
  import '../app.css';
  import favicon from '$lib/assets/favicon.svg';
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { ServerEventType } from '$lib/api/types';
  import type {
    ServerEvent,
    TeamStatusEvent,
    PermissionRequestEvent,
    ConnectedEvent,
  } from '$lib/api/types';
  import { wsClient } from '$lib/api/websocket.svelte';
  import { agentState, teamState, permissionQueue } from '$lib/stores';
  import { createThread, listThreads } from '$lib/api/rest';
  import type { ThreadSummary } from '$lib/api/types';
  import { Toaster } from '$lib/components/ui/sonner';
  import { toast } from 'svelte-sonner';
  import { Button } from '$lib/components/ui/button';
  import { ScrollArea } from '$lib/components/ui/scroll-area';
  import { Badge } from '$lib/components/ui/badge';
  import * as AlertDialog from '$lib/components/ui/alert-dialog';

  let { children } = $props();

  let threadList: ThreadSummary[] = $state([]);

  // --- WebSocket event handlers ---

  function handleAgentState(event: ServerEvent): void {
    agentState.applyEvent(event);
  }

  function handleTeamStatus(event: ServerEvent): void {
    teamState.applyTeamStatus(event as TeamStatusEvent);
  }

  function handlePermissionRequest(event: ServerEvent): void {
    permissionQueue.enqueue(event as PermissionRequestEvent);
  }

  function handleConnected(event: ServerEvent): void {
    const e = event as ConnectedEvent;
    wsClient.clientId = e.client_id;
  }

  function handleError(event: ServerEvent): void {
    agentState.applyEvent(event);
    if ('message' in event) {
      toast.error(event.message as string);
    }
  }

  // --- Actions ---

  async function createNewThread(): Promise<void> {
    const response = await createThread({
      title: null,
      initial_message: '',
      provider: null,
      model: null,
    });
    await goto(`/thread/${response.thread_id}`);
  }

  async function loadThreadList(): Promise<void> {
    try {
      const response = await listThreads();
      threadList = response.threads;
    } catch {
      // Will show empty list
    }
  }

  // --- Lifecycle ---

  onMount(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    // Agent state events
    wsClient.on(ServerEventType.AGENT_STATUS, handleAgentState);
    wsClient.on(ServerEventType.MESSAGE_CHUNK, handleAgentState);
    wsClient.on(ServerEventType.THOUGHT_CHUNK, handleAgentState);
    wsClient.on(ServerEventType.TOOL_CALL_START, handleAgentState);
    wsClient.on(ServerEventType.TOOL_CALL_UPDATE, handleAgentState);
    wsClient.on(ServerEventType.ARTIFACT_UPDATE, handleAgentState);
    wsClient.on(ServerEventType.PLAN_UPDATE, handleAgentState);

    // Error events go to both store and toast
    wsClient.on(ServerEventType.ERROR, handleError);

    // Team and permission events
    wsClient.on(ServerEventType.TEAM_STATUS, handleTeamStatus);
    wsClient.on(ServerEventType.PERMISSION_REQUEST, handlePermissionRequest);

    // Connection lifecycle
    wsClient.on(ServerEventType.CONNECTED, handleConnected);

    wsClient.connect(wsUrl);
    loadThreadList();
  });

  onDestroy(() => {
    wsClient.off(ServerEventType.AGENT_STATUS, handleAgentState);
    wsClient.off(ServerEventType.MESSAGE_CHUNK, handleAgentState);
    wsClient.off(ServerEventType.THOUGHT_CHUNK, handleAgentState);
    wsClient.off(ServerEventType.TOOL_CALL_START, handleAgentState);
    wsClient.off(ServerEventType.TOOL_CALL_UPDATE, handleAgentState);
    wsClient.off(ServerEventType.ARTIFACT_UPDATE, handleAgentState);
    wsClient.off(ServerEventType.PLAN_UPDATE, handleAgentState);
    wsClient.off(ServerEventType.ERROR, handleError);
    wsClient.off(ServerEventType.TEAM_STATUS, handleTeamStatus);
    wsClient.off(ServerEventType.PERMISSION_REQUEST, handlePermissionRequest);
    wsClient.off(ServerEventType.CONNECTED, handleConnected);

    wsClient.disconnect();
  });
</script>

<svelte:head>
  <link rel="icon" href={favicon} />
</svelte:head>

<div class="flex h-screen w-full flex-col">
  <div class="flex flex-1 overflow-hidden">
    <!-- Sidebar: thread list + team status -->
    <aside class="flex w-60 flex-col border-r">
      <div class="flex items-center justify-between border-b p-3">
        <span class="text-sm font-semibold">VaultSpec</span>
        <!-- Theme toggle button placeholder -->
      </div>
      <div class="p-2">
        <Button variant="outline" class="w-full" onclick={createNewThread}>
          + New Thread
        </Button>
      </div>
      <ScrollArea class="flex-1">
        {#each threadList as thread (thread.thread_id)}
          <a
            href="/thread/{thread.thread_id}"
            class="hover:bg-accent block border-b px-3 py-2 text-sm"
          >
            <div class="flex items-center gap-2">
              <span
                class="h-2 w-2 rounded-full {thread.agent_state === 'working'
                  ? 'animate-pulse bg-blue-500'
                  : thread.agent_state === 'idle'
                    ? 'bg-green-500'
                    : thread.agent_state === 'failed'
                      ? 'bg-red-500'
                      : 'bg-gray-400'}"
              ></span>
              <span class="flex-1 truncate">{thread.title ?? thread.thread_id}</span>
            </div>
            {#if thread.agent_state}
              <span class="text-muted-foreground text-xs">{thread.agent_state}</span>
            {/if}
          </a>
        {:else}
          <div class="text-muted-foreground p-3 text-sm">No threads yet</div>
        {/each}
      </ScrollArea>
      <div class="border-t p-3">
        <div
          class="text-muted-foreground mb-2 text-xs font-semibold tracking-wider uppercase"
        >
          Team Status
        </div>
        {#each teamState.agents as agent (agent.agent_id)}
          <div class="flex items-center gap-2 text-sm">
            <span
              class="h-2 w-2 rounded-full {agent.state === 'working'
                ? 'animate-pulse bg-blue-500'
                : agent.state === 'idle'
                  ? 'bg-green-500'
                  : agent.state === 'failed'
                    ? 'bg-red-500'
                    : 'bg-gray-400'}"
            ></span>
            <span class="flex-1 truncate">{agent.node_name}</span>
            <span class="text-muted-foreground text-xs">{agent.state}</span>
          </div>
        {/each}
      </div>
    </aside>

    <!-- Main content area -->
    <main class="flex min-w-0 flex-1 flex-col">
      {@render children()}
    </main>
  </div>

  <!-- Permission modal overlay (FIFO queue) -->
  {#if permissionQueue.current}
    <AlertDialog.Root open={true}>
      <AlertDialog.Content class="max-w-md">
        <AlertDialog.Header>
          <AlertDialog.Title>Permission Required</AlertDialog.Title>
          <AlertDialog.Description
            >{permissionQueue.current.description}</AlertDialog.Description
          >
        </AlertDialog.Header>
        {#if permissionQueue.current.tool_call}
          <div class="text-muted-foreground text-sm">
            Tool: {permissionQueue.current.tool_call}
          </div>
        {/if}
        <AlertDialog.Footer>
          {#each permissionQueue.current.options as option (option.option_id)}
            <Button
              variant={option.kind === 'allow_once'
                ? 'default'
                : option.kind === 'reject_once' || option.kind === 'reject_always'
                  ? 'destructive'
                  : 'secondary'}
              onclick={() => permissionQueue.respond(option.option_id)}
            >
              {option.name}
            </Button>
          {/each}
        </AlertDialog.Footer>
        {#if permissionQueue.length > 1}
          <div class="text-muted-foreground text-center text-xs">
            1 of {permissionQueue.length} pending
          </div>
        {/if}
      </AlertDialog.Content>
    </AlertDialog.Root>
  {/if}

  <!-- Toast notifications -->
  <Toaster />

  <!-- Status bar -->
  <footer class="flex items-center gap-4 border-t px-4 py-1 text-xs">
    <span class="flex items-center gap-1">
      <span
        class="inline-block h-2 w-2 rounded-full {wsClient.status === 'connected'
          ? 'bg-green-500'
          : wsClient.status === 'connecting'
            ? 'animate-pulse bg-yellow-500'
            : 'bg-red-500'}"
      ></span>
      {wsClient.status}
    </span>
    <span>{agentState.threads.size} threads</span>
  </footer>
</div>
