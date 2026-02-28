// ---------------------------------------------------------------------------
// App state store — Svelte 5 Runes
// Master state orchestrator: theme, connection, sidebar
// ---------------------------------------------------------------------------

import type { ConnectionState, ThemeMode } from '$lib/data/types';

export class AppStateStore {
  // --- Theme ---
  themeMode: ThemeMode = $state('dark');

  // --- Connection ---
  connectionState: ConnectionState = $state('disconnected');
  lastHeartbeat: number = $state(Date.now());

  // --- Sidebar ---
  sidebarCollapsed: boolean = $state(false);
  sidebarWidth: number = $state(240);

  constructor() {
    // Apply initial theme
    this.#applyTheme(this.themeMode);

    // Watch for system preference changes
    if (typeof window !== 'undefined') {
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      mq.addEventListener('change', () => {
        if (this.themeMode === 'system') {
          this.#applyTheme('system');
        }
      });
    }
  }

  setThemeMode(mode: ThemeMode): void {
    this.themeMode = mode;
    this.#applyTheme(mode);
  }

  #applyTheme(mode: ThemeMode): void {
    if (typeof document === 'undefined') return;
    const root = document.documentElement;
    if (mode === 'dark') {
      root.classList.add('dark');
    } else if (mode === 'light') {
      root.classList.remove('dark');
    } else {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      if (prefersDark) root.classList.add('dark');
      else root.classList.remove('dark');
    }
  }

  setConnectionState(state: ConnectionState): void {
    this.connectionState = state;
  }

  updateHeartbeat(): void {
    this.lastHeartbeat = Date.now();
  }

  toggleSidebar(): void {
    this.sidebarCollapsed = !this.sidebarCollapsed;
  }

  setSidebarWidth(width: number): void {
    // Clamp between 180 and 420
    this.sidebarWidth = Math.max(180, Math.min(420, width));
  }
}

// ---------------------------------------------------------------------------
// Singleton store instance
// ---------------------------------------------------------------------------

export const appState = new AppStateStore();
