import figma from '@figma/code-connect';
import { TabBar } from './tab-bar';

/**
 * Code Connect mapping for TabBar.
 * VS Code-style tab system: transient tabs open on single-click,
 * pinned tabs open on double-click or deep-link navigation.
 * Renders null when there are no open tabs.
 *
 * Props:
 * - tabs: EditorTab[] — from appStore.tabs
 * - activeTabId: string | null — from appStore.activeTabId
 * - threads: ThreadSummary[] — from useThreadsQuery() for label/state lookup
 * - activateTab: (threadId) => void
 * - pinTab: (threadId) => void
 * - closeTab: (threadId) => void
 */
figma.connect(
  TabBar,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    example: () => (
      <TabBar
        tabs={[]}
        activeTabId={null}
        threads={[]}
        activateTab={() => {}}
        pinTab={() => {}}
        closeTab={() => {}}
      />
    ),
  },
);
