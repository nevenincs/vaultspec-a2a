<script lang="ts">
  import * as AlertDialog from '$lib/components/ui/alert-dialog';
  import { Button } from '$lib/components/ui/button';
  import type { PermissionRequestEvent } from '$lib/api/types';

  let {
    permission,
    onrespond,
  }: {
    permission: PermissionRequestEvent;
    onrespond: (optionId: string) => void;
  } = $props();
</script>

<AlertDialog.Root open={true}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>Permission Required</AlertDialog.Title>
      <AlertDialog.Description>{permission.description}</AlertDialog.Description>
    </AlertDialog.Header>
    {#if permission.tool_call}
      <p class="text-muted-foreground text-sm">Tool call: {permission.tool_call}</p>
    {/if}
    <AlertDialog.Footer>
      {#each permission.options as option (option.option_id)}
        <Button
          variant={option.kind.startsWith('allow') ? 'default' : 'destructive'}
          onclick={() => onrespond(option.option_id)}
        >
          {option.name}
        </Button>
      {/each}
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
