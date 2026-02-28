<script lang="ts">
  import { onMount } from 'svelte';
  import Sidebar from './Sidebar.svelte';
  import TabBar from './TabBar.svelte';
  import StatusBar from './StatusBar.svelte';
  import { appState } from '$lib/stores/app-state.svelte';
  import { tabState } from '$lib/stores/tab-state.svelte';
  import { threadState } from '$lib/stores/thread-state.svelte';
  import { inspectorState } from '$lib/stores/inspector-state.svelte';

  // Slots/children — these are provided by the integration layer (route page)
  interface Props {
    children?: import('svelte').Snippet;
    streamPanel?: import('svelte').Snippet;
    inspectorPanel?: import('svelte').Snippet;
    permissionModal?: import('svelte').Snippet;
  }

  let { children, streamPanel, inspectorPanel, permissionModal }: Props = $props();

  // ── Inspector resize ──────────────────────────────────────────────────────
  let isResizingInspector = false;

  function handleInspectorResizeMouseDown(e: MouseEvent) {
    e.preventDefault();
    isResizingInspector = true;
    const startX = e.clientX;
    const startWidth = inspectorState.inspectorWidth;

    function onMove(ev: MouseEvent) {
      if (!isResizingInspector) return;
      inspectorState.setInspectorWidth(startWidth - (ev.clientX - startX));
    }
    function onUp() {
      isResizingInspector = false;
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

  // ── Keyboard shortcuts ────────────────────────────────────────────────────
  function handleKeydown(e: KeyboardEvent) {
    if (e.ctrlKey && e.key === '.') {
      e.preventDefault();
      appState.toggleSidebar();
    }
    if (e.ctrlKey && e.key === 'i') {
      e.preventDefault();
      if (inspectorState.isOpen) inspectorState.closeInspector();
    }
    if (e.key === 'Escape') {
      if (inspectorState.isOpen) inspectorState.closeInspector();
    }
    if (e.ctrlKey && e.key === 'n') {
      e.preventDefault();
      tabState.clearActiveTab();
    }
  }

  onMount(() => {
    window.addEventListener('keydown', handleKeydown);
    return () => window.removeEventListener('keydown', handleKeydown);
  });

  const hasActiveTab = $derived(
    tabState.activeTabId !== null &&
      threadState.getThread(tabState.activeTabId) !== null,
  );
</script>

<div
  class="bg-background text-foreground flex h-screen w-screen flex-col overflow-hidden"
>
  <!-- Main row: Sidebar | Content -->
  <div class="flex min-h-0 flex-1">
    <!-- Sidebar -->
    <Sidebar />

    <!-- Main content area -->
    <div class="flex min-h-0 min-w-0 flex-1 flex-col">
      <!-- Tab bar -->
      <TabBar />

      <!-- Stream + Inspector row -->
      <div class="flex min-h-0 min-w-0 flex-1">
        <!-- Stream panel -->
        <div class="flex min-h-0 min-w-0 flex-1 flex-col">
          {#if hasActiveTab}
            {@render streamPanel?.()}
          {:else}
            <!-- Empty state — no active tab -->
            <div class="flex flex-1 items-center justify-center">
              <div class="text-center select-none">
                <h2 class="text-foreground/60 mb-1 text-[1rem] font-semibold">
                  VaultSpec
                </h2>
                <p class="text-muted-foreground text-[0.75rem]">
                  Select a task from the sidebar, or create a new one below.
                </p>
              </div>
            </div>
          {/if}
          <!-- Children (e.g. InputBar) always rendered below stream -->
          {@render children?.()}
        </div>

        <!-- Inspector Panel -->
        {#if inspectorState.isOpen}
          <div
            class="relative h-full shrink-0"
            style="width: {inspectorState.inspectorWidth / 16}rem"
          >
            <!-- Resize handle — left edge -->
            <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
            <div
              role="separator"
              aria-label="Resize inspector panel"
              class="hover:bg-primary/30 active:bg-primary/50 absolute top-0 left-0 z-30 h-full w-1 cursor-col-resize transition-colors"
              onmousedown={handleInspectorResizeMouseDown}
            ></div>
            {@render inspectorPanel?.()}
          </div>
        {/if}
      </div>
    </div>
  </div>

  <!-- Status bar -->
  <StatusBar />

  <!-- Permission modal overlay -->
  {@render permissionModal?.()}
</div>
