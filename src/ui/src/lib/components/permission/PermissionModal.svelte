<script lang="ts">
  import type { PermissionRequestEvent } from '$lib/api/types';
  import * as AlertDialog from '$lib/components/ui/alert-dialog';
  import { Button } from '$lib/components/ui/button';

  let {
    event,
    queueLength = 1,
    onrespond,
  }: {
    event: PermissionRequestEvent;
    queueLength?: number;
    onrespond: (optionId: string) => void;
  } = $props();
</script>

<AlertDialog.Root open={true}>
  <AlertDialog.Content class="max-w-md">
    <AlertDialog.Header>
      <AlertDialog.Title>Permission Required</AlertDialog.Title>
      <AlertDialog.Description>{event.description}</AlertDialog.Description>
    </AlertDialog.Header>
    {#if event.tool_call}
      <div class="text-muted-foreground text-sm">Tool: {event.tool_call}</div>
    {/if}
    <AlertDialog.Footer>
      {#each event.options as option (option.option_id)}
        <Button
          variant={option.kind === 'allow_once'
            ? 'default'
            : option.kind === 'reject_once' || option.kind === 'reject_always'
              ? 'destructive'
              : 'secondary'}
          onclick={() => onrespond(option.option_id)}
        >
          {option.name}
        </Button>
      {/each}
    </AlertDialog.Footer>
    {#if queueLength > 1}
      <div class="text-muted-foreground text-center text-xs">
        1 of {queueLength} pending
      </div>
    {/if}
  </AlertDialog.Content>
</AlertDialog.Root>
