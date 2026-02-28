<script lang="ts">
  import { ListChecks } from '@lucide/svelte';
  import { uiAccent } from '$lib/utils/palette';
  import type { PlanEntryUI, InspectorTarget } from '$lib/data/types';

  const plan = uiAccent('plan');

  let {
    entries,
    oninspect,
  }: {
    entries: PlanEntryUI[];
    oninspect: (target: InspectorTarget) => void;
  } = $props();

  const completed = $derived(entries.filter((e) => e.status === 'completed').length);
  const total = $derived(entries.length);

  function handleInspect() {
    oninspect({
      type: 'plan',
      event: {
        id: 'plan',
        type: 'plan_update',
        timestamp: new Date().toISOString(),
        thread_id: '',
        agent_id: '',
        agent_name: '',
        entries,
      },
    });
  }
</script>

<div class="py-0.5">
  <button
    onclick={handleInspect}
    class="rounded-terminal border-border/50 bg-muted/10 hover:bg-muted/20 w-full border px-3 py-1.5 text-left transition-colors"
  >
    <div class="flex items-center gap-2">
      <ListChecks class="text-accent-4 h-3.5 w-3.5 shrink-0 opacity-60" />
      <span class="text-muted-foreground/60 font-mono text-[0.75rem]">Plan updated</span
      >
      <span class="text-muted-foreground/40 font-mono text-[0.625rem]">
        {completed}/{total}
      </span>
    </div>
  </button>
</div>
