<script lang="ts">
  import type { ArtifactSnapshot } from '$lib/api/types';
  import * as Card from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';

  let { artifact }: { artifact: ArtifactSnapshot } = $props();
</script>

<Card.Root class="mb-3 p-3">
  <div class="flex items-center justify-between">
    <span class="text-sm font-medium">{artifact.filename}</span>
    <Badge variant={artifact.complete ? 'secondary' : 'default'}>
      {artifact.complete ? 'complete' : 'streaming...'}
    </Badge>
  </div>
  <pre class="bg-muted mt-2 overflow-x-auto rounded p-2 text-xs"><code
      >{artifact.content}</code
    ></pre>
</Card.Root>
