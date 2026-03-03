import { AlertTriangle } from 'lucide-react';
import { useEffect } from 'react';
import type { ErrorStreamEvent } from '../../data/types';
import { log } from '../../utils/logger';

export function ErrorAlert({ event }: { event: ErrorStreamEvent }) {
  // Surface stream errors through the centralized logger
  useEffect(() => {
    log.error('stream.error', event.message, { code: event.code });
  }, [event.message, event.code]);

  return (
    <div className="px-4 py-1.5">
      <div
        className="rounded-ui border-status-error/30 bg-status-error/5 relative w-full border px-4 py-3 text-[0.8125rem]"
        role="alert"
      >
        <div className="flex items-start gap-3">
          <AlertTriangle className="text-status-error mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-status-error font-medium">Error</p>
            <p className="text-foreground/80 mt-0.5">{event.message}</p>
            {event.code && (
              <span className="text-muted-foreground/70 mt-1 block font-mono text-[0.6875rem]">
                Code: {event.code}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
