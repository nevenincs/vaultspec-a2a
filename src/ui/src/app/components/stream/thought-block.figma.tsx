import figma from '@figma/code-connect'
import { ThoughtBlock } from './thought-block'

/**
 * Code Connect mapping for ThoughtBlock.
 * Collapsible internal agent reasoning block. Collapsed by default, showing
 * "Thinking…" with a chevron toggle. Expanded shows the full thought content
 * in a monospaced, muted italic box.
 *
 * Props:
 * - event: ThoughtEvent — { type: 'thought', content, agent_id, ... }
 */
figma.connect(ThoughtBlock, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  example: () => (
    <ThoughtBlock
      event={{
        id: 'evt-3',
        type: 'thought',
        thread_id: 'thread-1',
        content: 'Let me think through the architecture...',
        agent_id: 'agent-1',
        agent_name: 'Planner',
        timestamp: new Date().toISOString(),
      }}
    />
  ),
})
