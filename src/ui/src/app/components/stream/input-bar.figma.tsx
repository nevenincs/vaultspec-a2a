import figma from '@figma/code-connect'
import { InputBar } from './input-bar'

/**
 * Code Connect mapping for InputBar.
 * The primary message composition area. Supports:
 * - Markdown editing via MarkdownEditor (syntax-highlighted textarea)
 * - Team preset selection (popover picker)
 * - Repo / branch / feature tag selection (collapsed pickers for new threads)
 * - Resizable height (100–480px, drag handle)
 * - Send (Enter) / Stop (⏸) via keyboard shortcut or button
 * - Markdown formatting toolbar (bold, italic, code, heading, list)
 * - isDark prop for consistent theming
 *
 * Props:
 * - agentState: AgentLifecycleState — 'idle' | 'working' | 'input_required' | etc.
 * - onSend: (message, opts?) => void
 * - onStop?: () => void
 * - teamPresets?: TeamPreset[]
 * - selectedPreset?: TeamPreset | null
 * - onSelectPreset?: (preset) => void
 * - isNewThread?: boolean — shows repo/branch/tag pickers when true
 * - threads?: ThreadSummary[] — for feature tag extraction
 * - activeThread?: ThreadSummary | null
 * - isDark?: boolean
 */
figma.connect(InputBar, 'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface', {
  example: () => (
    <InputBar
      agentState="idle"
      onSend={() => {}}
      teamPresets={[]}
      isNewThread={true}
    />
  ),
})
