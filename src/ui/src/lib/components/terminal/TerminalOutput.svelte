<script lang="ts">
  import * as Card from '$lib/components/ui/card';

  let {
    terminalId,
    content = '',
  }: {
    terminalId: string;
    content?: string;
  } = $props();
</script>

<Card.Root class="bg-black text-green-400">
  <Card.Header class="pb-1">
    <Card.Title class="text-muted-foreground font-mono text-xs">
      Terminal: {terminalId}
    </Card.Title>
  </Card.Header>
  <Card.Content>
    <pre class="font-mono text-xs whitespace-pre-wrap">{content ||
        'Waiting for output...'}</pre>
  </Card.Content>
</Card.Root>
