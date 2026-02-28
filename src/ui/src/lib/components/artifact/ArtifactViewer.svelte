<script lang="ts">
  import { onMount } from 'svelte';
  import type { ArtifactSnapshot } from '$lib/api/types';
  import * as Card from '$lib/components/ui/card';
  import { Badge } from '$lib/components/ui/badge';
  import { EditorView } from '@codemirror/view';
  import { EditorState } from '@codemirror/state';
  import { basicSetup } from 'codemirror';
  import { javascript } from '@codemirror/lang-javascript';
  import { python } from '@codemirror/lang-python';
  import { json } from '@codemirror/lang-json';
  import { markdown } from '@codemirror/lang-markdown';
  import { html } from '@codemirror/lang-html';
  import { css } from '@codemirror/lang-css';

  let { artifact }: { artifact: ArtifactSnapshot } = $props();

  let editorEl: HTMLDivElement;
  let view: EditorView | undefined;

  function getLanguageExtension(filename: string) {
    const ext = filename.split('.').pop()?.toLowerCase() ?? '';
    switch (ext) {
      case 'js':
      case 'jsx':
      case 'mjs':
      case 'cjs':
        return javascript();
      case 'ts':
      case 'tsx':
        return javascript({ typescript: true });
      case 'py':
        return python();
      case 'json':
      case 'jsonc':
        return json();
      case 'md':
      case 'mdx':
        return markdown();
      case 'html':
      case 'htm':
      case 'svelte':
        return html();
      case 'css':
      case 'scss':
      case 'less':
        return css();
      default:
        return [];
    }
  }

  onMount(() => {
    const lang = getLanguageExtension(artifact.filename);
    const state = EditorState.create({
      doc: artifact.content,
      extensions: [
        basicSetup,
        ...(Array.isArray(lang) ? lang : [lang]),
        EditorState.readOnly.of(true),
        EditorView.theme({
          '&': { maxHeight: '400px', fontSize: '12px' },
          '.cm-scroller': { overflow: 'auto' },
        }),
      ],
    });
    view = new EditorView({ state, parent: editorEl });

    return () => view?.destroy();
  });

  // Push streaming content updates into the editor document
  $effect(() => {
    const newContent = artifact.content;
    if (view && newContent !== view.state.doc.toString()) {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: newContent },
      });
    }
  });
</script>

<Card.Root class="mb-3 overflow-hidden">
  <div class="flex items-center justify-between border-b px-3 py-2">
    <span class="font-mono text-xs font-medium">{artifact.filename}</span>
    <Badge variant={artifact.complete ? 'secondary' : 'default'}>
      {artifact.complete ? 'complete' : 'streaming...'}
    </Badge>
  </div>
  <div bind:this={editorEl}></div>
</Card.Root>
