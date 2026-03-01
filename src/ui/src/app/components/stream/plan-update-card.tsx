import { ListChecks } from 'lucide-react';
import type { PlanUpdateEvent, InspectorTarget } from '../../data/types';
import { uiAccent } from '../../utils/palette';

const plan = uiAccent('plan');

/** Plan update card — dimmed, compact, palette-driven. */
export function PlanUpdateCard({
  event,
  onInspect,
}: {
  event: PlanUpdateEvent;
  onInspect: (target: InspectorTarget) => void;
}) {
  const completed = event.entries.filter((e) => e.status === 'completed').length;
  const total = event.entries.length;

  return (
    <div className="py-0.5">
      <button
        onClick={() => onInspect({ type: 'plan', event })}
        aria-label={`Plan updated: ${completed} of ${total} completed`}
        className="w-full text-left rounded-terminal border border-border/50 bg-muted/10 px-3 py-1.5 hover:bg-muted/20 transition-colors"
      >
        <div className="flex items-center gap-2">
          <ListChecks className={`w-3.5 h-3.5 ${plan.text} opacity-60 shrink-0`} />
          <span className="text-[0.75rem] font-mono text-muted-foreground/60">
            Plan updated
          </span>
          <span className="text-[0.625rem] text-muted-foreground/40 font-mono">
            {completed}/{total}
          </span>
        </div>
      </button>
    </div>
  );
}