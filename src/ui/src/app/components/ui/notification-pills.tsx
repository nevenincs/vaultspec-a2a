/**
 * NotificationPills
 * ─────────────────────────────────────────────────────────
 * Floating pill-shaped notifications that surface logger
 * warnings, errors, and info messages to the user.
 *
 * Design:
 *   - Fixed position, bottom-right, stacked vertically
 *   - Frosted glass (backdrop-blur) background using oxide tokens
 *   - Status-colored left accent stripe
 *   - Subtle enter/exit animations via Motion
 *   - Manual dismiss (X) + auto-dismiss timer progress bar
 *   - Fully themed via oxide tokens — no ad-hoc colors
 */

import { X, AlertTriangle, Info, AlertCircle, CheckCircle } from 'lucide-react';
import { forwardRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useNotifications, type Notification } from '../../hooks/use-notifications';
import type { LogLevel } from '../../utils/logger';

// ── Status color mapping (oxide token classes) ─────────────────────────────

const LEVEL_CONFIG: Record<
  LogLevel,
  {
    icon: typeof Info;
    stripe: string;
    iconColor: string;
    bg: string;
    border: string;
    label: string;
  }
> = {
  debug: {
    icon: Info,
    stripe: 'bg-muted-foreground',
    iconColor: 'text-muted-foreground',
    bg: 'bg-oxide-terminal-bg/80',
    border: 'border-border/40',
    label: 'Debug',
  },
  info: {
    icon: CheckCircle,
    stripe: 'bg-status-info',
    iconColor: 'text-status-info',
    bg: 'bg-oxide-terminal-bg/80',
    border: 'border-status-info/20',
    label: 'Info',
  },
  warn: {
    icon: AlertTriangle,
    stripe: 'bg-status-warning',
    iconColor: 'text-status-warning',
    bg: 'bg-oxide-terminal-bg/80',
    border: 'border-status-warning/20',
    label: 'Warning',
  },
  error: {
    icon: AlertCircle,
    stripe: 'bg-status-error',
    iconColor: 'text-status-error',
    bg: 'bg-oxide-terminal-bg/80',
    border: 'border-status-error/20',
    label: 'Error',
  },
};

// ── Single pill ────────────────────────────────────────────────────────────

const NotificationPill = forwardRef<
  HTMLDivElement,
  { notification: Notification; onDismiss: (id: number) => void }
>(function NotificationPill({ notification, onDismiss }, ref) {
  const config = LEVEL_CONFIG[notification.level];
  const Icon = config.icon;

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 10, scale: 0.95, transition: { duration: 0.2 } }}
      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
      className={`rounded-bubble relative flex max-w-[26rem] min-w-[18rem] items-start gap-2.5 border ${config.border} ${config.bg} pointer-events-auto overflow-hidden shadow-lg shadow-black/10 backdrop-blur-xl dark:shadow-black/30`}
      role="alert"
      aria-live={notification.level === 'error' ? 'assertive' : 'polite'}
      aria-label={`${config.label}: ${notification.message}`}
    >
      {/* Left accent stripe */}
      <div className={`absolute top-0 bottom-0 left-0 w-[3px] ${config.stripe}`} />

      {/* Content */}
      <div className="flex min-w-0 flex-1 items-start gap-2.5 py-2.5 pr-2 pl-3.5">
        <Icon className={`h-4 w-4 ${config.iconColor} mt-0.5 shrink-0`} />

        <div className="min-w-0 flex-1">
          {/* Source namespace */}
          <div className="mb-0.5 flex items-center gap-2">
            <span className="text-oxide-metadata truncate font-mono text-[0.5625rem] tracking-widest uppercase">
              {notification.source}
            </span>
            <span className="text-oxide-metadata shrink-0 text-[0.5rem] tabular-nums">
              {new Date(notification.ts).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
              })}
            </span>
          </div>

          {/* Message */}
          <p className="text-foreground/90 text-[0.75rem] break-words">
            {notification.message}
          </p>

          {/* Optional data preview */}
          {notification.data != null && (
            <pre className="text-oxide-metadata mt-1 max-w-full truncate font-mono text-[0.625rem]">
              {typeof notification.data === 'string'
                ? notification.data
                : JSON.stringify(notification.data)}
            </pre>
          )}
        </div>

        {/* Dismiss button */}
        <button
          onClick={() => onDismiss(notification.id)}
          className="rounded-control text-oxide-metadata hover:text-foreground hover:bg-muted/60 shrink-0 p-1 transition-colors"
          aria-label="Dismiss notification"
        >
          <X className="h-3 w-3" />
        </button>
      </div>

      {/* Auto-dismiss progress bar */}
      {notification.dismissAfter > 0 && (
        <motion.div
          className={`absolute bottom-0 left-0 h-[2px] ${config.stripe} opacity-40`}
          initial={{ width: '100%' }}
          animate={{ width: '0%' }}
          transition={{ duration: notification.dismissAfter / 1000, ease: 'linear' }}
        />
      )}
    </motion.div>
  );
});

// ── Pill container (fixed overlay) ─────────────────────────────────────────

export function NotificationPills() {
  const { notifications, dismissNotification, clearAll } = useNotifications();

  return (
    <div
      className="pointer-events-none fixed right-4 bottom-8 z-50 flex flex-col-reverse gap-2"
      aria-label="Notifications"
      role="log"
      aria-live="polite"
    >
      <AnimatePresence mode="popLayout">
        {notifications.map((n) => (
          <NotificationPill
            key={n.id}
            notification={n}
            onDismiss={dismissNotification}
          />
        ))}
      </AnimatePresence>

      {/* Clear-all button when 3+ visible */}
      <AnimatePresence>
        {notifications.length >= 3 && (
          <motion.button
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            onClick={clearAll}
            className="text-oxide-metadata hover:text-foreground bg-oxide-terminal-bg/60 border-border/30 pointer-events-auto self-end rounded-full border px-3 py-1 font-mono text-[0.625rem] tracking-widest uppercase backdrop-blur-lg transition-colors"
            aria-label="Clear all notifications"
          >
            Clear all
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}
