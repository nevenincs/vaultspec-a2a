// ---------------------------------------------------------------------------
// Inspector state store — Svelte 5 Runes
// Inspector panel target + context documents
// ---------------------------------------------------------------------------

import type { InspectorTarget, ContextDocument } from '$lib/data/types';

export class InspectorStateStore {
  inspectorTarget: InspectorTarget | null = $state(null);
  inspectorWidth: number = $state(420);
  contextDocuments: ContextDocument[] = $state([]);

  get isOpen(): boolean {
    return this.inspectorTarget !== null;
  }

  openInspector(target: InspectorTarget): void {
    this.inspectorTarget = target;
  }

  closeInspector(): void {
    this.inspectorTarget = null;
  }

  openDocument(doc: ContextDocument): void {
    this.inspectorTarget = { type: 'document', document: doc };
  }

  /**
   * Toggle context list panel. If already showing context_list, close it.
   */
  toggleContextPanel(docs: ContextDocument[]): void {
    if (this.inspectorTarget?.type === 'context_list') {
      this.inspectorTarget = null;
    } else {
      this.inspectorTarget = { type: 'context_list', documents: docs };
    }
  }

  setInspectorWidth(width: number): void {
    // Clamp between 260 and 700
    this.inspectorWidth = Math.max(260, Math.min(700, width));
  }

  setContextDocuments(docs: ContextDocument[]): void {
    this.contextDocuments = docs;
  }
}

// ---------------------------------------------------------------------------
// Singleton store instance
// ---------------------------------------------------------------------------

export const inspectorState = new InspectorStateStore();
