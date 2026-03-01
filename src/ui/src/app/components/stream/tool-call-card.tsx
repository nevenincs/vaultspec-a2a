import { Loader2, Check, X, Circle } from 'lucide-react';
import type { ToolCallEvent, InspectorTarget } from '../../data/types';

/**
 * Tool call card — dimmed presentation so agent prose stands out.
 * The status indicator (check/x/spinner) IS the icon — no decorative tool kind icons.
 * No text status badge — the icon communicates status.
 */
export function ToolCallCard({
  event,
  onInspect,
}: {
  event: ToolCallEvent;
  onInspect: (target: InspectorTarget) => void;
}) {
  const statusIcon =
    event.status === 'running' ? (
      <Loader2 className="w-3.5 h-3.5 text-status-info/70 animate-spin shrink-0" />
    ) : event.status === 'completed' ? (
      <Check className="w-3.5 h-3.5 text-status-success/70 shrink-0" />
    ) : event.status === 'failed' ? (
      <X className="w-3.5 h-3.5 text-status-error/70 shrink-0" />
    ) : (
      <Circle className="w-3.5 h-3.5 text-muted-foreground/40 shrink-0" />
    );

  const borderColor =
    event.status === 'failed'
      ? 'border-status-error/20'
      : 'border-border/50';

  return (
    <div className="py-0.5">
      <button
        onClick={() => onInspect({ type: 'tool_call', event })}
        aria-label={`Tool call: ${event.tool_name}, status: ${event.status}`}
        className={`w-full text-left rounded-terminal border ${borderColor} bg-muted/10 px-3 py-1.5 hover:bg-muted/20 transition-colors group`}
      >
        <div className="flex items-center gap-2">
          {statusIcon}
          <span className="text-[0.75rem] font-mono text-muted-foreground/60">
            {event.tool_name}
          </span>
          {event.location && (
            <span className="text-[0.625rem] text-muted-foreground/40 font-mono truncate">
              {event.location.file}
              {event.location.line ? `:${event.location.line}` : ''}
            </span>
          )}
          {event.input && !event.location && (
            <span className="text-[0.625rem] text-muted-foreground/40 font-mono truncate flex-1">
              {event.input}
            </span>
          )}
        </div>
      </button>
    </div>
  );
}