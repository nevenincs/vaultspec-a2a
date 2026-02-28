<script lang="ts">
  import type { ToolCallContentDiff } from '$lib/api/types';
  import { createPatch } from 'diff';
  import * as Diff2Html from 'diff2html';

  let { diff }: { diff: ToolCallContentDiff } = $props();

  const diffHtml = $derived(
    Diff2Html.html(createPatch(diff.path, diff.old_text ?? '', diff.new_text, '', ''), {
      drawFileList: false,
      matching: 'lines',
      outputFormat: 'line-by-line',
      renderNothingWhenEmpty: false,
    }),
  );
</script>

<div class="d2h-wrapper overflow-auto rounded border text-xs">
  <!-- eslint-disable-next-line svelte/no-at-html-tags -->
  {@html diffHtml}
</div>
