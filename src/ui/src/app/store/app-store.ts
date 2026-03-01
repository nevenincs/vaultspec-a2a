/**
 * Vanilla Zustand store composed from 5 slices.
 *
 * Architecture (ADR-018 §2.2):
 * - Vanilla store (createStore) so WS bridge can call store.getState() outside React
 * - Middleware: devtools > persist > immer (outermost → innermost)
 * - Persist scope: themeMode, sidebarCollapsed, sidebarWidth only
 */

import { createStore } from 'zustand/vanilla';
import { devtools, persist } from 'zustand/middleware';
import { immer } from 'zustand/middleware/immer';

import { createStreamSlice, type StreamSlice } from './slices/stream-slice';
import { createConnectionSlice, type ConnectionSlice } from './slices/connection-slice';
import { createPermissionSlice, type PermissionSlice } from './slices/permission-slice';
import { createTabSlice, type TabSlice } from './slices/tab-slice';
import { createUiSlice, type UiSlice } from './slices/ui-slice';

export type AppStore = StreamSlice &
  ConnectionSlice &
  PermissionSlice &
  TabSlice &
  UiSlice;

type PersistedState = Pick<UiSlice, 'themeMode' | 'sidebarCollapsed' | 'sidebarWidth'>;

export const appStore = createStore<AppStore>()(
  devtools(
    persist(
      immer((...args) => ({
        ...createStreamSlice(...args),
        ...createConnectionSlice(...args),
        ...createPermissionSlice(...args),
        ...createTabSlice(...args),
        ...createUiSlice(...args),
      })),
      {
        name: 'vaultspec-ui-prefs',
        partialize: (state): PersistedState => ({
          themeMode: state.themeMode,
          sidebarCollapsed: state.sidebarCollapsed,
          sidebarWidth: state.sidebarWidth,
        }),
      },
    ),
    {
      name: 'VaultSpec AppStore',
      enabled: import.meta.env.DEV,
    },
  ),
);
