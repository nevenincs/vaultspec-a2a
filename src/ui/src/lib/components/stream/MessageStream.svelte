<script lang="ts">
  // ---------------------------------------------------------------------------
  // MessageStream — main stream view for a thread.
  // Consumes ThreadState from AgentStateStore and renders the chronological
  // stream of messages, tool calls, artifacts, and plan updates in agent capsules.
  // ---------------------------------------------------------------------------
  import { ChevronDown, Search, Check, FileText, X, Loader2 } from '@lucide/svelte';
  import { Button } from '$lib/components/ui/button';
  import { Input } from '$lib/components/ui/input';
  import MessageBubble from './MessageBubble.svelte';
  import ThoughtBlock from './ThoughtBlock.svelte';
  import ToolCallCard from './ToolCallCard.svelte';
  import ArtifactCard from './ArtifactCard.svelte';
  import PlanUpdateCard from './PlanUpdateCard.svelte';
  import ErrorAlert from './ErrorAlert.svelte';
  import { getAgentColor } from '$lib/utils/agent-colors';
  import { SvelteSet } from 'svelte/reactivity';
  import type {
    InspectorTarget,
    AgentLifecycleStateStr,
    PlanEntryUI,
  } from '$lib/data/types';
  import type { ThreadState, StreamItem } from '$lib/stores/agent-state.svelte';

  let {
    thread,
    oninspect,
    emptyState = false,
    agentLifecycleState = null,
    ontoggledocs,
    isDocsOpen = false,
    docsCount = 0,
  }: {
    thread: ThreadState | null;
    oninspect: (target: InspectorTarget) => void;
    emptyState?: boolean;
    agentLifecycleState?: AgentLifecycleStateStr | null;
    ontoggledocs?: () => void;
    isDocsOpen?: boolean;
    docsCount?: number;
  } = $props();

  // ---------------------------------------------------------------------------
  // Filter state
  // ---------------------------------------------------------------------------
  let selectedAgentIds = new SvelteSet<string>();
  let showThoughts = $state(true);
  let showToolCalls = $state(true);
  let searchQuery = $state('');
  let searchOpen = $state(false);
  let searchInputEl: HTMLInputElement | undefined = $state();

  // Scroll state
  let scrollContainerEl: HTMLDivElement | undefined = $state();
  let bottomEl: HTMLDivElement | undefined = $state();
  let isNearBottom = $state(true);
  let showNewBadge = $state(false);

  const isWorking = $derived(
    agentLifecycleState === 'working' || agentLifecycleState === 'submitted',
  );

  // ---------------------------------------------------------------------------
  // Derive stream items from ThreadState
  // ---------------------------------------------------------------------------

  /**
   * Build a flat ordered list from streamItems + thread data maps.
   * Each item references the actual data in the thread's reactive maps.
   */
  const streamItems: StreamItem[] = $derived(thread?.streamItems ?? []);

  // ---------------------------------------------------------------------------
  // Available agents (for filter popover)
  // ---------------------------------------------------------------------------

  const availableAgents = $derived.by(() => {
    const map = new Map<string, string>();
    for (const msg of thread?.messages ?? []) {
      if (msg.agent_id) {
        map.set(msg.agent_id, msg.agent_id); // agent_id used as display name fallback
      }
    }
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
  });

  const hasActiveFilters = $derived(
    selectedAgentIds.size > 0 ||
      !showThoughts ||
      !showToolCalls ||
      searchQuery.length > 0,
  );

  const activeFilterCount = $derived(
    selectedAgentIds.size +
      (searchQuery ? 1 : 0) +
      (!showThoughts ? 1 : 0) +
      (!showToolCalls ? 1 : 0),
  );

  // ---------------------------------------------------------------------------
  // Filtered stream items
  // ---------------------------------------------------------------------------

  const filteredItems = $derived.by(() => {
    if (!thread) return [];
    const items: StreamItem[] = [];

    for (const item of streamItems) {
      if (item.kind === 'message') {
        const msg = thread.messages.find((m) => m.message_id === item.id);
        if (!msg) continue;

        if (msg.role === 'thought' && !showThoughts) continue;

        if (selectedAgentIds.size > 0 && msg.agent_id) {
          if (!selectedAgentIds.has(msg.agent_id)) continue;
        }

        if (
          searchQuery &&
          !msg.content.toLowerCase().includes(searchQuery.toLowerCase())
        )
          continue;

        items.push(item);
      } else if (item.kind === 'tool') {
        if (!showToolCalls) continue;

        const tc = thread.toolCalls.get(item.id);
        if (!tc) continue;

        if (selectedAgentIds.size > 0) continue; // tool calls don't have agent_id in ThreadToolCall

        if (searchQuery && !tc.title.toLowerCase().includes(searchQuery.toLowerCase()))
          continue;

        items.push(item);
      } else if (item.kind === 'artifact') {
        const art = thread.artifacts.get(item.id);
        if (!art) continue;

        if (
          searchQuery &&
          !art.filename.toLowerCase().includes(searchQuery.toLowerCase())
        )
          continue;

        items.push(item);
      }
    }

    return items;
  });

  // ---------------------------------------------------------------------------
  // Grouping: consecutive items from same agent → agent capsule
  // ---------------------------------------------------------------------------

  type AgentGroup = {
    kind: 'agent';
    agentId: string;
    timestamp: string;
    itemIds: string[]; // StreamItem ids in order
  };

  type StandaloneGroup = {
    kind: 'standalone';
    item: StreamItem;
  };

  type Group = AgentGroup | StandaloneGroup;

  const groups = $derived.by((): Group[] => {
    if (!thread) return [];

    const result: Group[] = [];
    let currentGroup: AgentGroup | null = null;

    for (const item of filteredItems) {
      // Determine agent_id for this item
      let agentId: string | null = null;
      let timestamp = new Date().toISOString();

      if (item.kind === 'message') {
        const msg = thread.messages.find((m) => m.message_id === item.id);
        if (msg?.agent_id && msg.role !== 'user') {
          agentId = msg.agent_id;
          timestamp = msg.timestamp;
        }
      }
      // tool calls and artifacts are attributed to the current agent group
      else if (item.kind === 'tool' || item.kind === 'artifact') {
        // Inherit current group if one is active
        if (currentGroup) {
          currentGroup.itemIds.push(item.id + ':' + item.kind);
          continue;
        }
        // Otherwise standalone
        result.push({ kind: 'standalone', item });
        continue;
      }

      if (agentId) {
        if (currentGroup && currentGroup.agentId === agentId) {
          currentGroup.itemIds.push(item.id + ':' + item.kind);
        } else {
          if (currentGroup) result.push(currentGroup);
          currentGroup = {
            kind: 'agent',
            agentId,
            timestamp,
            itemIds: [item.id + ':' + item.kind],
          };
        }
      } else {
        if (currentGroup) {
          result.push(currentGroup);
          currentGroup = null;
        }
        result.push({ kind: 'standalone', item });
      }
    }

    if (currentGroup) result.push(currentGroup);

    return result;
  });

  // ---------------------------------------------------------------------------
  // Scroll management
  // ---------------------------------------------------------------------------

  $effect(() => {
    // Trigger on filteredItems change
    const _ = filteredItems.length;
    if (isNearBottom) {
      bottomEl?.scrollIntoView({ behavior: 'smooth' });
    } else {
      showNewBadge = true;
    }
  });

  $effect(() => {
    if (searchOpen && searchInputEl) {
      setTimeout(() => searchInputEl?.focus(), 50);
    }
  });

  function handleScroll(e: UIEvent) {
    const el = e.currentTarget as HTMLDivElement;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    isNearBottom = nearBottom;
    if (nearBottom) showNewBadge = false;
  }

  function scrollToBottom() {
    bottomEl?.scrollIntoView({ behavior: 'smooth' });
    showNewBadge = false;
    isNearBottom = true;
  }

  function toggleAgent(id: string) {
    if (selectedAgentIds.has(id)) selectedAgentIds.delete(id);
    else selectedAgentIds.add(id);
  }

  function clearAllFilters() {
    selectedAgentIds.clear();
    showThoughts = true;
    showToolCalls = true;
    searchQuery = '';
  }

  // ---------------------------------------------------------------------------
  // Plan adapter: backend PlanEntry → PlanEntryUI for PlanUpdateCard
  // ---------------------------------------------------------------------------
  function adaptPlan(
    entries: { content: string; status: string; priority: string }[],
  ): PlanEntryUI[] {
    return entries.map((e, i) => ({
      id: `pe-${i}`,
      title: e.content,
      status: e.status as PlanEntryUI['status'],
      priority: e.priority as PlanEntryUI['priority'],
    }));
  }
