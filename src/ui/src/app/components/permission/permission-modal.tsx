import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../ui/alert-dialog';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { toolKindIcon } from '../layout/state-indicators';
import { log } from '../../utils/logger';
import type { PermissionRequest } from '../../data/types';

interface PermissionModalProps {
  request: PermissionRequest;
  queueLength: number;
  onRespond: (requestId: string, optionId: string) => void;
}

export function PermissionModal({
  request,
  queueLength,
  onRespond,
}: PermissionModalProps) {
  return (
    <AlertDialog open={true}>
      <AlertDialogContent className="max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-[0.9375rem]">
            Permission Required
          </AlertDialogTitle>
          <AlertDialogDescription className="text-[0.8125rem]">
            {request.agent_name} wants to use {request.tool_name}
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="mt-1 space-y-3">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground w-14 text-[0.75rem]">Agent:</span>
              <span className="text-foreground text-[0.8125rem]">
                {request.agent_name}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground w-14 text-[0.75rem]">Tool:</span>
              <div className="flex items-center gap-1.5">
                {toolKindIcon(request.tool_kind, 'w-3.5 h-3.5 text-muted-foreground')}
                <span className="text-foreground font-mono text-[0.8125rem]">
                  {request.tool_name}
                </span>
              </div>
            </div>
          </div>

          <div className="bg-muted/50 border-border rounded-lg border px-3 py-2.5">
            <p className="text-foreground text-[0.8125rem]">
              &ldquo;{request.message}&rdquo;
            </p>
          </div>
        </div>

        <AlertDialogFooter className="mt-2 flex-row gap-2">
          {request.options.map((option) => {
            const variant =
              option.kind === 'allow_once'
                ? 'default'
                : option.kind === 'reject_once'
                  ? 'outline'
                  : option.kind === 'allow_always'
                    ? 'secondary'
                    : 'ghost';
            const extraClass =
              option.kind === 'reject_once' || option.kind === 'reject_always'
                ? 'text-status-error border-status-error/30 hover:bg-status-error/10 hover:text-status-error'
                : '';
            return (
              <Button
                key={option.id}
                variant={variant as any}
                size="sm"
                className={`text-[0.8125rem] ${extraClass}`}
                onClick={() => {
                  log.info(
                    'permission.respond',
                    `${option.label}: ${request.tool_name}`,
                    { agent: request.agent_name, option: option.kind },
                  );
                  onRespond(request.id, option.id);
                }}
                aria-label={`${option.label} permission for ${request.tool_name}`}
              >
                {option.label}
              </Button>
            );
          })}
        </AlertDialogFooter>

        {queueLength > 1 && (
          <div className="mt-2 flex justify-center">
            <Badge variant="secondary" className="text-[0.6875rem]">
              1 of {queueLength} pending
            </Badge>
          </div>
        )}
      </AlertDialogContent>
    </AlertDialog>
  );
}
