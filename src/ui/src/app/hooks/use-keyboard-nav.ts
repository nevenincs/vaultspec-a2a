/**
 * use-keyboard-nav.ts
 * ─────────────────────────────────────────────────────────
 * Centralized keyboard shortcut registry for vaultspec-a2a.
 *
 * All global shortcuts are declared as data in SHORTCUT_MAP,
 * so they're discoverable from one place. The hook attaches a
 * single `keydown` listener and dispatches to registered actions.
 *
 * Section cycling (F6 / Shift+F6) moves focus between the major
 * UI regions: sidebar → tab-bar → stream → input → inspector.
 */

import { useEffect, useCallback, useRef } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';

// ── Section cycling ──────────────────────────────────────────────────────────

/** Ordered list of focusable UI sections (data-focus-section attribute values). */
const FOCUS_SECTIONS = [
  'sidebar',
  'tab-bar',
  'stream',
  'input-bar',
  'inspector',
] as const;

export type FocusSection = (typeof FOCUS_SECTIONS)[number];

/**
 * Focus the first tabbable element within a section,
 * or the section container itself if no tabbable child exists.
 */
function focusSection(sectionId: FocusSection) {
  const section = document.querySelector(
    `[data-focus-section="${sectionId}"]`,
  ) as HTMLElement | null;
  if (!section) return false;

  const focusable = section.querySelector<HTMLElement>(
    'button:not([disabled]):not([tabindex="-1"]), ' +
      'input:not([disabled]):not([tabindex="-1"]), ' +
      'textarea:not([disabled]):not([tabindex="-1"]), ' +
      'a[href]:not([tabindex="-1"]), ' +
      '[tabindex="0"]',
  );
  if (focusable) {
    focusable.focus();
    return true;
  }

  // Fall back to the section container
  if (section.tabIndex < 0) section.tabIndex = -1;
  section.focus();
  return true;
}

function cycleSections(reverse: boolean) {
  const active = document.activeElement as HTMLElement | null;
  let currentIdx = -1;

  // Find which section currently holds focus
  for (let i = 0; i < FOCUS_SECTIONS.length; i++) {
    const sec = document.querySelector(`[data-focus-section="${FOCUS_SECTIONS[i]}"]`);
    if (sec?.contains(active)) {
      currentIdx = i;
      break;
    }
  }

  // Walk forward/backward, skipping sections not in the DOM
  const len = FOCUS_SECTIONS.length;
  for (let step = 1; step <= len; step++) {
    const nextIdx = reverse
      ? (currentIdx - step + len) % len
      : (currentIdx + step) % len;
    if (focusSection(FOCUS_SECTIONS[nextIdx])) return;
  }
}

// ── Shortcut definitions ─────────────────────────────────────────────────────

export interface ShortcutDef {
  /** Human-readable label (for help display) */
  label: string;
  /** Group heading */
  group: 'Navigation' | 'Tabs' | 'Panels' | 'Editor';
  /** Modifier keys */
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  /** e.key value (case-insensitive match) */
  key: string;
}

/**
 * Registry of all keyboard shortcuts.
 * The keys are action IDs referenced in the dispatch switch.
 */
export const SHORTCUT_MAP: Record<string, ShortcutDef> = {
  // ── Navigation ──
  cycleSectionForward: {
    label: 'Next section',
    group: 'Navigation',
    key: 'F6',
  },
  cycleSectionBack: {
    label: 'Previous section',
    group: 'Navigation',
    key: 'F6',
    shift: true,
  },
  focusInput: {
    label: 'Focus message input',
    group: 'Navigation',
    ctrl: true,
    key: '/',
  },
  focusSidebarSearch: {
    label: 'Focus sidebar search',
    group: 'Navigation',
    ctrl: true,
    key: 'k',
  },

  // ── Panels ──
  toggleSidebar: {
    label: 'Toggle sidebar',
    group: 'Panels',
    ctrl: true,
    key: '.',
  },
  closeInspector: {
    label: 'Close inspector',
    group: 'Panels',
    ctrl: true,
    key: 'i',
  },
  escapePanel: {
    label: 'Dismiss / close panel',
    group: 'Panels',
    key: 'Escape',
  },

  // ── Tabs ──
  newTask: {
    label: 'New task',
    group: 'Tabs',
    ctrl: true,
    key: 'n',
  },
  closeTab: {
    label: 'Close current tab',
    group: 'Tabs',
    ctrl: true,
    key: 'w',
  },
  nextTab: {
    label: 'Next tab',
    group: 'Tabs',
    ctrl: true,
    key: 'Tab',
  },
  prevTab: {
    label: 'Previous tab',
    group: 'Tabs',
    ctrl: true,
    shift: true,
    key: 'Tab',
  },
  tab1: { label: 'Switch to tab 1', group: 'Tabs', ctrl: true, key: '1' },
  tab2: { label: 'Switch to tab 2', group: 'Tabs', ctrl: true, key: '2' },
  tab3: { label: 'Switch to tab 3', group: 'Tabs', ctrl: true, key: '3' },
  tab4: { label: 'Switch to tab 4', group: 'Tabs', ctrl: true, key: '4' },
  tab5: { label: 'Switch to tab 5', group: 'Tabs', ctrl: true, key: '5' },
  tab6: { label: 'Switch to tab 6', group: 'Tabs', ctrl: true, key: '6' },
  tab7: { label: 'Switch to tab 7', group: 'Tabs', ctrl: true, key: '7' },
  tab8: { label: 'Switch to tab 8', group: 'Tabs', ctrl: true, key: '8' },
  tab9: { label: 'Switch to tab 9 (last)', group: 'Tabs', ctrl: true, key: '9' },

  // ── Editor ──
  showShortcuts: {
    label: 'Show keyboard shortcuts',
    group: 'Navigation',
    ctrl: true,
    shift: true,
    key: '?',
  },
};

