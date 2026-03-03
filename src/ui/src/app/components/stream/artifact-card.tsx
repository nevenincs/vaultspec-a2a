import { FileCode } from 'lucide-react';
import type { ArtifactEvent, InspectorTarget } from '../../data/types';
import { uiAccent } from '../../utils/palette';

const art = uiAccent('artifact');

/** Artifact card — dimmed, compact, palette-driven. */
export function ArtifactCard({
  event,
  onInspect,
}: {
  event: ArtifactEvent;
  onInspect: (target: InspectorTarget) => void;
}) {
  return (
    <div className="py-0.5">
      <button
        onClick={() => onInspect({ type: 'artifact', event })}
        aria-label={`Artifact: ${event.filename}, ${event.old_content ? 'modified' : 'created'}`}
        className="rounded-terminal border-border/50 bg-muted/10 hover:bg-muted/20 w-full border px-3 py-1.5 text-left transition-colors"
      >
        <div className="flex items-center gap-2">
          <FileCode className={`h-3.5 w-3.5 ${art.text} shrink-0 opacity-70`} />
          <span className="text-muted-foreground font-mono text-[0.75rem]">
            {event.filename}
          </span>
          <span className="text-muted-foreground font-mono text-[0.625rem] opacity-80">
            {event.old_content ? 'modified' : 'created'}
          </span>
        </div>
      </button>
    </div>
  );
}
