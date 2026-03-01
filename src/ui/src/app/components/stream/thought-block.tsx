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
        className="flex items-center gap-1.5 text-[0.75rem] text-muted-foreground hover:text-foreground transition-colors w-full text-left"
      >
        {expanded ? (
          <ChevronDown className="w-3 h-3 shrink-0" />
        ) : (
          <ChevronRight className="w-3 h-3 shrink-0" />
        )}
        <span className="italic">Thinking…</span>
      </button>
      {expanded && (
        <div className="mt-1 px-3 py-2 rounded-terminal bg-muted/20 border border-border/50">
          <p className="text-[0.75rem] text-muted-foreground italic whitespace-pre-wrap font-mono">
            {event.content}
          </p>
        </div>
      )}
    </div>
  );
}