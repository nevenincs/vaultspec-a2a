import figma from '@figma/code-connect';
import { MessageStream } from './message-stream';

/**
 * Code Connect mapping for MessageStream.
 * Renders the scrollable event stream for a thread. Interleaves UserBubble,
 * AgentBubble, ThoughtBlock, ToolCallCard, ArtifactCard, PlanUpdateCard,
 * and ErrorAlert components from a flat StreamEvent array.
 * Supports search (Ctrl+F), auto-scroll, context panel toggle.
 *
 * Props:
 * - events: StreamEvent[] — from appStore.streamEvents[activeTabId]
 * - onInspect: (target: InspectorTarget) => void — opens inspector panel
 * - emptyState: boolean — shows empty thread state when true
 * - teamPreset?: TeamPreset — active team topology info for working indicator
 * - agents?: AgentSummary[] — for agent capsule grouping
 * - agentState: AgentLifecycleState — drives the working indicator
 * - onOpenDocument?: (doc) => void — opens document in inspector
 * - onToggleContext?: () => void — toggles context panel
 * - isContextOpen?: boolean — context panel open state
 * - contextDocumentCount?: number — badge count on context button
 * - isDark?: boolean — for syntax highlighter theme selection
 */
figma.connect(
  MessageStream,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    example: () => (
      <MessageStream
        events={[]}
        onInspect={() => {}}
        emptyState={false}
        agentState="idle"
      />
    ),
  },
);
