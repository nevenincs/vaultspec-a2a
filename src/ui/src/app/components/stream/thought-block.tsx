import { useState } from 'react';
import { ChevronRight, ChevronDown } from 'lucide-react';
import type { ThoughtEvent } from '../../data/types';

/** Thought block — rendered inside an agent capsule, no agent name needed. */
export function ThoughtBlock({ event }: { event: ThoughtEvent }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="py-0.5">
      <button
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-label={expanded ? 'Collapse thought' : 'Expand thought'}
        className="text-muted-foreground hover:text-foreground flex w-full items-center gap-1.5 text-left text-[0.75rem] transition-colors"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0" />
        )}
        <span className="italic">Thinking…</span>
      </button>
      {expanded && (
        <div className="rounded-terminal bg-muted/20 border-border/50 mt-1 border px-3 py-2">
          <p className="text-muted-foreground font-mono text-[0.75rem] whitespace-pre-wrap italic">
            {event.content}
          </p>
        </div>
      )}
    </div>
  );
}
