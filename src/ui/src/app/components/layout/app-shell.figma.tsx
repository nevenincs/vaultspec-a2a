import figma from '@figma/code-connect';
import { AppShell } from './app-shell';

/**
 * Code Connect mapping for AppShell — the root layout component.
 * AppShell is a singleton that composes Sidebar, TabBar, MessageStream,
 * InputBar, InspectorPanel, StatusBar, and PermissionModal.
 * It manages all Zustand store subscriptions and TanStack Query hooks.
 * No props — all state comes from the appStore vanilla Zustand store.
 */
figma.connect(
  AppShell,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    example: () => <AppShell />,
  },
);
