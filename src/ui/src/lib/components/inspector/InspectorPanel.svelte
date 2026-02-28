<script lang="ts">
  // ---------------------------------------------------------------------------
  // InspectorPanel — 3-mode panel: context list, document view, event detail.
  //
  // Modes:
  //   context_list  — sidebar with document buttons
  //   document      — full detail view with toolbar (raw/rendered, copy, popout)
  //   tool_call / artifact / plan — JSON event detail (auto-synthesised as doc)
  //
  // Resize: drag left edge handle between 260–700 px.
  // CodeMirror 6 for syntax-highlighted code files (ADR-005).
  // @humanspeak/svelte-markdown for rendered markdown.
  // ---------------------------------------------------------------------------

  import { X, ExternalLink, Copy, Check } from '@lucide/svelte';
  import { Button } from '$lib/components/ui/button';
  import { Root as ScrollArea } from '$lib/components/ui/scroll-area';
  import SvelteMarkdown from '@humanspeak/svelte-markdown';
  import { uiAccent } from '$lib/utils/palette';
  import type { InspectorTarget, ContextDocument } from '$lib/data/types';
  import { inspectorState } from '$lib/stores/inspector-state.svelte';
  import CodeBlock from './CodeBlock.svelte';

  let {
    target,
    onclose,
    ondocumentopen,
  }: {
    target: InspectorTarget;
    onclose: () => void;
    ondocumentopen?: (doc: ContextDocument) => void;
  } = $props();

  const copySuccess = uiAccent('copySuccess');

  // ── Language detection ─────────────────────────────────────────────────────

  const EXT_MAP: Record<string, string> = {
    ts: 'typescript',
    tsx: 'tsx',
    js: 'javascript',
    jsx: 'jsx',
    py: 'python',
    rs: 'rust',
    java: 'java',
    kt: 'kotlin',
    go: 'go',
    c: 'c',
    cpp: 'cpp',
    cs: 'csharp',
    rb: 'ruby',
    sh: 'bash',
    bash: 'bash',
    zsh: 'bash',
    yaml: 'yaml',
    yml: 'yaml',
    json: 'json',
    toml: 'toml',
    md: 'markdown',
    mdx: 'markdown',
    html: 'html',
    htm: 'html',
    css: 'css',
    scss: 'scss',
    less: 'less',
    sql: 'sql',
    graphql: 'graphql',
    gql: 'graphql',
    xml: 'xml',
    svg: 'xml',
    dockerfile: 'docker',
    tf: 'hcl',
    hcl: 'hcl',
    lua: 'lua',
    php: 'php',
    swift: 'swift',
    dart: 'dart',
    r: 'r',
    proto: 'protobuf',
  };

  const CODE_EXTS = new Set([
    'ts',
    'tsx',
    'js',
    'jsx',
    'py',
    'rs',
    'java',
    'go',
    'c',
    'cpp',
    'sh',
    'json',
    'yaml',
    'toml',
    'sql',
    'html',
    'css',
    'rb',
    'kt',
    'swift',
    'dart',
    'php',
  ]);

  function getExt(title: string): string {
    return title.split('.').pop()?.toLowerCase() ?? '';
  }

  function detectLanguage(title: string, content: string): string {
    const ext = getExt(title);
    if (ext && EXT_MAP[ext]) return EXT_MAP[ext];
    const trimmed = content.trim();
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json';
    if (content.includes('def ') && content.includes(':')) return 'python';
    if (content.includes('fn ') && content.includes('->')) return 'rust';
    if (content.includes('public class') || content.includes('import java.'))
      return 'java';
    if (content.includes('import React') || content.includes('export default'))
      return 'typescript';
    return 'text';
  }

  function isMarkdown(title: string): boolean {
    const ext = getExt(title);
    return ext === 'md' || ext === 'mdx';
  }

  function isCodeFile(doc: ContextDocument): boolean {
    if (doc.type === 'file') return true;
    const ext = getExt(doc.title);
    return CODE_EXTS.has(ext);
  }

  // ── Popout ─────────────────────────────────────────────────────────────────

  function buildPopoutHtml(doc: ContextDocument, isDarkMode: boolean): string {
    const md = isMarkdown(doc.title);
    const fg = isDarkMode ? '#e2e8f0' : '#1e293b';
    const bg = isDarkMode ? '#0f172a' : '#ffffff';
    const preBg = isDarkMode ? '#1e293b' : '#f1f5f9';
    const border = isDarkMode ? '#334155' : '#e2e8f0';
    const quote = isDarkMode ? '#94a3b8' : '#64748b';
    const link = isDarkMode ? '#60a5fa' : '#2563eb';

    if (md) {
      return `<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>${doc.title}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    max-width: 48rem; margin: 2rem auto; padding: 0 1.5rem;
    color: ${fg}; background: ${bg}; line-height: 1.7; }
  pre { background: ${preBg}; padding: 1rem; border-radius: 0.375rem; overflow-x: auto; }
  code { font-size: 0.875rem; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid ${border}; padding: 0.5rem 0.75rem; text-align: left; }
  blockquote { border-left: 3px solid ${border}; margin-left: 0; padding-left: 1rem; color: ${quote}; }
  img { max-width: 100%; }
  a { color: ${link}; }
  h1,h2,h3,h4,h5,h6 { margin-top: 1.5em; }
</style>
</head><body>
<div id="content"></div>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"><\/script>
<script>document.getElementById('content').innerHTML = marked.parse(${JSON.stringify(doc.content)});<\/script>
</body></html>`;
    }

    const escaped = doc.content
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    return `<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>${doc.title}</title>
<style>
  body { font-family: ui-monospace, 'Cascadia Code', 'Fira Code', monospace;
    margin: 2rem; color: ${fg}; background: ${bg}; }
  pre { white-space: pre-wrap; word-wrap: break-word; font-size: 0.8125rem; line-height: 1.6; }
</style>
</head><body><pre>${escaped}</pre></body></html>`;
  }

  function handlePopout(doc: ContextDocument) {
    const isDark = document.documentElement.classList.contains('dark');
    const html = buildPopoutHtml(doc, isDark);
    const dataUri = 'data:text/html;charset=utf-8,' + encodeURIComponent(html);
    const a = document.createElement('a');
    a.href = dataUri;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  // ── Copy ───────────────────────────────────────────────────────────────────

  let copied = $state(false);

  async function handleCopy(content: string) {
    try {
      await navigator.clipboard.writeText(content);
      copied = true;
    } catch {
      // Fallback for environments without Clipboard API
      const ta = document.createElement('textarea');
      ta.value = content;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      copied = true;
    }
    setTimeout(() => {
      copied = false;
    }, 2000);
  }

  // ── Resize (drag left edge) ────────────────────────────────────────────────

  let resizing = $state(false);
  let resizeStartX = 0;
  let resizeStartWidth = 0;

  function onResizeMouseDown(e: MouseEvent) {
    resizing = true;
    resizeStartX = e.clientX;
    resizeStartWidth = inspectorState.inspectorWidth;
    e.preventDefault();
  }

  $effect(() => {
    if (!resizing) return;

    function onMouseMove(e: MouseEvent) {
      // Dragging left edge: leftward drag increases width
      const delta = resizeStartX - e.clientX;
      inspectorState.setInspectorWidth(resizeStartWidth + delta);
    }

    function onMouseUp() {
      resizing = false;
    }

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);

    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  });

  // ── View raw toggle (per-document) ────────────────────────────────────────

  let viewRaw = $state(false);

  // Reset viewRaw when target changes
  $effect(() => {
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    target;
    viewRaw = false;
    copied = false;
  });

  // ── Resolved document ─────────────────────────────────────────────────────

  const resolvedDoc = $derived.by((): ContextDocument | null => {
    if (target.type === 'context_list') return null;
    if (target.type === 'document') return target.document ?? null;
    // Synthesise a document from the event for tool_call / artifact / plan
    if (!target.event) return null;
    const typeLabel =
      target.type === 'tool_call'
        ? 'Tool Call'
        : target.type === 'artifact'
          ? 'Artifact'
          : 'Plan Detail';
    return {
      id: target.event.id ?? 'unknown',
      title: typeLabel,
      content: JSON.stringify(target.event, null, 2),
      type: 'note' as const,
      updated_at: target.event.timestamp ?? new Date().toISOString(),
    };
  });
