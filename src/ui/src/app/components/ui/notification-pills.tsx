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

const LEVEL_CONFIG: Record<LogLevel, {
  icon: typeof Info;
  stripe: string;
  iconColor: string;
  bg: string;
  border: string;
  label: string;
}> = {
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
      className={`
        relative flex items-start gap-2.5 min-w-[18rem] max-w-[26rem]
        rounded-bubble border ${config.border} ${config.bg}
        backdrop-blur-xl shadow-lg shadow-black/10
        dark:shadow-black/30
        overflow-hidden
        pointer-events-auto
      `}
      role="alert"
      aria-live={notification.level === 'error' ? 'assertive' : 'polite'}
      aria-label={`${config.label}: ${notification.message}`}
    >
      {/* Left accent stripe */}
      <div className={`absolute left-0 top-0 bottom-0 w-[3px] ${config.stripe}`} />

      {/* Content */}
      <div className="flex items-start gap-2.5 pl-3.5 pr-2 py-2.5 flex-1 min-w-0">
        <Icon className={`w-4 h-4 ${config.iconColor} shrink-0 mt-0.5`} />

        <div className="flex-1 min-w-0">
          {/* Source namespace */}
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-[0.5625rem] font-mono uppercase tracking-widest text-oxide-metadata truncate">
              {notification.source}
            </span>
            <span className="text-[0.5rem] text-oxide-metadata tabular-nums shrink-0">
              {new Date(notification.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          </div>

          {/* Message */}
          <p className="text-[0.75rem] text-foreground/90 break-words">
            {notification.message}
          </p>

          {/* Optional data preview */}
          {notification.data != null && (
            <pre className="text-[0.625rem] text-oxide-metadata font-mono mt-1 truncate max-w-full">
              {typeof notification.data === 'string'
                ? notification.data
                : JSON.stringify(notification.data)}
            </pre>
          )}
        </div>

        {/* Dismiss button */}
        <button
          onClick={() => onDismiss(notification.id)}
          className="shrink-0 p-1 rounded-control text-oxide-metadata hover:text-foreground hover:bg-muted/60 transition-colors"
          aria-label="Dismiss notification"
        >
          <X className="w-3 h-3" />
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
      className="fixed bottom-8 right-4 z-50 flex flex-col-reverse gap-2 pointer-events-none"
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
            className="
              pointer-events-auto self-end
              text-[0.625rem] font-mono uppercase tracking-widest
              text-oxide-metadata hover:text-foreground
              bg-oxide-terminal-bg/60 backdrop-blur-lg
              border border-border/30 rounded-full
              px-3 py-1 transition-colors
            "
            aria-label="Clear all notifications"
          >
            Clear all
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}