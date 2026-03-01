/**
 * use-notifications.ts
 * ─────────────────────────────────────────────────────────
 * React hook that bridges the logger's subscriber bus into
 * component state. Manages a visible notification queue
 * with auto-dismiss timers.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { log, type LogEntry } from '../utils/logger';

export interface Notification extends LogEntry {
  /** Whether the dismiss animation is in progress */
  exiting: boolean;
}

const MAX_VISIBLE = 5;

export function useNotifications() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const timersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  // Subscribe to logger on mount
  useEffect(() => {
    const unsubscribe = log.subscribe((entry: LogEntry) => {
      const notification: Notification = { ...entry, exiting: false };

      setNotifications((prev) => {
        // Dedupe — don't show the same message twice in quick succession
        const isDupe = prev.some(
          (n) => n.source === entry.source && n.message === entry.message && !n.exiting,
        );
        if (isDupe) return prev;

        const next = [...prev, notification];
        // Trim oldest if over max
        if (next.length > MAX_VISIBLE) {
          return next.slice(next.length - MAX_VISIBLE);
        }
        return next;
      });

      // Auto-dismiss timer
      if (entry.dismissAfter > 0) {
        const timer = setTimeout(() => {
          dismissNotification(entry.id);
        }, entry.dismissAfter);
        timersRef.current.set(entry.id, timer);
      }
    });

    return () => {
      unsubscribe();
      // Clear all timers
      timersRef.current.forEach((t) => clearTimeout(t));
      timersRef.current.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dismissNotification = useCallback((id: number) => {
    // Start exit animation
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, exiting: true } : n)),
    );

    // Remove after animation completes
    setTimeout(() => {
      setNotifications((prev) => prev.filter((n) => n.id !== id));
    }, 300);

    // Clear auto-dismiss timer if it exists
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  const clearAll = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, exiting: true })));
    setTimeout(() => {
      setNotifications([]);
    }, 300);
    timersRef.current.forEach((t) => clearTimeout(t));
    timersRef.current.clear();
  }, []);

  return { notifications, dismissNotification, clearAll };
}
