/**
 * ═══════════════════════════════════════════════════════════════════════════════
 * VaultSpec Logger — Centralized logging & notification bus
 * ═══════════════════════════════════════════════════════════════════════════════
 *
 * USAGE:
 *   import { log } from '../utils/logger';
 *
 *   log.info('thread.created', 'Thread abc-123 created');
 *   log.warn('sse.reconnect', 'Connection lost, retrying…');
 *   log.error('api.send', 'Failed to send message', { status: 500 });
 *   log.debug('render.stream', 'Re-rendered with 42 events');
 *
 * SURFACE BEHAVIOR:
 *   - debug: console only (hidden in production)
 *   - info:  console + optional UI pill notification
 *   - warn:  console + UI pill notification
 *   - error: console.error + UI pill notification
 *
 * UI NOTIFICATIONS:
 *   Components call `log.subscribe(callback)` to receive entries that
 *   should be surfaced. The NotificationPills component does this
 *   automatically via the `useNotifications` hook.
 *
 * STRUCTURED ENTRIES:
 *   Every log entry carries a `source` tag (dot-separated namespace)
 *   so entries are filterable and grep-able in the console.
 *
 * RING BUFFER:
 *   The last N entries are retained in memory for debugging. Access
 *   via `log.history()` in the browser console.
 * ═══════════════════════════════════════════════════════════════════════════════
 */

// ── Types ────────────────────────────────────────────────────────────────────

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface LogEntry {
  /** Monotonic id */
  id: number;
  /** ISO-8601 timestamp */
  ts: string;
  /** Severity level */
  level: LogLevel;
  /** Dot-separated source namespace (e.g. 'thread.create', 'sse.reconnect') */
  source: string;
  /** Human-readable message */
  message: string;
  /** Optional structured data payload */
  data?: unknown;
  /** Whether this entry should surface as a UI notification pill */
  surface: boolean;
  /** Auto-dismiss delay in ms (0 = manual dismiss only) */
  dismissAfter: number;
}

export type LogSubscriber = (entry: LogEntry) => void;

// ── Configuration ────────────────────────────────────────────────────────────

const MAX_HISTORY = 500;

/** Default auto-dismiss delays per level (ms). 0 = sticky. */
const DEFAULT_DISMISS: Record<LogLevel, number> = {
  debug: 0,
  info: 4000,
  warn: 6000,
  error: 0, // errors require manual dismiss
};

// ── Singleton state ──────────────────────────────────────────────────────────

let _nextId = 1;
const _history: LogEntry[] = [];
const _subscribers = new Set<LogSubscriber>();

// ── Core emit ────────────────────────────────────────────────────────────────

function emit(
  level: LogLevel,
  source: string,
  message: string,
  data?: unknown,
  opts?: { surface?: boolean; dismissAfter?: number },
): LogEntry {
  const entry: LogEntry = {
    id: _nextId++,
    ts: new Date().toISOString(),
    level,
    source,
    message,
    data,
    surface: opts?.surface ?? level !== 'debug',
    dismissAfter: opts?.dismissAfter ?? DEFAULT_DISMISS[level],
  };

  // Ring buffer
  _history.push(entry);
  if (_history.length > MAX_HISTORY) _history.shift();

  // Console output — structured
  const tag = `[${level.toUpperCase()}] ${source}`;
  switch (level) {
    case 'debug':
      // eslint-disable-next-line no-console
      console.debug(tag, message, data ?? '');
      break;
    case 'info':
      // eslint-disable-next-line no-console
      console.info(tag, message, data ?? '');
      break;
    case 'warn':
      // eslint-disable-next-line no-console
      console.warn(tag, message, data ?? '');
      break;
    case 'error':
      // eslint-disable-next-line no-console
      console.error(tag, message, data ?? '');
      break;
  }

  // Notify subscribers (UI layer)
  if (entry.surface) {
    _subscribers.forEach((fn) => {
      try {
        fn(entry);
      } catch {
        // Subscriber threw — swallow to avoid cascade
      }
    });
  }

  return entry;
}

// ── Public API ───────────────────────────────────────────────────────────────

export const log = {
  /**
   * Debug — console only, never surfaces to UI.
   * Use for render counts, state snapshots, internal diagnostics.
   */
  debug(source: string, message: string, data?: unknown) {
    return emit('debug', source, message, data, { surface: false });
  },

  /**
   * Info — console + optional UI pill (short auto-dismiss).
   * Use for successful operations the user should see confirmation of.
   */
  info(
    source: string,
    message: string,
    data?: unknown,
    opts?: { surface?: boolean; dismissAfter?: number },
  ) {
    return emit('info', source, message, data, opts);
  },

  /**
   * Warn — console + UI pill (medium auto-dismiss).
   * Use for degraded states, retries, non-critical failures.
   */
  warn(
    source: string,
    message: string,
    data?: unknown,
    opts?: { dismissAfter?: number },
  ) {
    return emit('warn', source, message, data, { surface: true, ...opts });
  },

  /**
   * Error — console.error + UI pill (sticky, manual dismiss).
   * Use for failures that block the user or lose data.
   */
  error(
    source: string,
    message: string,
    data?: unknown,
    opts?: { dismissAfter?: number },
  ) {
    return emit('error', source, message, data, { surface: true, ...opts });
  },

  /**
   * Subscribe to surfaced log entries. Returns unsubscribe function.
   */
  subscribe(fn: LogSubscriber): () => void {
    _subscribers.add(fn);
    return () => _subscribers.delete(fn);
  },

  /**
   * Access the in-memory ring buffer (for console debugging).
   */
  history(): readonly LogEntry[] {
    return _history;
  },

  /**
   * Filter history by level.
   */
  filter(level: LogLevel): LogEntry[] {
    return _history.filter((e) => e.level === level);
  },

  /**
   * Clear history (useful in tests).
   */
  clear() {
    _history.length = 0;
  },
};

// Expose on window for console debugging
if (typeof window !== 'undefined') {
  (window as unknown as Record<string, unknown>).__vaultspec_log = log;
}
