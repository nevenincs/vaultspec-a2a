<script lang="ts">
  // ---------------------------------------------------------------------------
  // CodeBlock — syntax-highlighted read-only code display via CodeMirror 6.
  // Used inside InspectorPanel for code/JSON/etc. files.
  // ---------------------------------------------------------------------------

  import { onMount } from 'svelte';
  import { EditorView, basicSetup } from 'codemirror';
  import { EditorState } from '@codemirror/state';
  import { javascript } from '@codemirror/lang-javascript';
  import { json } from '@codemirror/lang-json';
  import { python } from '@codemirror/lang-python';
  import { html } from '@codemirror/lang-html';
  import { css } from '@codemirror/lang-css';
  import { markdown } from '@codemirror/lang-markdown';

  let {
    content,
    language,
  }: {
    content: string;
    language: string;
  } = $props();

  let container: HTMLDivElement | undefined = $state();
  let view: EditorView | undefined;

  function getLanguageExtension(lang: string) {
    switch (lang) {
      case 'javascript':
      case 'jsx':
        return javascript({ jsx: true });
      case 'typescript':
      case 'tsx':
        return javascript({ jsx: true, typescript: true });
      case 'json':
        return json();
      case 'python':
        return python();
      case 'html':
        return html();
      case 'css':
      case 'scss':
      case 'less':
        return css();
      case 'markdown':
        return markdown();
      default:
        return [];
    }
  }

  onMount(() => {
    if (!container) return;

    const isDark = document.documentElement.classList.contains('dark');

    const state = EditorState.create({
      doc: content,
      extensions: [
        basicSetup,
        getLanguageExtension(language),
        EditorView.editable.of(false),
        EditorView.lineWrapping,
        EditorView.theme(
          {
            '&': {
              fontSize: '0.75rem',
              fontFamily: 'var(--font-mono)',
              minHeight: '12.5rem',
              backgroundColor: isDark
                ? 'color-mix(in oklch, var(--muted) 40%, transparent)'
                : 'color-mix(in oklch, var(--muted) 40%, transparent)',
            },
            '.cm-content': {
              padding: '0.75rem 1rem',
              lineHeight: '1.6',
            },
            '.cm-gutters': {
              backgroundColor: 'transparent',
              borderRight:
                '1px solid color-mix(in oklch, var(--border) 30%, transparent)',
              color: 'color-mix(in oklch, var(--muted-foreground) 60%, transparent)',
              fontSize: '0.6875rem',
              minWidth: '2.5em',
            },
            '.cm-activeLineGutter': {
              backgroundColor: 'transparent',
            },
            '.cm-activeLine': {
              backgroundColor: 'transparent',
            },
            '.cm-focused': {
              outline: 'none',
            },
          },
          { dark: isDark },
        ),
      ],
    });

    view = new EditorView({ state, parent: container });

    return () => {
      view?.destroy();
      view = undefined;
    };
  });

  // Update content reactively when prop changes
  $effect(() => {
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== content) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: content },
      });
    }
  });
</script>

<div
  bind:this={container}
  class="cm-inspector-host min-h-[12.5rem] overflow-x-auto"
></div>

<style>
  /* Ensure CodeMirror fills the container without its own scrollbars clashing */
  .cm-inspector-host :global(.cm-editor) {
    height: 100%;
    min-height: 12.5rem;
  }
  .cm-inspector-host :global(.cm-scroller) {
    font-family: var(--font-mono);
    overflow-x: auto;
  }
</style>
