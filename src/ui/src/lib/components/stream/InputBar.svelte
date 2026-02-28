<script lang="ts">
  import {
    Send,
    Pause,
    ChevronDown,
    Users,
    GitBranch,
    FolderGit2,
    Tag,
    Plus,
    Check,
  } from '@lucide/svelte';
  import * as Popover from '$lib/components/ui/popover/index.js';
  import { Button } from '$lib/components/ui/button/index.js';
  import MarkdownEditor, { getEditorTextarea } from './MarkdownEditor.svelte';
  import { getAgentColor } from '$lib/utils/agent-colors';
  import type {
    AgentLifecycleStateStr,
    TeamPreset,
    ThreadSummaryUI,
  } from '$lib/data/types';

  // ── Mock data for pickers ──────────────────────────────────────────────────

  const MOCK_REPOS = [
    'wgergely/vaultspec-a2a',
    'wgergely/vaultspec-core',
    'wgergely/vaultspec-ui',
  ];

  const MOCK_BRANCHES = [
    'main',
    'develop',
    'fix/auth-session',
    'feat/sqlmodel',
    'feat/rate-limit',
    'chore/cicd',
  ];

  // ── Constants ──────────────────────────────────────────────────────────────

  const MIN_INPUT_HEIGHT = 100;
  const MAX_INPUT_HEIGHT = 480;

  // ── Props ──────────────────────────────────────────────────────────────────

  interface Props {
    agentState: AgentLifecycleStateStr;
    onSend: (
      message: string,
      opts?: {
        preset?: TeamPreset;
        repo?: string;
        branch?: string;
        featureTag?: string;
      },
    ) => void;
    onStop?: () => void;
    teamPresets?: TeamPreset[];
    selectedPreset?: TeamPreset | null;
    onSelectPreset?: (preset: TeamPreset) => void;
    isNewThread?: boolean;
    threads?: ThreadSummaryUI[];
    activeThread?: ThreadSummaryUI | null;
  }

  let {
    agentState,
    onSend,
    onStop,
    teamPresets,
    selectedPreset,
    onSelectPreset,
    isNewThread = false,
    threads,
    activeThread,
  }: Props = $props();

  // ── Derived booleans ────────────────────────────────────────────────────────

  const isWorking = $derived(agentState === 'working');
  const isInputRequired = $derived(agentState === 'input_required');
  const isCreateMode = $derived(!!isNewThread);

  // ── Editor state ────────────────────────────────────────────────────────────

  let message = $state('');
  let inputHeight = $state(MIN_INPUT_HEIGHT);
  let editorContainerEl: HTMLDivElement | undefined = $state();
  let isResizingBar = false;
  let userHasResized = false;

  const canSend = $derived(!isWorking && message.trim().length > 0);

  const placeholder = $derived(
    isInputRequired
      ? 'Agent needs input...'
      : isWorking
        ? ''
        : isCreateMode
          ? 'Describe the task for your team...'
          : selectedPreset
            ? `Message ${selectedPreset.name}...`
            : 'Message team...',
  );

  // ── Auto-expansion ──────────────────────────────────────────────────────────

  function handleHeightChange(contentHeight: number) {
    if (isResizingBar) return;
    const padding = 64;
    const target = Math.max(
      MIN_INPUT_HEIGHT,
      Math.min(MAX_INPUT_HEIGHT, contentHeight + padding),
    );
    if (!userHasResized || message === '') {
      inputHeight = target;
    }
  }

  // ── Create-mode local state ─────────────────────────────────────────────────

  let createRepo = $state(MOCK_REPOS[0]);
  let createBranch = $state('');
  let createFeatureTag = $state('');
  let newBranchInput = $state('');
  let newFeatureInput = $state('');
  let showNewBranch = $state(false);
  let showNewFeature = $state(false);

  // Popover open state
  let teamPickerOpen = $state(false);
  let repoPickerOpen = $state(false);
  let branchPickerOpen = $state(false);
  let featurePickerOpen = $state(false);

  const existingFeatureTags = $derived(
    threads
      ? [
          ...new Set(threads.map((t) => t.feature_tag).filter((t): t is string => !!t)),
        ].sort()
      : [],
  );

  const displayRepo = $derived(isCreateMode ? createRepo : activeThread?.source_repo);
  const displayBranch = $derived(
    isCreateMode ? createBranch : activeThread?.source_branch,
  );
  const displayFeature = $derived(
    isCreateMode ? createFeatureTag : activeThread?.feature_tag,
  );

  // ── @ mention autocomplete ──────────────────────────────────────────────────

  interface MentionState {
    active: boolean;
    query: string;
    startPos: number;
    selectedIndex: number;
  }

  let mentionState = $state<MentionState>({
    active: false,
    query: '',
    startPos: 0,
    selectedIndex: 0,
  });

  const availableAgents = $derived(selectedPreset?.agents ?? []);

  const filteredAgents = $derived(
    mentionState.active
      ? availableAgents.filter((a) =>
          a.toLowerCase().startsWith(mentionState.query.toLowerCase()),
        )
      : [],
  );

  function insertMention(agentName: string) {
    const before = message.slice(0, mentionState.startPos);
    const after = message.slice(mentionState.startPos + mentionState.query.length + 1);
    message = `${before}@${agentName} ${after}`;
    mentionState = { active: false, query: '', startPos: 0, selectedIndex: 0 };
    requestAnimationFrame(() => {
      if (editorContainerEl) {
        const pos = before.length + agentName.length + 2;
        const ta = getEditorTextarea(editorContainerEl);
        if (ta) {
          ta.focus();
          ta.setSelectionRange(pos, pos);
        }
      }
    });
  }

  // ── Markdown shortcut helpers ───────────────────────────────────────────────

  function wrapSelection(ta: HTMLTextAreaElement, before: string, after: string) {
    const { selectionStart: ss, selectionEnd: se, value } = ta;
    const selected = value.slice(ss, se);
    const replacement = `${before}${selected || 'text'}${after}`;
    message = value.slice(0, ss) + replacement + value.slice(se);
    requestAnimationFrame(() => {
      if (selected) {
        ta.setSelectionRange(ss, ss + replacement.length);
      } else {
        ta.setSelectionRange(ss + before.length, ss + before.length + 4);
      }
      ta.focus();
    });
  }

  function insertLinePrefix(ta: HTMLTextAreaElement, prefix: string) {
    const { selectionStart: ss, value } = ta;
    const lineStart = value.lastIndexOf('\n', ss - 1) + 1;
    message = value.slice(0, lineStart) + prefix + value.slice(lineStart);
    requestAnimationFrame(() => {
      ta.setSelectionRange(ss + prefix.length, ss + prefix.length);
      ta.focus();
    });
  }

  // ── Event handlers ──────────────────────────────────────────────────────────

  function handleMessageChange(val: string) {
    message = val;
    const ta = editorContainerEl ? getEditorTextarea(editorContainerEl) : null;
    const cursorPos = ta?.selectionStart ?? val.length;
    const textBefore = val.slice(0, cursorPos);
    const lastAt = textBefore.lastIndexOf('@');
    if (lastAt >= 0) {
      const charBefore = lastAt > 0 ? textBefore[lastAt - 1] : ' ';
      if (charBefore === ' ' || charBefore === '\n' || lastAt === 0) {
        const query = textBefore.slice(lastAt + 1);
        if (!query.includes(' ')) {
          mentionState = { active: true, query, startPos: lastAt, selectedIndex: 0 };
          return;
        }
      }
    }
    if (mentionState.active) {
      mentionState = { ...mentionState, active: false };
    }
  }

  function handleSend() {
    if (!canSend) return;
    if (isCreateMode) {
      onSend(message.trim(), {
        preset: selectedPreset ?? undefined,
        repo: createRepo || undefined,
        branch: createBranch || undefined,
        featureTag: createFeatureTag || undefined,
      });
    } else {
      onSend(message.trim());
    }
    message = '';
    inputHeight = MIN_INPUT_HEIGHT;
    userHasResized = false;
    mentionState = { active: false, query: '', startPos: 0, selectedIndex: 0 };
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (mentionState.active && filteredAgents.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        mentionState = {
          ...mentionState,
          selectedIndex: (mentionState.selectedIndex + 1) % filteredAgents.length,
        };
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        mentionState = {
          ...mentionState,
          selectedIndex:
            (mentionState.selectedIndex - 1 + filteredAgents.length) %
            filteredAgents.length,
        };
        return;
      }
      if (e.key === 'Tab' || e.key === 'Enter') {
        e.preventDefault();
        insertMention(filteredAgents[mentionState.selectedIndex]);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        mentionState = { active: false, query: '', startPos: 0, selectedIndex: 0 };
        return;
      }
    }

    const ta = editorContainerEl ? getEditorTextarea(editorContainerEl) : null;

    if (ta && (e.ctrlKey || e.metaKey)) {
      if (e.key === 'b') {
        e.preventDefault();
        wrapSelection(ta, '**', '**');
        return;
      }
      if (e.key === 'i') {
        e.preventDefault();
        wrapSelection(ta, '_', '_');
        return;
      }
      if (e.key === '`') {
        e.preventDefault();
        e.shiftKey ? wrapSelection(ta, '```\n', '\n```') : wrapSelection(ta, '`', '`');
        return;
      }
      if (e.key === 'k') {
        e.preventDefault();
        const { selectionStart: ss, selectionEnd: se, value } = ta;
        const selected = value.slice(ss, se);
        message = value.slice(0, ss) + `[${selected || 'text'}](url)` + value.slice(se);
        requestAnimationFrame(() => {
          if (selected) {
            ta.setSelectionRange(ss + selected.length + 3, ss + selected.length + 6);
          } else {
            ta.setSelectionRange(ss + 1, ss + 5);
          }
          ta.focus();
        });
        return;
      }
      if (e.shiftKey && e.key === '7') {
        e.preventDefault();
        insertLinePrefix(ta, '1. ');
        return;
      }
      if (e.shiftKey && e.key === '8') {
        e.preventDefault();
        insertLinePrefix(ta, '- ');
        return;
      }
    }

    if (e.key === 'Tab' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      if (ta) {
        const { selectionStart: ss, selectionEnd: se, value } = ta;
        message = value.slice(0, ss) + '  ' + value.slice(se);
        requestAnimationFrame(() => {
          ta.setSelectionRange(ss + 2, ss + 2);
          ta.focus();
        });
      }
      return;
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  // ── Drag-to-resize ─────────────────────────────────────────────────────────

  function handleResizeMouseDown(e: MouseEvent) {
    e.preventDefault();
    isResizingBar = true;
    userHasResized = true;
    const startY = e.clientY;
    const startH = inputHeight;
    function onMove(ev: MouseEvent) {
      if (!isResizingBar) return;
      inputHeight = Math.max(
        MIN_INPUT_HEIGHT,
        Math.min(MAX_INPUT_HEIGHT, startH - (ev.clientY - startY)),
      );
    }
    function onUp() {
      isResizingBar = false;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  const borderClass = $derived(
    isInputRequired
      ? 'border-status-warning/50 ring-1 ring-status-warning/20'
      : 'border-border',
  );

  // ── Branch / feature tag slug helpers ──────────────────────────────────────

  function slugifyBranch(raw: string): string {
    return raw
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9/._-]+/g, '-')
      .replace(/^-|-$/g, '');
  }

  function slugifyFeature(raw: string): string {
    return raw
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, '-')
      .replace(/^-|-$/g, '');
  }

  function commitBranch() {
    const slug = slugifyBranch(newBranchInput);
    if (slug) {
      createBranch = slug;
      newBranchInput = '';
      showNewBranch = false;
      branchPickerOpen = false;
    }
  }

  function commitFeature() {
    const slug = slugifyFeature(newFeatureInput);
    if (slug) {
      createFeatureTag = slug;
      newFeatureInput = '';
      showNewFeature = false;
      featurePickerOpen = false;
    }
  }
