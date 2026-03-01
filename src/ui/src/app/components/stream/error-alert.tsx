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
      <div className="relative w-full rounded-ui border border-status-error/30 bg-status-error/5 px-4 py-3 text-[0.8125rem]" role="alert">
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-4 w-4 text-status-error shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="font-medium text-status-error">Error</p>
            <p className="text-foreground/80 mt-0.5">{event.message}</p>
            {event.code && (
              <span className="text-[0.6875rem] block mt-1 text-muted-foreground/70 font-mono">
                Code: {event.code}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}