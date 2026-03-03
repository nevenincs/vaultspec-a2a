import { useStore } from 'zustand';
import { useEffect, useRef } from 'react';
import { log } from '../../utils/logger';
import { appStore } from '../../store/app-store';
import { useThreadsQuery } from '../../queries/use-threads';

export function StatusBar() {
  const connectionState = useStore(appStore, (s) => s.connectionState);
  const lastHeartbeat = useStore(appStore, (s) => s.lastHeartbeat);
  const { data: threads = [] } = useThreadsQuery();

  const prevState = useRef(connectionState);

  // Log connection state transitions
  useEffect(() => {
    if (prevState.current !== connectionState) {
      if (connectionState === 'disconnected') {
        log.error('connection.state', 'Connection lost — events may be stale');
      } else if (connectionState === 'reconnecting') {
        log.warn('connection.state', 'Reconnecting to event stream...');
      } else if (connectionState === 'connected' && prevState.current !== 'connected') {
        log.info('connection.state', 'Connection re-established');
      }
      prevState.current = connectionState;
    }
  }, [connectionState]);

  const heartbeatAgo = ((Date.now() - lastHeartbeat) / 1000).toFixed(1);
  const activeCount = threads.filter(
    (t) => t.agent_state === 'working' || t.agent_state === 'submitted',
  ).length;

  const connDot =
    connectionState === 'connected'
      ? 'bg-status-success'
      : connectionState === 'reconnecting'
        ? 'bg-status-warning'
        : 'bg-status-error';

  const connLabel =
    connectionState === 'connected'
      ? 'Connected'
      : connectionState === 'reconnecting'
        ? 'Reconnecting...'
        : 'Disconnected';

  const barBg =
    connectionState === 'reconnecting'
      ? 'bg-status-warning/5'
      : connectionState === 'disconnected'
        ? 'bg-status-error/5'
        : '';

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={`${connLabel}, ${threads.length} threads, ${activeCount} active`}
      className={`border-border text-oxide-metadata bg-oxide-sidebar-bg flex h-6 shrink-0 items-center justify-between border-t px-4 font-mono text-[0.625rem] tracking-wider uppercase select-none ${barBg}`}
    >
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className={`h-1.5 w-1.5 rounded-full ${connDot}`} />
          <span className="font-bold">{connLabel}</span>
        </div>
        <div className="flex items-center gap-1 opacity-60">
          <span className="text-[0.5625rem]">Latency</span>
          <span className="font-bold">42ms</span>
        </div>
      </div>
      <div className="flex items-center gap-4">
        <div>
          {threads.length} THREAD{threads.length !== 1 ? 'S' : ''} &middot;{' '}
          {activeCount} ACTIVE
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[0.625rem] opacity-60">HEARTBEAT</span>
          <span className="font-bold">{heartbeatAgo}S</span>
        </div>
      </div>
    </div>
  );
}
