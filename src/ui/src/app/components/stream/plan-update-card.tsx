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
        className="rounded-terminal border-border/50 bg-muted/10 hover:bg-muted/20 w-full border px-3 py-1.5 text-left transition-colors"
      >
        <div className="flex items-center gap-2">
          <ListChecks className={`h-3.5 w-3.5 ${plan.text} shrink-0 opacity-60`} />
          <span className="text-muted-foreground/60 font-mono text-[0.75rem]">
            Plan updated
          </span>
          <span className="text-muted-foreground/40 font-mono text-[0.625rem]">
            {completed}/{total}
          </span>
        </div>
      </button>
    </div>
  );
}
