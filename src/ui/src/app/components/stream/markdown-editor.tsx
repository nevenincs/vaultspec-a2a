import {
  forwardRef,
  useRef,
  useEffect,
  useCallback,
  type ChangeEvent,
  type KeyboardEvent,
  type ReactNode,
} from 'react';

// ── Token types ──────────────────────────────────────────────────────────────

interface Token {
  type:
    | 'text'
    | 'bold'
    | 'italic'
    | 'bold-italic'
    | 'code'
    | 'code-block-fence'
    | 'code-block-body'
    | 'heading-marker'
    | 'heading-text'
    | 'link-bracket'
    | 'link-text'
    | 'link-paren'
    | 'link-url'
    | 'list-marker'
    | 'blockquote-marker'
    | 'hr'
    | 'mention'
    | 'strikethrough';
  value: string;
}

// ── Tokeniser ────────────────────────────────────────────────────────────────

function tokenize(src: string): Token[] {
  const tokens: Token[] = [];
  const lines = src.split('\n');

  let inCodeBlock = false;

  for (let li = 0; li < lines.length; li++) {
    const line = lines[li];

    if (li > 0) tokens.push({ type: 'text', value: '\n' });

    // ── Code-fence toggle ──
    if (line.trimStart().startsWith('```')) {
      tokens.push({ type: 'code-block-fence', value: line });
      inCodeBlock = !inCodeBlock;
      continue;
    }

    if (inCodeBlock) {
      tokens.push({ type: 'code-block-body', value: line });
      continue;
    }

    // ── Horizontal rule ──
    if (/^(\s*[-*_]\s*){3,}$/.test(line)) {
      tokens.push({ type: 'hr', value: line });
      continue;
    }

    // ── Heading ──
    const headingMatch = line.match(/^(#{1,6}\s)/);
    if (headingMatch) {
      tokens.push({ type: 'heading-marker', value: headingMatch[1] });
      tokenizeInline(line.slice(headingMatch[1].length), tokens, 'heading-text');
      continue;
    }

    // ── Blockquote ──
    const bqMatch = line.match(/^(>\s?)/);
    if (bqMatch) {
      tokens.push({ type: 'blockquote-marker', value: bqMatch[1] });
      tokenizeInline(line.slice(bqMatch[1].length), tokens);
      continue;
    }

    // ── Unordered / ordered list ──
    const listMatch = line.match(/^(\s*(?:[-*+]|\d+\.)\s)/);
    if (listMatch) {
      tokens.push({ type: 'list-marker', value: listMatch[1] });
      tokenizeInline(line.slice(listMatch[1].length), tokens);
      continue;
    }

    // ── Normal line — inline parse ──
    tokenizeInline(line, tokens);
  }

  return tokens;
}

/** Tokenise inline markdown (bold, italic, code, links, mentions, strikethrough). */
function tokenizeInline(
  src: string,
  out: Token[],
  textType: Token['type'] = 'text'
) {
  const re =
    /(\*\*\*(.+?)\*\*\*)|(\*\*(.+?)\*\*)|(\*(.+?)\*)|(_(.+?)_)|(`([^`]+?)`)|(~~(.+?)~~)|(\[([^\]]*)\]\(([^)]*)\))|(@[A-Za-z][\w]*)/g;

  let lastIndex = 0;
  let m: RegExpExecArray | null;

  while ((m = re.exec(src)) !== null) {
    if (m.index > lastIndex) {
      out.push({ type: textType, value: src.slice(lastIndex, m.index) });
    }

    if (m[1]) {
      out.push({ type: 'bold-italic', value: m[1] });
    } else if (m[3]) {
      out.push({ type: 'bold', value: m[3] });
    } else if (m[5]) {
      out.push({ type: 'italic', value: m[5] });
    } else if (m[7]) {
      out.push({ type: 'italic', value: m[7] });
    } else if (m[9]) {
      out.push({ type: 'code', value: m[9] });
    } else if (m[11]) {
      out.push({ type: 'strikethrough', value: m[11] });
    } else if (m[13]) {
      out.push({ type: 'link-bracket', value: '[' });
      out.push({ type: 'link-text', value: m[14] });
      out.push({ type: 'link-bracket', value: '](' });
      out.push({ type: 'link-url', value: m[15] });
      out.push({ type: 'link-paren', value: ')' });
    } else if (m[0].startsWith('@')) {
      out.push({ type: 'mention', value: m[0] });
    }

    lastIndex = m.index + m[0].length;
  }

  if (lastIndex < src.length) {
    out.push({ type: textType, value: src.slice(lastIndex) });
  }
}

// ── Component ────────────────────────────────────────────────────────────────
 
interface MarkdownEditorProps {
  value: string;
  onChange: (e: ChangeEvent<HTMLTextAreaElement>) => void;
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  onHeightChange?: (height: number) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  /** Extra classes for the textarea (e.g. warning border) */
  inputClassName?: string;
  isDark?: boolean;
}
 
export const MarkdownEditor = forwardRef<HTMLDivElement, MarkdownEditorProps>(
  function MarkdownEditor(
    {
      value,
      onChange,
      onKeyDown,
      onHeightChange,
      placeholder,
      disabled,
      className = '',
      inputClassName = '',
      isDark,
    },
    ref
  ) {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const highlightRef = useRef<HTMLDivElement>(null);
 
    // Sync scroll positions
    const syncScroll = useCallback(() => {
      if (textareaRef.current && highlightRef.current) {
        highlightRef.current.scrollTop = textareaRef.current.scrollTop;
        highlightRef.current.scrollLeft = textareaRef.current.scrollLeft;
      }
    }, []);
 
    useEffect(() => {
      const ta = textareaRef.current;
      if (!ta) return;
      ta.addEventListener('scroll', syncScroll);
      return () => ta.removeEventListener('scroll', syncScroll);
    }, [syncScroll]);
 
    // Auto-expand logic
    useEffect(() => {
      if (textareaRef.current && onHeightChange) {
        // We use a temporary method to measure the content height
        // The highlight div has the same typography and whitespace settings
        // so its scrollHeight should be accurate for the content
        if (highlightRef.current) {
          const contentHeight = highlightRef.current.scrollHeight;
          onHeightChange(contentHeight);
        }
      }
    }, [value, onHeightChange]);
 
    const tokens = tokenize(value);
    const highlighted = renderTokens(tokens);
 
    // Shared typography classes — must match exactly between textarea and highlight div
    const sharedTypography =
      'font-mono text-[0.8125rem] leading-[1.625] px-3 py-2 whitespace-pre-wrap break-words';
 
    // Token styles that adapt to dark/light mode
    const tokenStyle: Record<Token['type'], string> = {
      text: '',
      bold: 'text-foreground font-bold',
      italic: 'text-foreground/80 italic',
      'bold-italic': 'text-foreground font-bold italic',
      code: 'text-accent-1 bg-accent-1/10 rounded px-0.5',
      'code-block-fence': 'text-accent-1/70',
      'code-block-body': 'text-accent-1 bg-accent-1/5',
      'heading-marker': 'text-accent-0 font-bold',
      'heading-text': 'text-foreground font-bold',
      'link-bracket': 'text-accent-0/60',
      'link-text': 'text-accent-0 underline',
      'link-url': 'text-accent-0/60',
      'link-paren': 'text-accent-0/60',
      'list-marker': 'text-accent-4',
      'blockquote-marker': 'text-muted-foreground/60',
      hr: 'text-muted-foreground/40',
      mention: 'text-accent-2 font-medium',
      strikethrough: 'text-muted-foreground line-through',
    };
 
    function renderTokens(tokens: Token[]): ReactNode[] {
      return tokens.map((t, i) => {
        const cls = tokenStyle[t.type];
        if (!cls) return t.value;
        return (
          <span key={i} className={cls}>
            {t.value}
          </span>
        );
      });
    }
 
    return (
      <div ref={ref} className={`relative h-full min-h-[2.25rem] ${className}`}>
        {/* Highlight layer — behind the textarea */}
        <div
          ref={highlightRef}
          aria-hidden
          className={`absolute inset-0 ${sharedTypography} overflow-hidden pointer-events-none rounded-terminal border border-transparent`}
          style={{ overflowWrap: 'anywhere' }}
        >
          {value ? highlighted : (
            <span className="text-muted-foreground">{placeholder}</span>
          )}
        </div>
 
        {/* Textarea — on top, with transparent text so the highlight shows through */}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={onChange}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder=""
          aria-label={placeholder || 'Message input'}
          className={`absolute inset-0 w-full h-full resize-none ${sharedTypography} bg-transparent text-transparent caret-foreground selection:bg-primary/20 selection:text-transparent rounded-terminal border border-border focus:outline-none focus:ring-1 focus:ring-ring transition-all ${
            disabled ? 'opacity-50 cursor-not-allowed' : ''
          } ${inputClassName}`}
          style={{ overflowWrap: 'anywhere' }}
          spellCheck={false}
        />
      </div>
    );
  }
);

// Re-export ref getter for parent components that need cursor positioning
export function getEditorTextarea(
  editorEl: HTMLElement | null
): HTMLTextAreaElement | null {
  if (!editorEl) return null;
  return editorEl.querySelector('textarea');
}