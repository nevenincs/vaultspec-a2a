<script lang="ts">
  import { X, Loader2 } from '@lucide/svelte';
  import { SvelteMap } from 'svelte/reactivity';
  import { tabState } from '$lib/stores/tab-state.svelte';
  import { threadState } from '$lib/stores/thread-state.svelte';
  import { agentStateDot, type AgentDotDescriptor } from './state-indicators';

  interface TabItemData {
    threadId: string;
    label: string;
    isActive: boolean;
    isPinned: boolean;
    dot: AgentDotDescriptor;
  }

  const tabItems = $derived<TabItemData[]>(
    tabState.tabs.map((tab) => {
      const thread = threadState.getThread(tab.threadId);
      return {
        threadId: tab.threadId,
        label: thread?.nickname || thread?.title || tab.threadId,
        isActive: tabState.activeTabId === tab.threadId,
        isPinned: tab.isPinned,
        dot: thread ? agentStateDot(thread.agent_state) : { kind: 'none' },
      };
    }),
  );

  // Per-tab click state for single/double-click detection
  const clickCounts = new SvelteMap<string, number>();
  const clickTimeouts = new SvelteMap<string, ReturnType<typeof setTimeout>>();

  function handleTabClick(threadId: string, button: number) {
    if (button !== 0) return;
    const count = (clickCounts.get(threadId) ?? 0) + 1;
    clickCounts.set(threadId, count);

    if (count === 1) {
      tabState.activateTab(threadId);
      const t = setTimeout(() => {
        clickCounts.set(threadId, 0);
      }, 300);
      clickTimeouts.set(threadId, t);
    } else if (count === 2) {
      const existing = clickTimeouts.get(threadId);
      if (existing) clearTimeout(existing);
      clickCounts.set(threadId, 0);
      tabState.pinTab(threadId);
    }
  }

  function handleMouseDown(threadId: string, button: number, e: MouseEvent) {
    if (button === 1) {
      e.preventDefault();
      tabState.closeTab(threadId);
    }
  }
</script>

{#if tabState.tabs.length > 0}
  <div
    class="border-border bg-oxide-sidebar-bg flex h-9 shrink-0 items-end overflow-x-auto border-b"
  >
    {#each tabItems as item (item.threadId)}
      <div
        role="tab"
        tabindex="0"
        aria-selected={item.isActive}
        onmousedown={(e) => handleMouseDown(item.threadId, e.button, e)}
        onclick={(e) => handleTabClick(item.threadId, e.button)}
        onkeydown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') tabState.activateTab(item.threadId);
        }}
        class="group border-border/40 relative flex h-full max-w-[14rem] shrink-0 cursor-pointer items-center gap-1.5 border-r px-4 font-mono tracking-tight transition-all select-none {item.isActive
          ? 'bg-oxide-terminal-bg text-foreground shadow-[inset_0_2px_0_var(--primary)]'
          : 'bg-oxide-sidebar-bg text-oxide-metadata hover:text-foreground hover:bg-oxide-terminal-bg/50'}"
      >
        <!-- Status dot -->
        {#if item.dot.kind === 'spinner'}
          <span class="flex shrink-0 items-center">
            <Loader2 class="h-3 w-3 animate-spin {item.dot.colorClass}" />
          </span>
        {:else if item.dot.kind === 'dot'}
          <span class="h-2 w-2 shrink-0 rounded-full {item.dot.colorClass}"></span>
        {/if}

        <!-- Label — italic when transient -->
        <span
          class="truncate text-[0.6875rem] font-bold uppercase {item.isPinned
            ? ''
            : 'italic opacity-60'}"
        >
          {item.label}
        </span>

        <!-- Close button -->
        <button
          onclick={(e) => {
            e.stopPropagation();
            tabState.closeTab(item.threadId);
          }}
          class="rounded-control hover:bg-muted ml-1.5 shrink-0 p-0.5 opacity-0 transition-all group-hover:opacity-60 hover:!opacity-100"
        >
          <X class="h-3 w-3" />
        </button>
      </div>
    {/each}
  </div>
{/if}
