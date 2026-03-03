import figma from '@figma/code-connect';
import { InspectorPanel } from './inspector-panel';

/**
 * Code Connect mapping for InspectorPanel.
 * A side panel that opens when the user inspects a tool call, artifact,
 * plan, or context list. Renders different views based on target.type:
 * - 'tool_call' → shows tool name, status, input/output with syntax highlighting
 * - 'artifact' → shows file content or diff (old vs new) with language detection
 * - 'plan' → shows full plan with status indicators per entry
 * - 'context_list' → shows the list of context documents (vault refs)
 * - 'document' → shows a single document with syntax highlighting
 *
 * Includes a copy-to-clipboard button and optional external link.
 * ResizableHandle at the left edge allows width adjustment (260–700px).
 *
 * Props:
 * - target: InspectorTarget — discriminated union of the above types
 * - onClose: () => void
 * - isDark?: boolean — for syntax highlighter theme
 * - onOpenDocument?: (doc: ContextDocument) => void
 */
figma.connect(
  InspectorPanel,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    example: () => (
      <InspectorPanel
        target={{
          type: 'tool_call',
          event: {
            id: 'evt-4',
            type: 'tool_call',
            thread_id: 'thread-1',
            tool_call_id: 'tc-1',
            tool_name: 'read_file',
            status: 'completed',
            tool_kind: 'read',
            input: 'src/lib/api.py',
            output: '# content here',
            agent_id: 'agent-1',
            agent_name: 'Coder',
            timestamp: new Date().toISOString(),
          },
        }}
        onClose={() => {}}
      />
    ),
  },
);
