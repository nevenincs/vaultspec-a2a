// src/ui/src/lib/api/rest.ts

import type {
  CreateThreadRequest,
  CreateThreadResponse,
  PermissionResponseRequest,
  PermissionResponseResult,
  SendMessageRequest,
  TeamStatusResponse,
  ThreadListResponse,
  ThreadStateSnapshot,
} from './types';

/** Base URL for the API. Configurable for different environments. */
let baseUrl = '';

/**
 * Set the base URL for all REST API calls.
 * Call this once during app initialization.
 */
export function setBaseUrl(url: string): void {
  baseUrl = url.replace(/\/$/, ''); // strip trailing slash
}

/** Typed API error with status code and response body. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly body: unknown,
  ) {
    super(`API error ${status}: ${statusText}`);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${baseUrl}${path}`;
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    throw new ApiError(response.status, response.statusText, body);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

// ============================================================
// REST Endpoint Wrappers (per ADR-011 §2.2)
// ============================================================

/** POST /threads — Create a new orchestration thread. */
export function createThread(req: CreateThreadRequest): Promise<CreateThreadResponse> {
  return request('/threads', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

/** GET /threads — List all threads. */
export function listThreads(): Promise<ThreadListResponse> {
  return request('/threads');
}

/** GET /threads/{id}/state — Fetch thread state snapshot for reconnection. */
export function getThreadState(threadId: string): Promise<ThreadStateSnapshot> {
  return request(`/threads/${encodeURIComponent(threadId)}/state`);
}

/** POST /threads/{id}/messages — Send a user message into a thread. */
export function sendMessage(threadId: string, req: SendMessageRequest): Promise<void> {
  return request(`/threads/${encodeURIComponent(threadId)}/messages`, {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

/** GET /team/status — Fetch current team status. */
export function getTeamStatus(): Promise<TeamStatusResponse> {
  return request('/team/status');
}

/**
 * POST /permissions/{id}/respond — Submit a permission response.
 * MUST use REST, never WebSocket (per ADR-011).
 */
export function respondToPermission(
  requestId: string,
  req: PermissionResponseRequest,
): Promise<PermissionResponseResult> {
  return request(`/permissions/${encodeURIComponent(requestId)}/respond`, {
    method: 'POST',
    body: JSON.stringify(req),
  });
}
