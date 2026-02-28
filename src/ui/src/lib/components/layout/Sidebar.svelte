<script lang="ts">
  import {
    Plus,
    PanelLeftClose,
    PanelLeft,
    Sun,
    Moon,
    Monitor,
    Settings,
    Search,
    X,
    GitBranch,
    Loader2,
  } from '@lucide/svelte';
  import { appState } from '$lib/stores/app-state.svelte';
  import { tabState } from '$lib/stores/tab-state.svelte';
  import { threadState } from '$lib/stores/thread-state.svelte';
  import { SvelteMap } from 'svelte/reactivity';
  import { agentStateDot, topologyLabel, timeAgo } from './state-indicators';
  import * as Tooltip from '$lib/components/ui/tooltip/index.js';

  // ── Search ────────────────────────────────────────────────────────────────
  let searchOpen = $state(false);
  let taskFilter = $state('');
  let searchInputEl: HTMLInputElement | undefined;

  // Focus search input when opening, clear filter when closing
  $effect(() => {
    if (searchOpen) {
      // Defer focus until DOM updates
      const id = setTimeout(() => searchInputEl?.focus(), 50);
      return () => clearTimeout(id);
    }
  });

  // Clear filter when search closes
  $effect(() => {
    if (!searchOpen) taskFilter = '';
  });

  const filteredThreads = $derived(
    taskFilter
      ? threadState.threads.filter((t) => {
          const q = taskFilter.toLowerCase();
          return [t.nickname, t.title, t.feature_tag, t.source_branch, t.source_repo]
            .filter(Boolean)
            .join(' ')
            .toLowerCase()
            .includes(q);
        })
      : threadState.threads,
  );

  // ── Drag-to-resize ────────────────────────────────────────────────────────
  const MIN_WIDTH = 180;
  const MAX_WIDTH = 420;
  let isResizing = false;

  function handleResizeMouseDown(e: MouseEvent) {
    e.preventDefault();
    isResizing = true;
    const startX = e.clientX;
    const startWidth = appState.sidebarWidth;

    function onMove(ev: MouseEvent) {
      if (!isResizing) return;
      appState.setSidebarWidth(startWidth + (ev.clientX - startX));
    }
    function onUp() {
      isResizing = false;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  // ── Click tracking for single/double click ───────────────────────────────
  const clickCounts = new SvelteMap<string, number>();
  const clickTimeouts = new SvelteMap<string, ReturnType<typeof setTimeout>>();

  function handleThreadClick(threadId: string) {
    const count = (clickCounts.get(threadId) ?? 0) + 1;
    clickCounts.set(threadId, count);

    if (count === 1) {
      tabState.openTransient(threadId);
      const t = setTimeout(() => {
        clickCounts.set(threadId, 0);
      }, 300);
      clickTimeouts.set(threadId, t);
    } else if (count === 2) {
      const existing = clickTimeouts.get(threadId);
      if (existing) clearTimeout(existing);
      clickCounts.set(threadId, 0);
      tabState.openPinned(threadId);
    }
  }

  // ── Theme cycling ─────────────────────────────────────────────────────────
  function cycleTheme() {
    const next =
      appState.themeMode === 'dark'
        ? 'light'
        : appState.themeMode === 'light'
          ? 'system'
          : 'dark';
    appState.setThemeMode(next);
  }
</script>

{#if appState.sidebarCollapsed}
  <!-- Collapsed icon-only sidebar -->
  <div
    class="border-border bg-oxide-sidebar-bg flex h-full w-12 shrink-0 flex-col items-center border-r px-1 py-2"
  >
    <Tooltip.Provider>
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <button
              {...props}
              class="rounded-ui hover:bg-accent flex h-8 w-8 items-center justify-center transition-colors"
              onclick={() => appState.toggleSidebar()}
            >
              <PanelLeft class="h-4 w-4" />
            </button>
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content side="right">Expand sidebar (Ctrl+.)</Tooltip.Content>
      </Tooltip.Root>
    </Tooltip.Provider>
  </div>
{:else}
  <!-- Expanded sidebar -->
  <div
    class="border-border bg-oxide-sidebar-bg relative flex h-full shrink-0 flex-col border-r"
    style="width: {appState.sidebarWidth / 16}rem"
  >
    <!-- Header -->
    <div class="border-border flex items-center justify-between border-b px-3 py-2.5">
      <div class="flex items-center gap-2">
        <button
          class="rounded-ui hover:bg-accent flex h-7 w-7 items-center justify-center transition-colors"
          onclick={() => appState.toggleSidebar()}
        >
          <PanelLeftClose class="text-oxide-icon h-4 w-4" />
        </button>
        <span
          class="text-foreground text-[0.8125rem] font-bold tracking-tight uppercase"
          >VaultSpec</span
        >
      </div>
      <div class="flex items-center gap-0.5">
        <Tooltip.Provider>
          <Tooltip.Root>
            <Tooltip.Trigger>
              {#snippet child({ props })}
                <button
                  {...props}
                  class="rounded-ui text-oxide-icon hover:bg-accent flex h-7 w-7 items-center justify-center transition-colors"
                  onclick={cycleTheme}
                >
                  {#if appState.themeMode === 'dark'}
                    <Moon class="h-3.5 w-3.5" />
                  {:else if appState.themeMode === 'light'}
                    <Sun class="h-3.5 w-3.5" />
                  {:else}
                    <Monitor class="h-3.5 w-3.5" />
                  {/if}
                </button>
              {/snippet}
            </Tooltip.Trigger>
            <Tooltip.Content side="bottom">Theme: {appState.themeMode}</Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
        <button
          class="rounded-ui text-oxide-icon hover:bg-accent flex h-7 w-7 items-center justify-center transition-colors"
        >
          <Settings class="h-3.5 w-3.5" />
        </button>
      </div>
    </div>

    <!-- New Task Button -->
    <div class="px-3 pt-3 pb-2">
      <button
        class="rounded-control text-foreground/70 hover:text-foreground border-border hover:bg-accent flex h-8 w-full items-center justify-start gap-2 border px-3 font-mono text-[0.75rem] tracking-wider uppercase transition-colors"
        onclick={() => tabState.clearActiveTab()}
      >
        <Plus class="h-3.5 w-3.5" />
        New Task
      </button>
    </div>

    <!-- Section header + search -->
    <div class="px-3 pb-1.5">
      <div class="flex h-7 items-center justify-between">
        <div class="mr-1 min-w-0 flex-1">
          {#if searchOpen}
            <div class="relative flex items-center">
              <Search
                class="text-muted-foreground pointer-events-none absolute left-2 z-10 h-3 w-3"
              />
              <input
                bind:this={searchInputEl}
                bind:value={taskFilter}
                onkeydown={(e) => {
                  if (e.key === 'Escape') searchOpen = false;
                }}
                placeholder="Filter tasks..."
                class="bg-input-background border-border rounded-ui focus:ring-ring h-6 w-full border pr-2 pl-6 text-[0.6875rem] focus:ring-1 focus:outline-none"
              />
            </div>
          {:else}
            <span
              class="text-text-dimmed px-1 text-[0.625rem] font-bold tracking-widest uppercase select-none"
            >
              Tasks
            </span>
          {/if}
        </div>
        <div class="flex shrink-0 items-center gap-0.5">
          <Tooltip.Provider>
            <Tooltip.Root>
              <Tooltip.Trigger>
                {#snippet child({ props })}
                  <button
                    {...props}
                    class="rounded-ui flex h-6 w-6 items-center justify-center transition-colors {searchOpen
                      ? 'text-primary bg-primary/10'
                      : 'text-text-dimmed hover:text-foreground'}"
                    onclick={() => {
                      searchOpen = !searchOpen;
                    }}
                  >
                    {#if searchOpen}
                      <X class="h-3 w-3" />
                    {:else}
                      <Search class="h-3 w-3" />
                    {/if}
                  </button>
                {/snippet}
              </Tooltip.Trigger>
              <Tooltip.Content side="bottom">
                {searchOpen ? 'Close search' : 'Search tasks'}
              </Tooltip.Content>
            </Tooltip.Root>
          </Tooltip.Provider>
        </div>
      </div>
    </div>

    <!-- Thread list -->
    <div class="min-h-0 flex-1 overflow-y-auto">
      <div class="space-y-0.5 px-2 py-1">
        {#if filteredThreads.length === 0 && taskFilter}
          <div class="text-text-subtle px-3 py-4 text-center text-[0.6875rem] italic">
            No tasks match &ldquo;{taskFilter}&rdquo;
          </div>
        {:else if filteredThreads.length === 0}
          <div class="text-text-subtle px-3 py-4 text-center text-[0.6875rem] italic">
            No tasks yet. Click &ldquo;New Task&rdquo; to start.
          </div>
        {/if}

        {#each filteredThreads as thread (thread.thread_id)}
          {@const isActive = tabState.activeTabId === thread.thread_id}
          {@const dot = agentStateDot(thread.agent_state)}
          {@const displayName = thread.nickname || thread.title}
          {@const topoLabel = topologyLabel(thread.topology)}
          <button
            class="rounded-ui group w-full px-2.5 py-2 text-left transition-colors {isActive
              ? 'bg-accent text-accent-foreground border-border/10 border shadow-sm'
              : 'hover:bg-accent/40 text-foreground/70'}"
            onclick={() => handleThreadClick(thread.thread_id)}
          >
            <!-- Row 1: status dot + nickname + time -->
            <div class="flex items-start gap-2">
              <span class="mt-0.5 flex w-4 shrink-0 items-center justify-center">
                {#if dot.kind === 'spinner'}
                  <Loader2 class="h-3.5 w-3.5 animate-spin {dot.colorClass}" />
                {:else if dot.kind === 'dot'}
                  <span class="h-2.5 w-2.5 rounded-full {dot.colorClass}"></span>
                {/if}
              </span>
              <span
                class="min-w-0 flex-1 text-[0.75rem] break-words {isActive
                  ? 'font-bold'
                  : ''}"
              >
                {displayName}
              </span>
              <span
                class="text-oxide-metadata mt-0.5 shrink-0 text-[0.625rem] tabular-nums"
              >
                {timeAgo(thread.updated_at)}
              </span>
            </div>

            <!-- Row 2: topology + feature tag + branch -->
            {#if thread.feature_tag || thread.source_branch || thread.topology}
              <div class="mt-1 ml-6 flex flex-wrap items-center gap-1.5">
                {#if topoLabel}
                  <span
                    class="text-oxide-metadata text-[0.625rem] font-bold tracking-widest uppercase"
                  >
                    {topoLabel}
                  </span>
                {/if}
                {#if thread.feature_tag}
                  <span
                    class="text-oxide-metadata font-mono text-[0.625rem] opacity-80"
                  >
                    #{thread.feature_tag}
                  </span>
                {/if}
                {#if thread.source_branch}
                  <span
                    class="text-oxide-metadata flex items-center gap-0.5 font-mono text-[0.625rem]"
                  >
                    <GitBranch class="h-2.5 w-2.5 shrink-0" />
                    {thread.source_branch}
                  </span>
                {/if}
              </div>
            {/if}
          </button>
        {/each}
      </div>
    </div>

    <!-- Drag-to-resize handle (right edge) -->
    <div
      role="separator"
      aria-label="Resize sidebar"
      class="hover:bg-primary/30 active:bg-primary/50 absolute top-0 right-0 z-30 h-full w-1 cursor-col-resize transition-colors"
      onmousedown={handleResizeMouseDown}
    ></div>
  </div>
{/if}
