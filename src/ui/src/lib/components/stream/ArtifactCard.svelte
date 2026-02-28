<script lang="ts">
  import { FileCode } from '@lucide/svelte';
  import { uiAccent } from '$lib/utils/palette';
  import type { ThreadArtifact } from '$lib/stores/agent-state.svelte';
  import type { InspectorTarget } from '$lib/data/types';

  let {
    artifact,
    oninspect,
  }: {
    artifact: ThreadArtifact;
    oninspect: (target: InspectorTarget) => void;
  } = $props();

  const art = uiAccent('artifact');

  function handleInspect() {
    oninspect({
      type: 'artifact',
      event: {
        id: artifact.artifact_id,
        type: 'artifact',
        timestamp: new Date().toISOString(),
        thread_id: '',
        agent_id: '',
        agent_name: '',
        artifact_id: artifact.artifact_id,
        filename: artifact.filename,
        content: artifact.content,
        complete: artifact.complete,
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
      <FileCode class="h-3.5 w-3.5 shrink-0 opacity-70 {art.text}" />
      <span class="text-muted-foreground font-mono text-[0.75rem]">
        {artifact.filename}
      </span>
      <span class="text-muted-foreground font-mono text-[0.625rem] opacity-80">
        {artifact.complete ? 'created' : 'streaming\u2026'}
      </span>
    </div>
  </button>
</div>
