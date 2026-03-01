import figma from '@figma/code-connect'
import { ToolCallCard } from './tool-call-card'

/**
 * Code Connect mapping for ToolCallCard.
 * Compact button that shows tool name, status icon (spinner/check/x/circle),
 * and optional location (file:line) or truncated input. Clicking opens the
 * inspector panel with full tool call details.
 *
 * Status icons:
 * - running  → Loader2 (spinning, status-info color)
 * - completed → Check (status-success color)
 * - failed   → X (status-error color, red border)
 * - pending  → Circle (muted)
 *
 * Props:
 * - event: ToolCallEvent — { type: 'tool_call', tool_name, status, input?, location?, ... }
 * - onInspect: (target: InspectorTarget) => void
 */
figma.connect(ToolCallCard, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  example: () => (
    <ToolCallCard
      event={{
        id: 'evt-4',
        type: 'tool_call',
        thread_id: 'thread-1',
        tool_call_id: 'tc-1',
        tool_name: 'read_file',
        status: 'completed',
        tool_kind: 'read',
        input: 'src/lib/api.py',
        agent_id: 'agent-1',
        agent_name: 'Coder',
        timestamp: new Date().toISOString(),
      }}
      onInspect={() => {}}
    />
  ),
})
