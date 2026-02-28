// ---------------------------------------------------------------------------
// Per-thread agent state store — Svelte 5 Runes
// Uses SvelteMap from svelte/reactivity for fine-grained per-key reactivity.
// ---------------------------------------------------------------------------

import { SvelteMap } from 'svelte/reactivity';

import {
  ServerEventType,
  type AgentLifecycleState,
  type ToolKind,
  type ToolCallStatus,
  type PermissionSnapshot,
  type ServerEvent,
  type MessageChunkEvent,
  type ThoughtChunkEvent,
  type ToolCallStartEvent,
  type ToolCallUpdateEvent,
  type ArtifactUpdateEvent,
  type PlanEntry,
  type ToolCallSnapshot,
  type ArtifactSnapshot,
  type MessageSnapshot,
  type ThreadStateSnapshot,
} from '$lib/api/types';
import { assertExhaustive } from '$lib/utils/exhaustive';

// ---------------------------------------------------------------------------
// Thread state shape
// ---------------------------------------------------------------------------

export interface ThreadMessage {
  message_id: string;
  role: string;
  content: string;
  agent_id: string | null;
  timestamp: string;
  finish_reason: string | null;
}

export interface ThreadToolCall {
  tool_call_id: string;
  title: string;
  kind: ToolKind;
  status: ToolCallStatus;
  locations: { path: string; line: number | null }[];
  content: ToolCallStartEvent['content'];
}

export interface ThreadArtifact {
  artifact_id: string;
  filename: string;
  content: string;
  complete: boolean;
}

export interface StreamItem {
  kind: 'message' | 'tool' | 'artifact';
  id: string;
}

export class ThreadState {
  lifecycleState: AgentLifecycleState | null = $state(null);
  nodeName: string | null = $state(null);
  detail: string | null = $state(null);
  messages: ThreadMessage[] = $state([]);
  toolCalls = new SvelteMap<string, ThreadToolCall>();
  artifacts = new SvelteMap<string, ThreadArtifact>();
  plan: PlanEntry[] = $state([]);
  lastSequence: number = $state(-1);
  /** Chronological insertion order across messages, tool calls, and artifacts. */
  streamItems: StreamItem[] = $state([]);
}

// ---------------------------------------------------------------------------
// Agent state store (all threads)
// ---------------------------------------------------------------------------

export class AgentStateStore {
  threads = new SvelteMap<string, ThreadState>();

  /** Message accumulators keyed by message_id — not reactive */
  #messageAccumulators = new Map<string, ThreadMessage>();

  getOrCreateThread(threadId: string): ThreadState {
    let thread = this.threads.get(threadId);
    if (!thread) {
      thread = new ThreadState();
      this.threads.set(threadId, thread);
    }
    return thread;
  }

  applyEvent(event: ServerEvent): void {
    // Connection-scoped events have no thread_id
    if (
      event.type === ServerEventType.CONNECTED ||
      event.type === ServerEventType.HEARTBEAT
    ) {
      return;
    }

    const threadId = event.thread_id;
    const thread = this.getOrCreateThread(threadId);

    // Update sequence
    if (event.sequence > thread.lastSequence) {
      thread.lastSequence = event.sequence;
    }

    switch (event.type) {
      case ServerEventType.AGENT_STATUS:
        thread.lifecycleState = event.state;
        thread.nodeName = event.node_name;
        thread.detail = event.detail;
        break;

      case ServerEventType.MESSAGE_CHUNK:
        this.#applyMessageChunk(thread, event);
        break;

      case ServerEventType.THOUGHT_CHUNK:
        this.#applyThoughtChunk(thread, event);
        break;

      case ServerEventType.TOOL_CALL_START:
        this.#applyToolCallStart(thread, event);
        break;

      case ServerEventType.TOOL_CALL_UPDATE:
        this.#applyToolCallUpdate(thread, event);
        break;

      case ServerEventType.PERMISSION_REQUEST:
        // Handled by permission-queue store
        break;

      case ServerEventType.ARTIFACT_UPDATE:
        this.#applyArtifactUpdate(thread, event);
        break;

      case ServerEventType.PLAN_UPDATE:
        thread.plan = [...event.entries];
        break;

      case ServerEventType.TEAM_STATUS:
        // Handled by team-state store
        break;

      case ServerEventType.ERROR:
        // Errors can be surfaced via toast; store doesn't mutate
        break;

      default:
        assertExhaustive(event);
    }

    // Re-set the map entry to trigger SvelteMap reactivity
    this.threads.set(threadId, thread);
  }

