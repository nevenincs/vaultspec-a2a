import { log } from '../../utils/logger';
import type { StateCreator } from 'zustand';
import type { ThemeMode, InspectorTarget, ContextDocument } from '../../data/types';
import type { AppStore } from '../app-store';

export interface UiSlice {
  // Persisted
  themeMode: ThemeMode;
  sidebarCollapsed: boolean;
  sidebarWidth: number;
  // Session-transient
  inspectorTarget: InspectorTarget | null;
  contextDocuments: ContextDocument[];

  setThemeMode: (mode: ThemeMode) => void;
  toggleSidebar: () => void;
  setSidebarWidth: (w: number) => void;
  openInspector: (target: InspectorTarget) => void;
  closeInspector: () => void;
  openDocument: (doc: ContextDocument) => void;
  toggleContextPanel: (docs: ContextDocument[]) => void;
}

function applyThemeToDocument(mode: ThemeMode): void {
  const root = document.documentElement;
  if (mode === 'dark') {
    root.classList.add('dark');
  } else if (mode === 'light') {
    root.classList.remove('dark');
  } else {
    // system
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (prefersDark) root.classList.add('dark');
    else root.classList.remove('dark');
  }
  log.debug('ui.theme', `Theme set to ${mode}`);
}

export const createUiSlice: StateCreator<
  AppStore,
  [['zustand/devtools', never], ['zustand/persist', unknown], ['zustand/immer', never]],
  [],
  UiSlice
> = (set) => ({
  themeMode: 'dark',
  sidebarCollapsed: false,
  sidebarWidth: 240,
  inspectorTarget: null,
  contextDocuments: [],

  setThemeMode: (mode) => {
    applyThemeToDocument(mode);
    set(
      (draft) => {
        draft.themeMode = mode;
      },
      false,
      'ui/setThemeMode',
    );
  },

  toggleSidebar: () =>
    set(
      (draft) => {
        draft.sidebarCollapsed = !draft.sidebarCollapsed;
      },
      false,
      'ui/toggleSidebar',
    ),

  setSidebarWidth: (w) =>
    set(
      (draft) => {
        draft.sidebarWidth = w;
      },
      false,
      'ui/setSidebarWidth',
    ),

  openInspector: (target) =>
    set(
      (draft) => {
        draft.inspectorTarget = target;
      },
      false,
      'ui/openInspector',
    ),

  closeInspector: () =>
    set(
      (draft) => {
        draft.inspectorTarget = null;
      },
      false,
      'ui/closeInspector',
    ),

  openDocument: (doc) =>
    set(
      (draft) => {
        draft.inspectorTarget = { type: 'document', document: doc };
      },
      false,
      'ui/openDocument',
    ),

  toggleContextPanel: (docs) =>
    set(
      (draft) => {
        if (draft.inspectorTarget?.type === 'context_list') {
          draft.inspectorTarget = null;
        } else {
          draft.inspectorTarget = { type: 'context_list', documents: docs };
        }
      },
      false,
      'ui/toggleContextPanel',
    ),
});