</script>

{#if emptyState || !thread}
  <!-- Empty / welcome state -->
  <div class="bg-oxide-sidebar-bg flex flex-1 items-center justify-center">
    <div class="max-w-sm text-center">
      <div
        class="rounded-bubble bg-muted mx-auto mb-4 flex h-12 w-12 items-center justify-center"
      >
        <FileText class="text-primary h-6 w-6" />
      </div>
      <h3 class="mb-1 text-[0.9375rem] font-medium">VaultSpec Orchestrator</h3>
      <p class="text-muted-foreground text-[0.8125rem]">
        Ready to deploy multi-agent workflows. Type a message to begin or select a team
        preset from the sidebar.
      </p>
    </div>
  </div>
{:else}
  <div class="bg-background relative flex min-h-0 flex-1 flex-col">
    <!-- ── Stream Toolbar ── -->
    <div
      class="border-border bg-oxide-sidebar-bg sticky top-0 z-20 flex items-center justify-between border-b px-4 py-2"
    >
      <!-- Active filter badges -->
      <div class="flex items-center gap-3">
        {#if selectedAgentIds.size > 0}
          <div class="flex gap-1">
            {#each Array.from(selectedAgentIds) as id (id)}
              {@const agent = availableAgents.find((a) => a.id === id)}
              {@const color = getAgentColor(agent?.name ?? id)}
              <button
                onclick={() => toggleAgent(id)}
                class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.625rem] transition-opacity hover:opacity-70 {color.badge}"
              >
                {agent?.name ?? id}
                <X class="h-2.5 w-2.5" />
              </button>
            {/each}
          </div>
        {/if}
        {#if searchQuery}
          <button
            onclick={() => (searchQuery = '')}
            class="border-primary/40 bg-primary/10 text-primary inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.625rem] transition-opacity hover:opacity-70"
          >
            &ldquo;{searchQuery.slice(0, 16)}{searchQuery.length > 16
              ? '\u2026'
              : ''}&rdquo;
            <X class="h-2.5 w-2.5" />
          </button>
        {/if}
      </div>

      <div class="flex items-center gap-1.5">
        <!-- Docs / context button -->
        <Button
          variant="ghost"
          size="sm"
          class="h-7 gap-1.5 px-2.5 text-[0.6875rem] transition-colors {isDocsOpen
            ? 'border-border bg-accent text-accent-foreground border'
            : 'text-muted-foreground hover:text-foreground'}"
          onclick={ontoggledocs}
        >
          <FileText class="h-3 w-3" />
          Plans
          {#if docsCount > 0}
            <span
              class="flex h-4 min-w-[1rem] items-center justify-center rounded-full px-1 text-[0.5625rem] font-bold {isDocsOpen
                ? 'bg-muted text-foreground'
                : 'bg-muted-foreground/20 text-muted-foreground'}"
            >
              {docsCount}
            </span>
          {/if}
        </Button>

        <!-- Search & filter toggle -->
        <div class="relative">
          <Button
            variant="ghost"
            size="sm"
            class="h-7 gap-1.5 px-2.5 text-[0.6875rem] transition-colors {hasActiveFilters
              ? 'border-border bg-accent text-accent-foreground border'
              : 'text-muted-foreground hover:text-foreground'}"
            onclick={() => (searchOpen = !searchOpen)}
          >
            <Search class="h-3 w-3" />
            Search
            {#if hasActiveFilters}
              <span
                class="bg-muted text-foreground flex h-4 w-4 items-center justify-center rounded-full text-[0.5625rem] font-bold"
              >
                {activeFilterCount}
              </span>
            {/if}
          </Button>

          {#if searchOpen}
            <!-- Filter popover -->
            <div
              class="rounded-ui border-border bg-background absolute top-full right-0 z-30 mt-1.5 w-80 border shadow-2xl"
            >
              <!-- Search input -->
              <div class="border-border border-b p-3">
                <div class="relative">
                  <Search
                    class="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 z-10 h-3.5 w-3.5 -translate-y-1/2 opacity-60"
                  />
                  <Input
                    bind:ref={searchInputEl}
                    type="text"
                    bind:value={searchQuery}
                    placeholder="Search messages\u2026"
                    class="h-8 pr-8 pl-8 font-mono text-[0.75rem]"
                  />
                  {#if searchQuery}
                    <button
                      onclick={() => (searchQuery = '')}
                      class="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2 transition-colors"
                    >
                      <X class="h-3 w-3" />
                    </button>
                  {/if}
                </div>
              </div>

              <!-- Agent filter -->
              <div class="border-border border-b p-3">
                <span
                  class="text-muted-foreground mb-2 block text-[0.625rem] font-bold tracking-wider uppercase opacity-80"
                >
                  Filter by Agent
                </span>
                {#if availableAgents.length === 0}
                  <p class="text-muted-foreground text-[0.6875rem] italic">
                    No agents in this thread
                  </p>
                {:else}
                  <div class="flex flex-wrap gap-1.5">
                    {#each availableAgents as agent (agent.id)}
                      {@const color = getAgentColor(agent.name)}
                      {@const isSelected = selectedAgentIds.has(agent.id)}
                      <button
                        onclick={() => toggleAgent(agent.id)}
                        class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[0.6875rem] font-medium transition-all {color.badge} {isSelected
                          ? 'opacity-100 ring-1 ring-current'
                          : 'opacity-70 hover:opacity-100'}"
                      >
                        {agent.name}
                        {#if isSelected}
                          <Check class="h-2.5 w-2.5" />
                        {/if}
                      </button>
                    {/each}
                  </div>
                {/if}
              </div>

              <!-- Visibility toggles -->
              <div class="border-border border-b p-3">
                <span
                  class="text-muted-foreground mb-2 block text-[0.625rem] font-bold tracking-wider uppercase opacity-80"
                >
                  Visibility
                </span>
                <div class="space-y-1.5">
                  {#each [{ label: 'Agent Thoughts', value: showThoughts, toggle: () => (showThoughts = !showThoughts) }, { label: 'Tool Calls', value: showToolCalls, toggle: () => (showToolCalls = !showToolCalls) }] as item (item.label)}
                    <button
                      onclick={item.toggle}
                      class="rounded-control hover:bg-muted/40 flex w-full items-center justify-between px-2 py-1.5 transition-colors"
                    >
                      <span class="text-foreground/80 text-[0.75rem]">{item.label}</span
                      >
                      <div
                        class="relative h-4 w-8 rounded-full transition-colors {item.value
                          ? 'bg-primary'
                          : 'bg-muted-foreground/30'}"
                      >
                        <div
                          class="bg-background absolute top-0.5 h-3 w-3 rounded-full shadow-sm transition-transform {item.value
                            ? 'translate-x-4'
                            : 'translate-x-0.5'}"
                        ></div>
                      </div>
                    </button>
                  {/each}
                </div>
              </div>

              <!-- Footer -->
              <div class="flex items-center justify-between p-2">
                <span class="text-muted-foreground px-1 text-[0.625rem]">
                  {filteredItems.length} / {streamItems.length} items
                </span>
                {#if hasActiveFilters}
                  <button
                    onclick={clearAllFilters}
                    class="text-muted-foreground hover:bg-muted/40 hover:text-foreground rounded px-2 py-1 text-[0.6875rem] transition-colors"
                  >
                    Clear all
                  </button>
                {/if}
              </div>
            </div>
          {/if}
        </div>
      </div>
    </div>

    <!-- ── Message list ── -->
    <div
      bind:this={scrollContainerEl}
      class="flex-1 overflow-y-auto"
      onscroll={handleScroll}
    >
      <div class="space-y-1 py-6">
        {#each groups as group (group.kind === 'agent' ? `grp-${group.agentId}-${group.timestamp}` : `standalone-${group.item.id}`)}
          {#if group.kind === 'agent'}
            <!-- Agent capsule -->
            {@const color = getAgentColor(group.agentId)}
            <div class="px-4 py-1.5">
              <div
                class="rounded-ui border-border/40 bg-oxide-terminal-bg flex overflow-hidden border"
              >
                <div class="w-[0.1875rem] shrink-0 {color.dot}"></div>
                <div class="min-w-0 flex-1">
                  <!-- Agent header -->
                  <div class="flex items-center gap-2 px-4 pt-2.5 pb-1">
                    <span
                      class="font-mono text-[0.6875rem] font-bold tracking-wider uppercase {color.text}"
                    >
                      {group.agentId}
                    </span>
                    <span
                      class="text-muted-foreground font-mono text-[0.625rem] opacity-80"
                    >
                      {new Date(group.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                  </div>

                  <!-- Events inside capsule -->
                  <div class="space-y-0.5 px-4 pb-3">
                    {#each group.itemIds as rawId (rawId)}
                      {@const [id, kind] = rawId.split(':')}
                      {#if kind === 'message'}
                        {@const msg = thread.messages.find((m) => m.message_id === id)}
                        {#if msg}
                          {#if msg.role === 'thought'}
                            <ThoughtBlock content={msg.content} />
                          {:else}
                            <MessageBubble message={msg} isUser={false} />
                          {/if}
                        {/if}
                      {:else if kind === 'tool'}
                        {@const tc = thread.toolCalls.get(id)}
                        {#if tc}
                          <ToolCallCard toolCall={tc} {oninspect} />
                        {/if}
                      {:else if kind === 'artifact'}
                        {@const art = thread.artifacts.get(id)}
                        {#if art}
                          <ArtifactCard artifact={art} {oninspect} />
                        {/if}
                      {/if}
                    {/each}

                    <!-- Plan (always shown at bottom of capsule if thread has a plan) -->
                    {#if thread.plan.length > 0 && group === groups[groups.length - 1]}
                      <PlanUpdateCard entries={adaptPlan(thread.plan)} {oninspect} />
                    {/if}
                  </div>
                </div>
              </div>
            </div>
          {:else}
            <!-- Standalone item -->
            {@const item = group.item}
            {#if item.kind === 'message'}
              {@const msg = thread.messages.find((m) => m.message_id === item.id)}
              {#if msg}
                {#if msg.role === 'user'}
                  <MessageBubble message={msg} isUser={true} />
                {:else if msg.role === 'thought'}
                  <!-- thought not inside a capsule — wrap lightly -->
                  <div class="px-4 py-1.5">
                    <ThoughtBlock content={msg.content} />
                  </div>
                {:else}
                  <MessageBubble message={msg} isUser={false} />
                {/if}
              {/if}
            {/if}
          {/if}
        {/each}

        <!-- Working indicator -->
        {#if isWorking}
          <div class="px-4 py-3">
            <div class="rounded-ui flex items-center gap-3 px-4 py-2.5">
              <Loader2 class="text-status-info h-4 w-4 animate-spin" />
              <span class="text-muted-foreground text-[0.75rem]"
                >Team is working&hellip;</span
              >
            </div>
          </div>
        {/if}

        <div bind:this={bottomEl} class="h-4"></div>
      </div>
    </div>

    <!-- New messages badge -->
    {#if showNewBadge}
      <div class="absolute bottom-6 left-1/2 z-10 -translate-x-1/2">
        <Button
          variant="secondary"
          size="sm"
          class="border-border h-8 gap-1 rounded-full border text-[0.75rem] shadow-xl"
          onclick={scrollToBottom}
        >
          <ChevronDown class="h-3.5 w-3.5" />
          New messages
        </Button>
      </div>
    {/if}

    <!-- Close search popover on outside click -->
    {#if searchOpen}
      <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
      <div class="fixed inset-0 z-20" onclick={() => (searchOpen = false)}></div>
    {/if}
  </div>
{/if}
