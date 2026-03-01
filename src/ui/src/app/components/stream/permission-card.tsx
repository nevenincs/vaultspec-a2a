import { ShieldAlert, Terminal, FileEdit, Search, Globe, Plug, Wrench, FileText } from 'lucide-react';
import { Button } from '../ui/button';
import { getAgentColor } from '../../utils/agent-colors';
import { log } from '../../utils/logger';
import type { PermissionRequest, ToolKind } from '../../data/types';

function toolKindIcon(kind: ToolKind, className = 'w-3.5 h-3.5') {
  switch (kind) {
    case 'read': return <FileText className={className} />;
    case 'edit': return <FileEdit className={className} />;
    case 'search': return <Search className={className} />;
    case 'execute': return <Terminal className={className} />;
    case 'browser': return <Globe className={className} />;
    case 'mcp': return <Plug className={className} />;
    case 'other': return <Wrench className={className} />;
  }
}

interface PermissionCardProps {
  request: PermissionRequest;
  onRespond: (requestId: string, optionId: string) => void;
  queueLength?: number;
}

export function PermissionCard({ request, onRespond, queueLength = 1 }: PermissionCardProps) {
  const color = getAgentColor(request.agent_name);

  return (
    <div className="px-4 py-1.5">
      <div className="rounded-ui border border-status-warning/40 bg-status-warning/[0.04] overflow-hidden">
        {/* Header bar */}
        <div className="flex items-center gap-2 px-4 pt-3 pb-2">
          <ShieldAlert className="w-4 h-4 text-status-warning shrink-0" />
          <span className="text-[0.6875rem] font-bold uppercase tracking-wider text-status-warning">
            Permission Required
          </span>
          {queueLength > 1 && (
            <span className="text-[0.5625rem] text-status-warning/70 ml-auto">
              1 of {queueLength} pending
            </span>
          )}
        </div>

        {/* Body */}
        <div className="px-4 pb-3 space-y-2.5">
          {/* Agent + Tool info */}
          <div className="flex items-center gap-3 text-[0.75rem]">
            <div className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${color.dot}`} />
              <span className={`font-mono font-bold ${color.text}`}>
                {request.agent_name}
              </span>
            </div>
            <span className="text-muted-foreground">wants to use</span>
            <div className="flex items-center gap-1.5 font-mono text-foreground">
              {toolKindIcon(request.tool_kind, 'w-3 h-3 text-muted-foreground')}
              {request.tool_name}
            </div>
          </div>

          {/* Message */}
          <div className="bg-background/60 rounded-control px-3 py-2 border border-border/40">
            <p className="text-[0.8125rem] text-foreground/90">&ldquo;{request.message}&rdquo;</p>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 pt-0.5">
            {request.options.map((option) => {
              const isAllow = option.kind === 'allow';
              const isDeny = option.kind === 'deny';
              const isAlwaysAllow = option.kind === 'allow_always';

              let variant: 'default' | 'outline' | 'secondary' | 'ghost' = 'ghost';
              let extraClass = '';

              if (isAllow) {
                variant = 'default';
              } else if (isDeny) {
                variant = 'outline';
                extraClass = 'text-status-error border-status-error/30 hover:bg-status-error/10 hover:text-status-error';
              } else if (isAlwaysAllow) {
                variant = 'secondary';
              }

              return (
                <Button
                  key={option.id}
                  variant={variant}
                  size="sm"
                  className={`text-[0.75rem] h-7 ${extraClass}`}
                  onClick={() => {
                    log.info('permission.respond', `${option.label}: ${request.tool_name}`, {
                      agent: request.agent_name,
                      option: option.kind,
                    });
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
