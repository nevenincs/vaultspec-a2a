<script lang="ts" module>
  // ── Token types ────────────────────────────────────────────────────────────

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

  // ── Tokeniser ──────────────────────────────────────────────────────────────

  function tokenize(src: string): Token[] {
    const tokens: Token[] = [];
    const lines = src.split('\n');
    let inCodeBlock = false;

    for (let li = 0; li < lines.length; li++) {
      const line = lines[li];
      if (li > 0) tokens.push({ type: 'text', value: '\n' });

      // Code-fence toggle
      if (line.trimStart().startsWith('```')) {
        tokens.push({ type: 'code-block-fence', value: line });
        inCodeBlock = !inCodeBlock;
        continue;
      }
      if (inCodeBlock) {
        tokens.push({ type: 'code-block-body', value: line });
        continue;
      }

      // Horizontal rule
      if (/^(\s*[-*_]\s*){3,}$/.test(line)) {
        tokens.push({ type: 'hr', value: line });
        continue;
      }

      // Heading
      const headingMatch = line.match(/^(#{1,6}\s)/);
      if (headingMatch) {
        tokens.push({ type: 'heading-marker', value: headingMatch[1] });
        tokenizeInline(line.slice(headingMatch[1].length), tokens, 'heading-text');
        continue;
      }

      // Blockquote
      const bqMatch = line.match(/^(>\s?)/);
      if (bqMatch) {
        tokens.push({ type: 'blockquote-marker', value: bqMatch[1] });
        tokenizeInline(line.slice(bqMatch[1].length), tokens);
        continue;
      }

      // Unordered / ordered list
      const listMatch = line.match(/^(\s*(?:[-*+]|\d+\.)\s)/);
      if (listMatch) {
        tokens.push({ type: 'list-marker', value: listMatch[1] });
        tokenizeInline(line.slice(listMatch[1].length), tokens);
        continue;
      }

      // Normal line — inline parse
      tokenizeInline(line, tokens);
    }

    return tokens;
  }

  function tokenizeInline(
    src: string,
    out: Token[],
    textType: Token['type'] = 'text',
  ): void {
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

  // Token → Tailwind class map
  const TOKEN_CLASS: Record<Token['type'], string> = {
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

  /**
   * Returns the textarea element inside the editor container.
   * Used by InputBar for cursor positioning after mention insertion.
   */
  export function getEditorTextarea(
    editorEl: HTMLElement | null,
  ): HTMLTextAreaElement | null {
    if (!editorEl) return null;
    return editorEl.querySelector('textarea');
  }
</script>

<script lang="ts">
  interface Props {
    value: string;
    onchange: (value: string) => void;
    onkeydown?: (e: KeyboardEvent) => void;
    onHeightChange?: (height: number) => void;
    placeholder?: string;
    disabled?: boolean;
    class?: string;
    inputClass?: string;
  }

  let {
    value,
    onchange,
    onkeydown,
    onHeightChange,
    placeholder = '',
    disabled = false,
    class: className = '',
    inputClass = '',
  }: Props = $props();

  // Shared typography — must match exactly between textarea and highlight div
  const SHARED_TYPOGRAPHY =
    'font-mono text-[0.8125rem] leading-[1.625] px-3 py-2 whitespace-pre-wrap break-words';

  let textareaEl: HTMLTextAreaElement | undefined = $state();
  let highlightEl: HTMLDivElement | undefined = $state();

  // Sync scroll positions: textarea → highlight layer
  function syncScroll() {
    if (textareaEl && highlightEl) {
      highlightEl.scrollTop = textareaEl.scrollTop;
      highlightEl.scrollLeft = textareaEl.scrollLeft;
    }
  }

  $effect(() => {
    const ta = textareaEl;
    if (!ta) return;
    ta.addEventListener('scroll', syncScroll);
    return () => ta.removeEventListener('scroll', syncScroll);
  });

  // Report height changes to parent for auto-expansion
  $effect(() => {
    // Re-run whenever value changes
    void value;
    if (highlightEl && onHeightChange) {
      onHeightChange(highlightEl.scrollHeight);
    }
  });

  // Tokenize on every value change
  const tokens = $derived(tokenize(value));

  function handleInput(e: Event) {
    onchange((e.target as HTMLTextAreaElement).value);
  }
</script>

<div class="relative h-full min-h-[2.25rem] {className}">
  <!-- Highlight layer — behind the textarea -->
  <div
    bind:this={highlightEl}
    aria-hidden="true"
    class="absolute inset-0 {SHARED_TYPOGRAPHY} rounded-terminal pointer-events-none overflow-hidden border border-transparent"
    style="overflow-wrap: anywhere"
  >
    {#if value}
      {#each tokens as token (token)}
        {#if TOKEN_CLASS[token.type]}
          <span class={TOKEN_CLASS[token.type]}>{token.value}</span>
        {:else}
          {token.value}
        {/if}
      {/each}
    {:else}
      <span class="text-muted-foreground">{placeholder}</span>
    {/if}
  </div>

  <!-- Textarea — on top, transparent text so highlight shows through -->
  <textarea
    bind:this={textareaEl}
    {value}
    oninput={handleInput}
    {onkeydown}
    {disabled}
    placeholder=""
    spellcheck={false}
    class="absolute inset-0 h-full w-full resize-none {SHARED_TYPOGRAPHY} caret-foreground selection:bg-primary/20 rounded-terminal border-border focus:ring-ring border bg-transparent text-transparent transition-all selection:text-transparent focus:ring-1 focus:outline-none {disabled
      ? 'cursor-not-allowed opacity-50'
      : ''} {inputClass}"
    style="overflow-wrap: anywhere"
  ></textarea>
</div>
