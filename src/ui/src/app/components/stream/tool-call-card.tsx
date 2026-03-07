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
    event.status === 'in_progress' ? (
      <Loader2 className="text-status-info/70 h-3.5 w-3.5 shrink-0 animate-spin" />
    ) : event.status === 'completed' ? (
      <Check className="text-status-success/70 h-3.5 w-3.5 shrink-0" />
    ) : event.status === 'failed' ? (
      <X className="text-status-error/70 h-3.5 w-3.5 shrink-0" />
    ) : (
      <Circle className="text-muted-foreground/40 h-3.5 w-3.5 shrink-0" />
    );

  const borderColor =
    event.status === 'failed' ? 'border-status-error/20' : 'border-border/50';

  return (
    <div className="py-0.5">
      <button
        onClick={() => onInspect({ type: 'tool_call', event })}
        aria-label={`Tool call: ${event.tool_name}, status: ${event.status}`}
        className={`rounded-terminal w-full border text-left ${borderColor} bg-muted/10 hover:bg-muted/20 group px-3 py-1.5 transition-colors`}
      >
        <div className="flex items-center gap-2">
          {statusIcon}
          <span className="text-muted-foreground/60 font-mono text-[0.75rem]">
            {event.tool_name}
          </span>
          {event.location && (
            <span className="text-muted-foreground/40 truncate font-mono text-[0.625rem]">
              {event.location.file}
              {event.location.line ? `:${event.location.line}` : ''}
            </span>
          )}
          {event.input && !event.location && (
            <span className="text-muted-foreground/40 flex-1 truncate font-mono text-[0.625rem]">
              {event.input}
            </span>
          )}
        </div>
      </button>
    </div>
  );
}