// ── Hook ─────────────────────────────────────────────────────────────────────

interface UseKeyboardNavActions {
  toggleSidebar: () => void;
  closeInspector: () => void;
  clearActiveTab: () => void;
  closeCurrentTab: () => void;
  nextTab: () => void;
  prevTab: () => void;
  activateTabByIndex: (index: number) => void;
  focusSidebarSearch: () => void;
  hasInspector: boolean;
}

export function useKeyboardNav(actions: UseKeyboardNavActions) {
  const actionsRef = useRef(actions);
  actionsRef.current = actions;

  const handler = useCallback((e: KeyboardEvent) => {
    const a = actionsRef.current;

    // Don't capture shortcuts when user is typing in an input/textarea,
    // UNLESS it's a modifier combo (Ctrl/Cmd + key).
    const target = e.target as HTMLElement;
    const isEditing =
      target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.isContentEditable;
    const hasModifier = e.ctrlKey || e.metaKey;

    // ── Section cycling: F6 / Shift+F6 — always active ──
    if (e.key === 'F6') {
      e.preventDefault();
      cycleSections(e.shiftKey);
      return;
    }

    // If editing and no modifier, let the event pass through
    if (isEditing && !hasModifier) return;

    // ── Escape — context sensitive ──
    if (e.key === 'Escape') {
      if (a.hasInspector) {
        a.closeInspector();
        e.preventDefault();
      }
      return;
    }

    // ── Ctrl/Cmd combos ──
    if (!hasModifier) return;

    const key = e.key.toLowerCase();

    // Ctrl+.
    if (key === '.') {
      e.preventDefault();
      a.toggleSidebar();
      return;
    }

    // Ctrl+I — close inspector
    if (key === 'i' && !e.shiftKey) {
      e.preventDefault();
      if (a.hasInspector) a.closeInspector();
      return;
    }

    // Ctrl+N — new task
    if (key === 'n' && !e.shiftKey) {
      e.preventDefault();
      a.clearActiveTab();
      return;
    }

    // Ctrl+W — close current tab
    if (key === 'w' && !e.shiftKey) {
      e.preventDefault();
      a.closeCurrentTab();
      return;
    }

    // Ctrl+Tab / Ctrl+Shift+Tab — cycle tabs
    if (e.key === 'Tab' && hasModifier) {
      e.preventDefault();
      if (e.shiftKey) a.prevTab();
      else a.nextTab();
      return;
    }

    // Ctrl+1..9 — jump to tab
    if (key >= '1' && key <= '9') {
      e.preventDefault();
      a.activateTabByIndex(key === '9' ? -1 : parseInt(key, 10) - 1);
      return;
    }

    // Ctrl+/ — focus input bar
    if (key === '/' || e.key === '/') {
      e.preventDefault();
      focusSection('input-bar');
      return;
    }

    // Ctrl+K — focus sidebar search
    if (key === 'k' && !e.shiftKey) {
      e.preventDefault();
      a.focusSidebarSearch();
      return;
    }
  }, []);

  useEffect(() => {
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handler]);
}

// ── Keyboard helpers for list navigation (arrow keys) ────────────────────────

/**
 * Handles ArrowUp/ArrowDown within a list container.
 * Moves focus to the previous/next focusable sibling.
 * Also handles Home/End for first/last item.
 */
export function handleListKeyDown(
  e: ReactKeyboardEvent,
  opts?: { onSelect?: () => void },
) {
  const target = e.currentTarget as HTMLElement;

  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    opts?.onSelect?.();
    return;
  }

  const container = target.parentElement;
  if (!container) return;

  const items = Array.from(
    container.querySelectorAll<HTMLElement>('button:not([disabled]), [tabindex="0"]'),
  );
  const idx = items.indexOf(target);
  if (idx === -1) return;

  let nextIdx: number | null = null;
  if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
    nextIdx = Math.min(idx + 1, items.length - 1);
  } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
    nextIdx = Math.max(idx - 1, 0);
  } else if (e.key === 'Home') {
    nextIdx = 0;
  } else if (e.key === 'End') {
    nextIdx = items.length - 1;
  }

  if (nextIdx !== null) {
    e.preventDefault();
    items[nextIdx].focus();
  }
}
