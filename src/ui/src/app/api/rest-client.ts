/**
 * Typed REST client for the VaultSpec A2A FastAPI backend.
 *
 * All endpoints are prefixed with /api (see lib/api/app.py line 301).
 * Permission responses MUST go via REST (WS rejects them).
 */

import type { components } from '../data/wire-types';

type CreateThreadRequest = components['schemas']['CreateThreadRequest'];
type CreateThreadResponse = components['schemas']['CreateThreadResponse'];
type ThreadListResponse = components['schemas']['ThreadListResponse'];
type ThreadStateSnapshot = components['schemas']['ThreadStateSnapshot'];
type ThreadMetadata = components['schemas']['ThreadMetadata'];
type SendMessageRequest = components['schemas']['SendMessageRequest'];
type SendMessageResponse = components['schemas']['SendMessageResponse'];
type TeamStatusResponse = components['schemas']['TeamStatusResponse'];
type TeamPresetsResponse = components['schemas']['TeamPresetsResponse'];
type PermissionResponseRequest = components['schemas']['PermissionResponseRequest'];
type PermissionResponseResult = components['schemas']['PermissionResponseResult'];

class RestClientError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body?: unknown,
  ) {
    super(`REST ${status} ${statusText}`);
    this.name = 'RestClientError';
  }
}

export class RestClient {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl = (
      baseUrl ||
      import.meta.env.VITE_API_BASE_URL ||
      'http://localhost:8000'
    ).replace(/\/$/, '');
  }

  // --- Threads ---

  async createThread(req: CreateThreadRequest): Promise<CreateThreadResponse> {
    return this.post<CreateThreadResponse>('/api/threads', req);
  }

  async listThreads(offset = 0, limit = 50): Promise<ThreadListResponse> {
    return this.get<ThreadListResponse>(`/api/threads?offset=${offset}&limit=${limit}`);
  }

  async getThreadState(threadId: string): Promise<ThreadStateSnapshot> {
    return this.get<ThreadStateSnapshot>(
      `/api/threads/${encodeURIComponent(threadId)}/state`,
    );
  }

  async getThreadMetadata(threadId: string): Promise<ThreadMetadata> {
    return this.get<ThreadMetadata>(
      `/api/threads/${encodeURIComponent(threadId)}/metadata`,
    );
  }

  // --- Messages ---

  async sendMessage(
    threadId: string,
    req: SendMessageRequest,
  ): Promise<SendMessageResponse> {
    return this.post<SendMessageResponse>(
      `/api/threads/${encodeURIComponent(threadId)}/messages`,
      req,
    );
  }

  // --- Team ---

  async getTeamStatus(): Promise<TeamStatusResponse> {
    return this.get<TeamStatusResponse>('/api/team/status');
  }

  async listTeamPresets(): Promise<TeamPresetsResponse> {
    return this.get<TeamPresetsResponse>('/api/teams');
  }

  // --- Permissions ---

  async respondToPermission(
    requestId: string,
    req: PermissionResponseRequest,
  ): Promise<PermissionResponseResult> {
    return this.post<PermissionResponseResult>(
      `/api/permissions/${encodeURIComponent(requestId)}/respond`,
      req,
    );
  }

  // --- Internal ---

  private async get<T>(path: string): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`);
    if (!res.ok) {
      const body = await res.text().catch(() => undefined);
      throw new RestClientError(res.status, res.statusText, body);
    }
    return res.json() as Promise<T>;
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const errBody = await res.text().catch(() => undefined);
      throw new RestClientError(res.status, res.statusText, errBody);
    }
    return res.json() as Promise<T>;
  }
}

// Singleton
export const restClient = new RestClient();
