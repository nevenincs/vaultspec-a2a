import figma from '@figma/code-connect';
import { StatusBar } from './status-bar';

/**
 * Code Connect mapping for StatusBar.
 * Displays WebSocket connection state (connected/reconnecting/disconnected),
 * heartbeat timestamp, and active thread count.
 * No props — reads directly from appStore and useThreadsQuery().
 */
figma.connect(
  StatusBar,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    example: () => <StatusBar />,
  },
);
