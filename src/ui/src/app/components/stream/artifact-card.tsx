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
        className="w-full text-left rounded-terminal border border-border/50 bg-muted/10 px-3 py-1.5 hover:bg-muted/20 transition-colors"
      >
        <div className="flex items-center gap-2">
          <FileCode className={`w-3.5 h-3.5 ${art.text} opacity-70 shrink-0`} />
          <span className="text-[0.75rem] font-mono text-muted-foreground">
            {event.filename}
          </span>
          <span className="text-[0.625rem] text-muted-foreground opacity-80 font-mono">
            {event.old_content ? 'modified' : 'created'}
          </span>
        </div>
      </button>
    </div>
  );
}