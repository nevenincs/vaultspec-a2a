import figma from '@figma/code-connect'
import { UserBubble, AgentBubble } from './message-bubble'
import type { UserMessageEvent, AgentMessageEvent } from '../../data/types'

/**
 * Code Connect mapping for UserBubble.
 * Renders a user message in a monospaced capsule with a left accent stripe.
 * Supports react-markdown with remark-gfm and syntax highlighting.
 *
 * Props:
 * - event: UserMessageEvent — { type: 'user_message', content, timestamp }
 * - isDark?: boolean — selects oneDark vs oneLight syntax highlight style
 */
figma.connect(UserBubble, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  example: () => (
    <UserBubble
      event={{
        id: 'evt-1',
        type: 'user_message',
        thread_id: 'thread-1',
        content: 'Hello, can you help me with this task?',
        timestamp: new Date().toISOString(),
      }}
      isDark={false}
    />
  ),
})

/**
 * Code Connect mapping for AgentBubble.
 * Renders an agent message as flowing text with markdown + syntax highlighting.
 * Shows an animated cursor when streaming is in progress.
 *
 * Props:
 * - event: AgentMessageEvent — { type: 'agent_message', content, streaming, ... }
 * - isDark?: boolean — selects oneDark vs oneLight syntax highlight style
 */
figma.connect(AgentBubble, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  example: () => (
    <AgentBubble
      event={{
        id: 'evt-2',
        type: 'agent_message',
        thread_id: 'thread-1',
        content: 'Here is the analysis...',
        streaming: false,
        agent_id: 'agent-1',
        agent_name: 'Planner',
        timestamp: new Date().toISOString(),
      }}
      isDark={false}
    />
  ),
})