</script>

<!-- ── Resize handle (drag left edge) ──────────────────────────────────────── -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
  role="separator"
  aria-orientation="vertical"
  aria-label="Resize inspector panel"
  class="hover:bg-border/60 absolute top-0 left-0 z-10 h-full w-1 cursor-col-resize opacity-0 transition-opacity hover:opacity-100"
  onmousedown={onResizeMouseDown}
></div>

<!-- ── Context list view ────────────────────────────────────────────────────── -->
{#if target.type === 'context_list'}
  <div class="border-border bg-muted/5 flex h-full flex-col border-l">
    <!-- Header -->
    <div
      class="border-border flex shrink-0 items-center justify-between border-b px-3 py-2.5"
    >
      <div class="flex items-center gap-2">
        <span class="text-[0.8125rem] font-semibold tracking-tight">Plans</span>
        <span class="text-muted-foreground text-[0.6875rem]"
          >{target.documents?.length ?? 0}</span
        >
      </div>
      <Button variant="ghost" size="icon" class="h-7 w-7" onclick={onclose}>
        <X class="h-4 w-4" />
      </Button>
    </div>

    <!-- Document list -->
    <ScrollArea class="flex-1" orientation="vertical">
      <div class="space-y-0.5 px-2 py-1">
        {#each target.documents ?? [] as doc (doc.id)}
          <button
            onclick={() => ondocumentopen?.(doc)}
            class="group rounded-terminal hover:bg-accent/50 w-full px-2.5 py-2 text-left transition-colors"
          >
            <div class="flex items-start gap-2">
              <span
                class="text-foreground/80 group-hover:text-foreground flex-1 truncate text-[0.75rem] transition-colors"
              >
                {doc.title}
              </span>
              <span class="text-muted-foreground mt-0.5 shrink-0 text-[0.625rem]">
                {new Date(doc.updated_at).toLocaleDateString([], {
                  month: 'short',
                  day: 'numeric',
                })}
              </span>
            </div>
          </button>
        {/each}
      </div>
    </ScrollArea>
  </div>

  <!-- ── Document / event detail view ─────────────────────────────────────────── -->
{:else if resolvedDoc}
  {@const doc = resolvedDoc}
  {@const isMd = isMarkdown(doc.title)}
  {@const isCode = isCodeFile(doc)}
  {@const lang = detectLanguage(doc.title, doc.content)}
  {@const charCount = doc.content.length.toLocaleString()}
  {@const lineCount = doc.content.split('\n').length}

  <div class="border-border bg-muted/5 flex h-full flex-col overflow-hidden border-l">
    <!-- Header: title + close -->
    <div
      class="border-border flex shrink-0 items-center justify-between border-b px-4 py-3"
    >
      <div class="flex min-w-0 flex-col overflow-hidden">
        <h3 class="mb-1 truncate text-[0.8125rem] leading-none font-semibold">
          {doc.title}
        </h3>
        <span class="text-muted-foreground font-mono text-[0.625rem]">
          {new Date(doc.updated_at).toLocaleString()}
        </span>
      </div>
      <Button
        variant="ghost"
        size="icon"
        class="ml-2 h-7 w-7 shrink-0"
        onclick={onclose}
      >
        <X class="h-4 w-4" />
      </Button>
    </div>

    <!-- Content area -->
    <div class="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div
        class="rounded-terminal border-border mx-4 mt-4 mb-4 flex min-h-0 flex-1 flex-col overflow-hidden border shadow-sm"
      >
        <!-- Content toolbar: filename + actions -->
        <div
          class="border-border bg-muted/40 flex shrink-0 items-center justify-between border-b px-3 py-1.5"
        >
          <span
            class="text-muted-foreground min-w-0 truncate font-mono text-[0.625rem]"
          >
            {doc.title}
          </span>
          <div class="ml-2 flex shrink-0 items-center gap-0.5">
            {#if isMd}
              <Button
                variant="ghost"
                size="icon"
                class="text-muted-foreground hover:text-foreground h-6 w-6"
                onclick={() => {
                  viewRaw = !viewRaw;
                }}
                title={viewRaw ? 'View rendered' : 'View raw'}
              >
                <span class="font-mono text-[0.5625rem] font-bold"
                  >{viewRaw ? 'MD' : '</>'}</span
                >
              </Button>
            {/if}
            <Button
              variant="ghost"
              size="icon"
              class="text-muted-foreground hover:text-foreground h-6 w-6"
              onclick={() => handleCopy(doc.content)}
              title="Copy content"
            >
              {#if copied}
                <Check class="h-3 w-3 {copySuccess.text}" />
              {:else}
                <Copy class="h-3 w-3" />
              {/if}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              class="text-muted-foreground hover:text-foreground h-6 w-6"
              onclick={() => handlePopout(doc)}
              title="Open in new tab"
            >
              <ExternalLink class="h-3 w-3" />
            </Button>
          </div>
        </div>

        <!-- Scrollable content -->
        <ScrollArea class="min-h-0 flex-1" orientation="both">
          {#if isMd && !viewRaw}
            <!-- Rendered markdown -->
            <div
              class="inspector-markdown text-foreground p-4 text-[0.8125rem] leading-relaxed break-words"
            >
              <SvelteMarkdown source={doc.content} />
            </div>
          {:else if isCode && lang !== 'text' && lang !== 'markdown'}
            <!-- Syntax-highlighted code via CodeMirror -->
            <CodeBlock content={doc.content} language={lang} />
          {:else}
            <!-- Plain text / raw -->
            <pre
              class="text-foreground/85 min-h-[12.5rem] p-4 font-mono text-[0.75rem] leading-relaxed break-words whitespace-pre-wrap">{doc.content}</pre>
          {/if}
        </ScrollArea>
      </div>
    </div>

    <!-- Footer metadata -->
    <div class="shrink-0 px-4 pt-0 pb-3">
      <div
        class="text-muted-foreground flex items-center gap-3 font-mono text-[0.625rem]"
      >
        <span>{charCount} chars</span>
        <span class="opacity-40">|</span>
        <span>{lineCount} lines</span>
        <span class="opacity-40">|</span>
        <span>{doc.type === 'file' ? 'Local' : 'External'}</span>
      </div>
    </div>
  </div>
{/if}

<style>
  /* ── Inspector markdown typography ── */
  .inspector-markdown :global(p) {
    margin-bottom: 0.5rem;
  }
  .inspector-markdown :global(p:last-child) {
    margin-bottom: 0;
  }
  .inspector-markdown :global(strong) {
    font-weight: 600;
  }
  .inspector-markdown :global(em) {
    font-style: italic;
  }
  .inspector-markdown :global(h1) {
    font-size: 1rem;
    font-weight: 600;
    margin-top: 1rem;
    margin-bottom: 0.5rem;
  }
  .inspector-markdown :global(h2) {
    font-size: 0.875rem;
    font-weight: 600;
    margin-top: 0.75rem;
    margin-bottom: 0.375rem;
  }
  .inspector-markdown :global(h3) {
    font-size: 0.8125rem;
    font-weight: 600;
    margin-top: 0.625rem;
    margin-bottom: 0.25rem;
  }
  .inspector-markdown :global(h1:first-child),
  .inspector-markdown :global(h2:first-child),
  .inspector-markdown :global(h3:first-child) {
    margin-top: 0;
  }
  .inspector-markdown :global(ul) {
    list-style-type: disc;
    padding-left: 1.25rem;
    margin: 0.375rem 0;
  }
  .inspector-markdown :global(ol) {
    list-style-type: decimal;
    padding-left: 1.25rem;
    margin: 0.375rem 0;
  }
  .inspector-markdown :global(li) {
    margin-bottom: 0.125rem;
  }
  .inspector-markdown :global(blockquote) {
    border-left: 2px solid color-mix(in oklch, var(--foreground) 20%, transparent);
    padding-left: 0.75rem;
    margin: 0.5rem 0;
    color: color-mix(in oklch, var(--foreground) 70%, transparent);
    font-style: italic;
  }
  .inspector-markdown :global(hr) {
    margin: 0.75rem 0;
    border-color: color-mix(in oklch, var(--border) 40%, transparent);
  }
  .inspector-markdown :global(code:not(pre code)) {
    padding: 0.125rem 0.375rem;
    border-radius: var(--radius-terminal, 0.25rem);
    font-size: 0.71875rem;
    font-family: var(--font-mono);
    border: 1px solid color-mix(in oklch, var(--border) 30%, transparent);
    background: color-mix(in oklch, var(--muted) 60%, transparent);
  }
  .inspector-markdown :global(pre) {
    margin: 0.5rem 0;
    border-radius: var(--radius-terminal, 0.25rem);
    border: 1px solid color-mix(in oklch, var(--border) 30%, transparent);
    overflow: hidden;
  }
  .inspector-markdown :global(pre code) {
    display: block;
    padding: 0.75rem 1rem;
    font-size: 0.71875rem;
    font-family: var(--font-mono);
    line-height: 1.6;
    background: color-mix(in oklch, var(--muted) 40%, transparent);
    border: none;
    border-radius: 0;
    overflow-x: auto;
    white-space: pre;
  }
  .inspector-markdown :global(table) {
    width: 100%;
    font-size: 0.71875rem;
    border-collapse: collapse;
    margin: 0.5rem 0;
  }
  .inspector-markdown :global(th) {
    text-align: left;
    padding: 0.25rem 0.625rem;
    font-weight: 600;
    border-bottom: 1px solid color-mix(in oklch, var(--border) 40%, transparent);
  }
  .inspector-markdown :global(td) {
    padding: 0.25rem 0.625rem;
    border-top: 1px solid color-mix(in oklch, var(--border) 30%, transparent);
  }
  .inspector-markdown :global(a) {
    color: var(--accent-0, var(--primary));
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  .inspector-markdown :global(a:hover) {
    opacity: 0.8;
  }
  .inspector-markdown :global(img) {
    max-width: 100%;
  }
</style>
