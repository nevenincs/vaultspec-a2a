import figma from '@figma/code-connect';
import { PermissionModal } from './permission-modal';

/**
 * Code Connect mapping for PermissionModal.
 * A blocking AlertDialog that presents a permission request from an agent.
 * Shows agent name, tool name (with kind icon), message, and action buttons.
 * Buttons vary by option.kind:
 * - 'allow'        → default variant (filled)
 * - 'deny'         → outline with red text/border
 * - 'allow_always' → secondary variant
 * - other          → ghost variant
 *
 * If multiple permissions are queued, shows a "1 of N pending" badge.
 * Permission responses MUST go via REST (not WebSocket) per ADR-011.
 *
 * Props:
 * - request: PermissionRequest — from appStore.permissionQueue[0]
 * - queueLength: number — total queue length for the badge
 * - onRespond: (requestId, optionId) => void — calls useRespondToPermission mutation
 */
figma.connect(
  PermissionModal,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    example: () => (
      <PermissionModal
        request={{
          id: 'req-1',
          thread_id: 'thread-1',
          agent_id: 'agent-1',
          agent_name: 'Coder',
          tool_name: 'bash',
          tool_kind: 'execute',
          message: 'Run: npm install @figma/code-connect',
          options: [
            { id: 'allow', label: 'Allow', kind: 'allow' },
            { id: 'deny', label: 'Deny', kind: 'deny' },
          ],
        }}
        queueLength={1}
        onRespond={() => {}}
      />
    ),
  },
);