</script>

<div
  class="relative border-t {borderClass} bg-oxide-sidebar-bg shrink-0"
  style="height: {inputHeight}px"
>
  <!-- Resize handle — top edge -->
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    role="separator"
    aria-label="Resize input bar"
    class="hover:bg-primary/30 active:bg-primary/50 absolute top-0 right-0 left-0 z-30 h-1.5 -translate-y-0.5 cursor-row-resize transition-colors"
    onmousedown={handleResizeMouseDown}
  ></div>

  <div class="flex h-full flex-col px-4 pt-2 pb-2">
    <!-- Widget row -->
    <div class="flex h-8 shrink-0 items-center gap-1 overflow-x-auto">
      <!-- Team preset picker -->
      {#if teamPresets && onSelectPreset}
        {#if isCreateMode}
          <Popover.Root bind:open={teamPickerOpen}>
            <Popover.Trigger>
              {#snippet child({ props })}
                <button
                  {...props}
                  class="text-foreground/80 hover:text-foreground rounded-control border-border/50 hover:border-border bg-oxide-terminal-bg hover:bg-muted/60 flex h-7 shrink-0 cursor-pointer items-center gap-1.5 border px-2 text-[0.6875rem] transition-colors"
                >
                  <Users class="text-oxide-icon h-3 w-3" />
                  <span class="max-w-[10rem] truncate"
                    >{selectedPreset?.name || 'Select team...'}</span
                  >
                  <ChevronDown class="h-2.5 w-2.5 shrink-0 opacity-50" />
                </button>
              {/snippet}
            </Popover.Trigger>
            <Popover.Content align="start" class="z-50 w-80 p-1.5">
              <div class="space-y-0.5">
                {#each teamPresets as p (p.id)}
                  <button
                    class="rounded-control hover:bg-accent flex w-full items-start gap-2 px-2.5 py-2 text-left transition-colors {selectedPreset?.id ===
                    p.id
                      ? 'bg-accent'
                      : ''}"
                    onclick={() => {
                      onSelectPreset!(p);
                      teamPickerOpen = false;
                    }}
                  >
                    <div class="min-w-0 flex-1">
                      <div class="flex items-center gap-2">
                        <span class="text-[0.75rem]">{p.name}</span>
                        {#if selectedPreset?.id === p.id}
                          <Check class="text-primary h-3 w-3 shrink-0" />
                        {/if}
                      </div>
                      {#if p.description}
                        <p class="text-muted-foreground mt-0.5 text-[0.625rem]">
                          {p.description}
                        </p>
                      {/if}
                      <div class="mt-1 flex flex-wrap gap-1">
                        {#each p.agents as agent (agent)}
                          {@const c = getAgentColor(agent)}
                          <span
                            class="inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 font-mono text-[0.5625rem] {c.badge}"
                          >
                            <span class="h-1 w-1 rounded-full {c.dot}"></span>
                            {agent}
                          </span>
                        {/each}
                      </div>
                    </div>
                  </button>
                {/each}
              </div>
            </Popover.Content>
          </Popover.Root>
        {:else}
          <div
            class="text-muted-foreground rounded-control bg-muted/30 flex h-7 shrink-0 cursor-default items-center gap-1.5 border border-transparent px-2 text-[0.6875rem] select-none"
          >
            <Users class="text-oxide-icon h-3 w-3" />
            <span class="max-w-[10rem] truncate">{selectedPreset?.name || ''}</span>
          </div>
        {/if}
      {/if}

      <!-- Repo picker -->
      {#if isCreateMode}
        <Popover.Root bind:open={repoPickerOpen}>
          <Popover.Trigger>
            {#snippet child({ props })}
              <button
                {...props}
                class="text-foreground/80 hover:text-foreground rounded-control border-border/50 hover:border-border bg-oxide-terminal-bg hover:bg-muted/60 flex h-7 shrink-0 cursor-pointer items-center gap-1.5 border px-2 text-[0.6875rem] transition-colors"
              >
                <FolderGit2 class="text-oxide-icon h-3 w-3" />
                <span class="max-w-[10rem] truncate"
                  >{createRepo || 'Repository...'}</span
                >
                <ChevronDown class="h-2.5 w-2.5 shrink-0 opacity-50" />
              </button>
            {/snippet}
          </Popover.Trigger>
          <Popover.Content align="start" class="z-50 w-64 p-1.5">
            <div class="space-y-0.5">
              {#each MOCK_REPOS as r (r)}
                <button
                  class="rounded-control hover:bg-accent flex w-full items-center gap-2 px-2.5 py-1.5 text-left font-mono text-[0.75rem] transition-colors {createRepo ===
                  r
                    ? 'bg-accent'
                    : ''}"
                  onclick={() => {
                    createRepo = r;
                    repoPickerOpen = false;
                  }}
                >
                  <span class="flex-1 truncate">{r}</span>
                  {#if createRepo === r}
                    <Check class="text-primary h-3 w-3 shrink-0" />
                  {/if}
                </button>
              {/each}
            </div>
          </Popover.Content>
        </Popover.Root>
      {:else if displayRepo}
        <div
          class="text-muted-foreground rounded-control bg-muted/30 flex h-7 shrink-0 cursor-default items-center gap-1.5 border border-transparent px-2 text-[0.6875rem] select-none"
        >
          <FolderGit2 class="text-oxide-icon h-3 w-3" />
          <span class="max-w-[10rem] truncate">{displayRepo}</span>
        </div>
      {/if}

      <!-- Branch picker -->
      {#if isCreateMode}
        <Popover.Root
          bind:open={branchPickerOpen}
          onOpenChange={(v) => {
            if (!v) showNewBranch = false;
          }}
        >
          <Popover.Trigger>
            {#snippet child({ props })}
              <button
                {...props}
                class="text-foreground/80 hover:text-foreground rounded-control border-border/50 hover:border-border bg-oxide-terminal-bg hover:bg-muted/60 flex h-7 shrink-0 cursor-pointer items-center gap-1.5 border px-2 text-[0.6875rem] transition-colors"
              >
                <GitBranch class="h-3 w-3" />
                <span class="max-w-[10rem] truncate">{createBranch || 'Branch...'}</span
                >
                <ChevronDown class="h-2.5 w-2.5 shrink-0 opacity-50" />
              </button>
            {/snippet}
          </Popover.Trigger>
          <Popover.Content align="start" class="z-50 w-64 p-1.5">
            <div class="max-h-[16rem] space-y-0.5 overflow-y-auto">
              {#each MOCK_BRANCHES as b (b)}
                <button
                  class="rounded-control hover:bg-accent flex w-full items-center gap-2 px-2.5 py-1.5 text-left font-mono text-[0.75rem] transition-colors {createBranch ===
                  b
                    ? 'bg-accent'
                    : ''}"
                  onclick={() => {
                    createBranch = b;
                    branchPickerOpen = false;
                  }}
                >
                  <GitBranch class="text-muted-foreground h-3 w-3 shrink-0" />
                  <span class="flex-1 truncate">{b}</span>
                  {#if createBranch === b}
                    <Check class="text-primary h-3 w-3 shrink-0" />
                  {/if}
                </button>
              {/each}
            </div>
            <div class="border-border mt-1 border-t pt-1">
              {#if showNewBranch}
                <div class="flex items-center gap-1.5 px-1">
                  <!-- svelte-ignore a11y_autofocus -->
                  <input
                    class="bg-input-background border-border rounded-ui focus:ring-ring h-7 flex-1 border px-2 font-mono text-[0.6875rem] focus:ring-1 focus:outline-none"
                    bind:value={newBranchInput}
                    placeholder="feat/my-branch"
                    autofocus
                    onkeydown={(e) => {
                      if (e.key === 'Enter') commitBranch();
                      if (e.key === 'Escape') showNewBranch = false;
                    }}
                  />
                  <Button
                    size="icon"
                    class="h-7 w-7 shrink-0"
                    disabled={!newBranchInput.trim()}
                    onclick={commitBranch}
                  >
                    <Check class="h-3 w-3" />
                  </Button>
                </div>
              {:else}
                <button
                  class="rounded-control hover:bg-accent text-muted-foreground flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[0.75rem] transition-colors"
                  onclick={() => (showNewBranch = true)}
                >
                  <Plus class="h-3 w-3" />
                  <span>New branch</span>
                </button>
              {/if}
            </div>
          </Popover.Content>
        </Popover.Root>
      {:else if displayBranch}
        <div
          class="text-muted-foreground rounded-control bg-muted/30 flex h-7 shrink-0 cursor-default items-center gap-1.5 border border-transparent px-2 text-[0.6875rem] select-none"
        >
          <GitBranch class="text-oxide-icon h-3 w-3" />
          <span class="max-w-[10rem] truncate">{displayBranch}</span>
        </div>
      {/if}

      <!-- Feature tag picker -->
      {#if isCreateMode}
        <Popover.Root
          bind:open={featurePickerOpen}
          onOpenChange={(v) => {
            if (!v) showNewFeature = false;
          }}
        >
          <Popover.Trigger>
            {#snippet child({ props })}
              <button
                {...props}
                class="text-foreground/80 hover:text-foreground rounded-control border-border/50 hover:border-border bg-oxide-terminal-bg hover:bg-muted/60 flex h-7 shrink-0 cursor-pointer items-center gap-1.5 border px-2 text-[0.6875rem] transition-colors"
              >
                <Tag class="h-3 w-3" />
                <span class="max-w-[10rem] truncate"
                  >{createFeatureTag ? `#${createFeatureTag}` : 'Feature...'}</span
                >
                <ChevronDown class="h-2.5 w-2.5 shrink-0 opacity-50" />
              </button>
            {/snippet}
          </Popover.Trigger>
          <Popover.Content align="start" class="z-50 w-56 p-1.5">
            <div class="max-h-[16rem] space-y-0.5 overflow-y-auto">
              {#if existingFeatureTags.length === 0 && !showNewFeature}
                <div class="text-muted-foreground px-2.5 py-2 text-[0.6875rem] italic">
                  No existing features
                </div>
              {/if}
              {#each existingFeatureTags as tag (tag)}
                <button
                  class="rounded-control hover:bg-accent flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[0.75rem] transition-colors {createFeatureTag ===
                  tag
                    ? 'bg-accent'
                    : ''}"
                  onclick={() => {
                    createFeatureTag = tag;
                    featurePickerOpen = false;
                  }}
                >
                  <Tag class="text-muted-foreground h-3 w-3 shrink-0" />
                  <span class="flex-1 truncate">#{tag}</span>
                  {#if createFeatureTag === tag}
                    <Check class="text-primary h-3 w-3 shrink-0" />
                  {/if}
                </button>
              {/each}
            </div>
            <div class="border-border mt-1 border-t pt-1">
              {#if showNewFeature}
                <div class="flex items-center gap-1.5 px-1">
                  <!-- svelte-ignore a11y_autofocus -->
                  <input
                    class="bg-input-background border-border rounded-ui focus:ring-ring h-7 flex-1 border px-2 font-mono text-[0.6875rem] focus:ring-1 focus:outline-none"
                    bind:value={newFeatureInput}
                    placeholder="my-feature"
                    autofocus
                    onkeydown={(e) => {
                      if (e.key === 'Enter') commitFeature();
                      if (e.key === 'Escape') showNewFeature = false;
                    }}
                  />
                  <Button
                    size="icon"
                    class="h-7 w-7 shrink-0"
                    disabled={!newFeatureInput.trim()}
                    onclick={commitFeature}
                  >
                    <Check class="h-3 w-3" />
                  </Button>
                </div>
              {:else}
                <button
                  class="rounded-control hover:bg-accent text-muted-foreground flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[0.75rem] transition-colors"
                  onclick={() => (showNewFeature = true)}
                >
                  <Plus class="h-3 w-3" />
                  <span>New feature</span>
                </button>
              {/if}
            </div>
          </Popover.Content>
        </Popover.Root>
      {:else if displayFeature}
        <div
          class="text-muted-foreground rounded-control bg-muted/30 flex h-7 shrink-0 cursor-default items-center gap-1.5 border border-transparent px-2 text-[0.6875rem] select-none"
        >
          <Tag class="text-oxide-icon h-3 w-3" />
          <span class="max-w-[10rem] truncate">#{displayFeature}</span>
        </div>
      {/if}

      <div class="flex-1"></div>

      <!-- Interrupt button when working -->
      {#if isWorking && onStop}
        <Button
          variant="destructive"
          size="sm"
          class="h-7 gap-1.5 px-3"
          onclick={onStop}
        >
          <Pause class="h-3 w-3" />
          Interrupt
        </Button>
      {/if}
    </div>

    <!-- Editor + send row -->
    <div class="relative mt-1 flex min-h-0 flex-1 items-end gap-2">
      <!-- @ mention popup -->
      {#if mentionState.active && filteredAgents.length > 0}
        <div
          class="bg-popover border-border rounded-ui absolute bottom-full left-0 z-40 mb-1 w-56 overflow-hidden border shadow-xl"
        >
          <div class="py-1">
            <div class="px-3 py-1.5">
              <span
                class="text-oxide-metadata text-[0.625rem] font-bold tracking-widest uppercase"
              >
                Mention agent
              </span>
            </div>
            {#each filteredAgents as agent, idx (agent)}
              {@const c = getAgentColor(agent)}
              <button
                class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[0.75rem] transition-colors {idx ===
                mentionState.selectedIndex
                  ? 'bg-accent'
                  : 'hover:bg-accent/50'}"
                onmousedown={(e) => {
                  e.preventDefault();
                  insertMention(agent);
                }}
              >
                <span class="h-2 w-2 rounded-full {c.dot}"></span>
                <span class="font-mono {c.text}">{agent}</span>
              </button>
            {/each}
          </div>
        </div>
      {/if}

      <!-- Markdown editor wrapper -->
      <div bind:this={editorContainerEl} class="min-h-0 flex-1 self-stretch">
        <MarkdownEditor
          value={message}
          onchange={handleMessageChange}
          onkeydown={handleKeyDown}
          onHeightChange={handleHeightChange}
          {placeholder}
          disabled={isWorking}
          class="bg-oxide-terminal-input rounded-terminal border-border/40 focus-within:border-primary/40 h-full border transition-colors"
          inputClass={isInputRequired ? 'border-status-warning/50' : ''}
        />
      </div>

      <!-- Send button -->
      <Button
        size="icon"
        variant="default"
        class="rounded-control h-9 w-9 shrink-0"
        disabled={!canSend}
        onclick={handleSend}
      >
        <Send class="h-4 w-4" />
      </Button>
    </div>
  </div>
</div>
