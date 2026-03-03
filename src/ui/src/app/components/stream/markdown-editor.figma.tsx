import figma from '@figma/code-connect';
import { MarkdownEditor } from './markdown-editor';

/**
 * Code Connect mapping for MarkdownEditor.
 * A custom syntax-highlighted textarea that renders markdown tokens inline
 * (bold, italic, code, headings, links, blockquotes, lists). Uses a hidden
 * real textarea + a visible overlay div for coloring. Supports all standard
 * textarea events and imperative ref access via getEditorTextarea().
 *
 * Used by InputBar as the composition surface.
 *
 * Props:
 * - value: string — the markdown text content
 * - onChange: (value: string) => void
 * - onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement>) => void
 * - placeholder?: string
 * - style?: React.CSSProperties — used for dynamic height resizing
 * - isDark?: boolean — token color palette
 */
figma.connect(
  MarkdownEditor,
  'https://www.figma.com/make/EAs7Eh1lxKVzBqzke5HASU/VaultSpec-A2A-Control-Surface',
  {
    example: () => (
      <MarkdownEditor
        value=""
        onChange={() => {}}
        onKeyDown={() => {}}
        placeholder="Type a message..."
      />
    ),
  },
);
