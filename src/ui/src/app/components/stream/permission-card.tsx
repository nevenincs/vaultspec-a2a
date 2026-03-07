import { ShieldAlert } from 'lucide-react';
import { Button } from '../ui/button';
import { toolKindIcon } from '../layout/state-indicators';
import { getAgentColor } from '../../utils/agent-colors';
import { log } from '../../utils/logger';
import type { PermissionRequest } from '../../data/types';

interface PermissionCardProps {
  request: PermissionRequest;
  onRespond: (requestId: string, optionId: string) => void;
  queueLength?: number;
}

export function PermissionCard({
  request,
  onRespond,
  queueLength = 1,
}: PermissionCardProps) {
  const color = getAgentColor(request.agent_name);

  return (
    <div className="px-4 py-1.5">
      <div className="rounded-ui border-status-warning/40 bg-status-warning/[0.04] overflow-hidden border">
        {/* Header bar */}
        <div className="flex items-center gap-2 px-4 pt-3 pb-2">
          <ShieldAlert className="text-status-warning h-4 w-4 shrink-0" />
          <span className="text-status-warning text-[0.6875rem] font-bold tracking-wider uppercase">
            Permission Required
          </span>
          {queueLength > 1 && (
            <span className="text-status-warning/70 ml-auto text-[0.5625rem]">
              1 of {queueLength} pending
            </span>
          )}
        </div>

        {/* Body */}
        <div className="space-y-2.5 px-4 pb-3">
          {/* Agent + Tool info */}
          <div className="flex items-center gap-3 text-[0.75rem]">
            <div className="flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full ${color.dot}`} />
              <span className={`font-mono font-bold ${color.text}`}>
                {request.agent_name}
              </span>
            </div>
            <span className="text-muted-foreground">wants to use</span>
            <div className="text-foreground flex items-center gap-1.5 font-mono">
              {toolKindIcon(request.tool_kind, 'w-3 h-3 text-muted-foreground')}
              {request.tool_name}
            </div>
          </div>

          {/* Message */}
          <div className="bg-background/60 rounded-control border-border/40 border px-3 py-2">
            <p className="text-foreground/90 text-[0.8125rem]">
              &ldquo;{request.message}&rdquo;
            </p>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 pt-0.5">
            {request.options.map((option) => {
              const isAllow = option.kind === 'allow_once';
              const isDeny =
                option.kind === 'reject_once' || option.kind === 'reject_always';
              const isAlwaysAllow = option.kind === 'allow_always';

              let variant: 'default' | 'outline' | 'secondary' | 'ghost' = 'ghost';
              let extraClass = '';

              if (isAllow) {
                variant = 'default';
              } else if (isDeny) {
                variant = 'outline';
                extraClass =
                  'text-status-error border-status-error/30 hover:bg-status-error/10 hover:text-status-error';
              } else if (isAlwaysAllow) {
                variant = 'secondary';
              }

              return (
                <Button
                  key={option.id}
                  variant={variant}
                  size="sm"
                  className={`h-7 text-[0.75rem] ${extraClass}`}
                  onClick={() => {
                    log.info(
                      'permission.respond',
                      `${option.label}: ${request.tool_name}`,
                      {
                        agent: request.agent_name,
                        option: option.kind,
                      },
                    );
                    onRespond(request.id, option.id);
                  }}
                  aria-label={`${option.label} permission for ${request.tool_name}`}
                >
                  {option.label}
                </Button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
