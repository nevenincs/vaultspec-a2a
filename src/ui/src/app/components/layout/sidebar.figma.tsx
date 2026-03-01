import figma from '@figma/code-connect'
import { Sidebar } from './sidebar'
import type { ThreadSummary } from '../../data/types'

/**
 * Code Connect mapping for Sidebar.
 * The Sidebar lists all threads, supports search (Ctrl+K), collapse/expand,
 * and theme toggling. It receives thread data from TanStack Query via AppShell.
 *
 * Props:
 * - threads: ThreadSummary[] — list from useThreadsQuery()
 * - activeTabId: string | null — currently open tab
 * - openTransient: (threadId) => void — single-click open
 * - openPinned: (threadId) => void — double-click/deep-link open
 * - clearActiveTab: () => void — deselect active tab
 * - onFocusSearchRef: MutableRefObject — exposes Ctrl+K focus trigger to AppShell
 */
figma.connect(Sidebar, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  example: () => (
    <Sidebar
      threads={[]}
      activeTabId={null}
      openTransient={() => {}}
      openPinned={() => {}}
      clearActiveTab={() => {}}
    />
  ),
})