  restoreFromSnapshot(snapshot: ThreadStateSnapshot): PermissionSnapshot[] {
    const thread = this.getOrCreateThread(snapshot.thread_id);

    // Restore messages
    thread.messages = snapshot.messages.map((m: MessageSnapshot) => ({
      message_id: m.message_id,
      role: m.role,
      content: m.content,
      agent_id: m.agent_id,
      timestamp: m.timestamp,
      finish_reason: null,
    }));

    // Restore tool calls
    thread.toolCalls.clear();
    for (const tc of snapshot.tool_calls) {
      thread.toolCalls.set(tc.tool_call_id, {
        tool_call_id: tc.tool_call_id,
        title: tc.title,
        kind: tc.kind,
        status: tc.status,
        locations: [...tc.locations],
        content: [...tc.content],
      });
    }

    // Restore artifacts
    thread.artifacts.clear();
    for (const a of snapshot.artifacts) {
      thread.artifacts.set(a.artifact_id, {
        artifact_id: a.artifact_id,
        filename: a.filename,
        content: a.content,
        complete: a.complete,
      });
    }

    // Restore plan
    thread.plan = [...snapshot.plan];

    // Restore sequence
    thread.lastSequence = snapshot.last_sequence;

    // Reconstruct stream order from snapshot (messages first, then tools, then artifacts)
    thread.streamItems = [
      ...snapshot.messages.map((m) => ({ kind: 'message' as const, id: m.message_id })),
      ...snapshot.tool_calls.map((tc) => ({
        kind: 'tool' as const,
        id: tc.tool_call_id,
      })),
      ...snapshot.artifacts.map((a) => ({
        kind: 'artifact' as const,
        id: a.artifact_id,
      })),
    ];

    // Restore agent state from first agent if available
    if (snapshot.agents.length > 0) {
      thread.lifecycleState = snapshot.agents[0].state;
      thread.nodeName = snapshot.agents[0].node_name;
      // detail is not in AgentSnapshot — reset to null
      thread.detail = null;
    }

    // Re-set the map entry to trigger SvelteMap reactivity
    this.threads.set(snapshot.thread_id, thread);

    return snapshot.pending_permissions;
  }

  // -----------------------------------------------------------------------
  // Private event application methods
  // -----------------------------------------------------------------------

  #applyMessageChunk(thread: ThreadState, event: MessageChunkEvent): void {
    let acc = this.#messageAccumulators.get(event.message_id);
    if (!acc) {
      acc = {
        message_id: event.message_id,
        role: 'assistant',
        content: '',
        agent_id: event.agent_id,
        timestamp: event.timestamp,
        finish_reason: null,
      };
      this.#messageAccumulators.set(event.message_id, acc);
      thread.messages.push(acc);
      thread.streamItems.push({ kind: 'message', id: event.message_id });
    }
    acc.content += event.content;
    if (event.finish_reason) {
      acc.finish_reason = event.finish_reason;
    }
  }

  #applyThoughtChunk(thread: ThreadState, event: ThoughtChunkEvent): void {
    let acc = this.#messageAccumulators.get(event.message_id);
    if (!acc) {
      acc = {
        message_id: event.message_id,
        role: 'thought',
        content: '',
        agent_id: event.agent_id,
        timestamp: event.timestamp,
        finish_reason: null,
      };
      this.#messageAccumulators.set(event.message_id, acc);
      thread.messages.push(acc);
      thread.streamItems.push({ kind: 'message', id: event.message_id });
    }
    acc.content += event.content;
  }

  #applyToolCallStart(thread: ThreadState, event: ToolCallStartEvent): void {
    thread.toolCalls.set(event.tool_call_id, {
      tool_call_id: event.tool_call_id,
      title: event.title,
      kind: event.kind,
      status: event.status,
      locations: [...event.locations],
      content: [...event.content],
    });
    thread.streamItems.push({ kind: 'tool', id: event.tool_call_id });
  }

  #applyToolCallUpdate(thread: ThreadState, event: ToolCallUpdateEvent): void {
    const existing = thread.toolCalls.get(event.tool_call_id);
    if (!existing) return; // Update without start, skip

    // Delta-merge: only overwrite non-null fields
    if (event.title !== null) existing.title = event.title;
    if (event.kind !== null) existing.kind = event.kind;
    if (event.status !== null) existing.status = event.status;
    if (event.locations !== null) existing.locations = [...event.locations];
    if (event.content !== null) existing.content = [...event.content];

    // Re-set to trigger SvelteMap reactivity (SvelteMap does not track in-place mutation)
    thread.toolCalls.set(event.tool_call_id, existing);
  }

  #applyArtifactUpdate(thread: ThreadState, event: ArtifactUpdateEvent): void {
    const existing = thread.artifacts.get(event.artifact_id);
    if (existing) {
      if (event.append) {
        existing.content += event.content;
      } else {
        existing.content = event.content;
      }
      existing.filename = event.filename;
      existing.complete = event.last_chunk;

      // Re-set to trigger SvelteMap reactivity (SvelteMap does not track in-place mutation)
      thread.artifacts.set(event.artifact_id, existing);
    } else {
      thread.artifacts.set(event.artifact_id, {
        artifact_id: event.artifact_id,
        filename: event.filename,
        content: event.content,
        complete: event.last_chunk,
      });
      thread.streamItems.push({ kind: 'artifact', id: event.artifact_id });
    }
  }
}

// ---------------------------------------------------------------------------
// Singleton store instance
// ---------------------------------------------------------------------------

export const agentState = new AgentStateStore();
