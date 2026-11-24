import {
  User,
  Room,
  Member,
  Agent,
  BatonRecord,
  Revision,
  BoardResponse,
  Submission,
  Approval,
  Comment,
  Event,
  TraceResponse,
  RecoveryResponse,
  PresenceResponse,
  StalePreviewResponse,
  AgentConfigResponse,
  ProviderInfo,
  ConnectTool,
  RunStatus,
  ContextEntry,
} from './types';
import * as mockData from '../mocks/mockData';

// Desktop build: VITE_API_URL is empty, so the UI talks to the server it was loaded from (same origin).
const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
export const IS_MOCK_ENV = import.meta.env.VITE_MOCK === 'true';
// Mock data is for UI work without a backend only. Never show invented data in the real app.
const ALLOW_MOCK = IS_MOCK_ENV || import.meta.env.VITE_ALLOW_MOCK === 'true';

// --- Response adapters -------------------------------------------------------------------------
// The UI types in ./types.ts were drafted before the backend existed. These functions map Baton's
// real REST shapes (docs/API_CONTRACT.md) onto them, so every view gets exactly what it expects.

const snippetText = (key: string, s: any): string => {
  if (typeof s === 'string') return s;
  if (!s) return '';
  if (key === 'claude_code') {
    return [s.command, s.mcp_json ? `# or save as .mcp.json:\n${s.mcp_json}` : ''].filter(Boolean).join('\n\n');
  }
  if (key === 'codex') return [s.config_toml, s.env].filter(Boolean).join('\n\n');
  if (key === 'gemini_cli') return s.settings_json || '';
  if (key === 'antigravity') return s.mcp_config_json || '';
  return JSON.stringify(s, null, 2);
};

const adaptConfig = (c: any): AgentConfigResponse => ({
  ...c,
  snippets: Object.fromEntries(
    Object.entries(c?.snippets || {}).map(([k, v]) => [k, snippetText(k, v)])
  ),
});

const adaptRevision = (r: any): Revision => ({
  ...r,
  based_on: (r.based_on || []).map((b: any) => ({ ...b, revision: b.revision ?? b.number })),
  sources: (r.sources || []).map((x: any) => ({ ...x, source_id: x.source_id ?? x.record_id })),
});

const adaptComment = (c: any): Comment => ({ ...c, body: c.body ?? c.text });

const adaptSubmission = (s: any): Submission => {
  const failed = (s.checks || []).find((c: any) => c.passed === false);
  return {
    ...s,
    attempt: s.attempt ?? s.attempts ?? 1,
    failed_check: s.failed_check ?? (failed ? failed.name : null),
    reason: s.reason ?? s.rejection_reason ?? null,
  };
};

const adaptPresence = (p: any): PresenceResponse => ({
  users: (p.users || []).map((u: any) => ({ ...u, id: u.id ?? u.user_id })),
  agents: (p.agents || []).map((a: any) => ({ ...a, id: a.id ?? a.agent_id })),
});

const adaptRecovery = (r: any): RecoveryResponse => ({
  items: (r.items || []).map((it: any) => {
    const rr = it.result_revision;
    let attempt = 1;
    return {
      ...it,
      task_label: it.task_label ?? it.task?.label ?? '',
      result_revision: typeof rr === 'string' ? rr : rr ? `${rr.label} v${rr.number}` : undefined,
      timeline: (it.timeline || []).map((t: any) => {
        if (t.type === 'submission.resumed') attempt = 2;
        if (t.type === 'submission.duplicate') attempt = it.attempts ?? 3;
        const status = String(t.status ?? t.type ?? '')
          .replace(/^(submission|agent)\./, '')
          .replace('revision.created', 'revision created');
        return { at: t.at, status, attempt };
      }),
    };
  }),
});

const adaptPreview = (p: any): StalePreviewResponse => ({
  stale_count: (p.would_go_stale || []).length,
  unaffected_count: (p.unaffected || []).length,
  stale_outputs: (p.would_go_stale || []).map((s: any) => ({
    record_id: s.record_id,
    label: s.label,
    title: s.title,
    current_revision: s.revision,
    path: s.path || [],
    reason: s.reason,
  })),
});

class ApiClient {
  private token: string | null = null;
  private isMockMode: boolean = IS_MOCK_ENV;
  private onMockModeChanged?: (isMock: boolean) => void;

  constructor() {
    this.token = localStorage.getItem('baton_session_token');
  }

  setMockModeListener(listener: (isMock: boolean) => void) {
    this.onMockModeChanged = listener;
  }

  getIsMockMode(): boolean {
    return this.isMockMode;
  }

  getBaseUrl(): string {
    return BASE_URL || window.location.origin;
  }

  setMockMode(mock: boolean) {
    if (mock && !ALLOW_MOCK) mock = false;
    this.isMockMode = mock;
    this.onMockModeChanged?.(mock);
  }

  getToken(): string | null {
    return this.token;
  }

  setToken(token: string | null) {
    this.token = token;
    if (token) {
      localStorage.setItem('baton_session_token', token);
    } else {
      localStorage.removeItem('baton_session_token');
    }
  }

  async checkHealth(): Promise<boolean> {
    if (this.isMockMode && IS_MOCK_ENV) return true;
    try {
      const res = await fetch(`${BASE_URL}/health`, { signal: AbortSignal.timeout(3000) });
      if (!res.ok) {
        this.setMockMode(true);
        return false;
      }
      this.setMockMode(false);
      return true;
    } catch {
      this.setMockMode(true);
      return false;
    }
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    if (this.isMockMode) {
      return this.handleMockRequest<T>(endpoint, options);
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    try {
      const res = await fetch(`${BASE_URL}${endpoint}`, {
        ...options,
        headers,
      });

      if (!res.ok) {
        if (res.status === 401) {
          this.setToken(null);
        }
        const errorData = await res.json().catch(() => ({}));
        const message = errorData?.error?.message || `API Error: ${res.status} ${res.statusText}`;
        throw new Error(message);
      }

      if (res.status === 204) return { revoked: true } as unknown as T;
      return res.json() as Promise<T>;
    } catch (err: any) {
      // If network failed completely and not just 4xx/5xx from server, fallback to mock mode
      if (err.name === 'TypeError' || err.message.includes('fetch') || err.message.includes('Failed to fetch')) {
        if (!ALLOW_MOCK) throw new Error("Can't reach Baton. Is the app still running?");
        console.warn('Backend unreachable, falling back to mock mode:', err.message);
        this.setMockMode(true);
        return this.handleMockRequest<T>(endpoint, options);
      }
      throw err;
    }
  }

  // --- Auth endpoints ---

  async createSession(display_name: string): Promise<{ user: User; token: string }> {
    try {
      const res = await this.request<{ user: User; token: string }>('/api/session', {
        method: 'POST',
        body: JSON.stringify({ display_name }),
      });
      this.setToken(res.token);
      return res;
    } catch (e) {
      if (!ALLOW_MOCK) throw e;
      // Fallback
      const res = {
        user: { id: `usr_${Date.now()}`, display_name, created_at: new Date().toISOString() },
        token: `bs_mock_${Date.now()}`,
      };
      this.setToken(res.token);
      return res;
    }
  }

  async demoSession(display_name: string): Promise<{ user: User; token: string }> {
    try {
      const res = await this.request<{ user: User; token: string }>('/api/session/demo', {
        method: 'POST',
        body: JSON.stringify({ display_name }),
      });
      this.setToken(res.token);
      return res;
    } catch (e) {
      if (!ALLOW_MOCK) throw e;
      const res = {
        user: { ...mockData.MOCK_USER, display_name },
        token: `bs_mock_${display_name.toLowerCase()}`,
      };
      this.setToken(res.token);
      return res;
    }
  }

  /** Desktop mode: sign in as the single local owner. Resolves to null when local mode is off. */
  async localSession(): Promise<{ user: User; token: string; room_id: string } | null> {
    try {
      const res = await this.request<{ user: User; token: string; room_id: string }>('/api/session/local', {
        method: 'POST',
      });
      this.setToken(res.token);
      return res;
    } catch {
      return null;
    }
  }

  async getMe(): Promise<{ user: User }> {
    return this.request<{ user: User }>('/api/me');
  }

  // --- Rooms ---

  async getRooms(): Promise<{ rooms: Room[] }> {
    return this.request<{ rooms: Room[] }>('/api/rooms');
  }

  async getRoom(roomId: string): Promise<Room> {
    return this.request<Room>(`/api/rooms/${roomId}`);
  }

  async createRoom(name: string): Promise<Room> {
    return this.request<Room>('/api/rooms', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  async joinRoom(invite_code: string): Promise<Room> {
    return this.request<Room>('/api/rooms/join', {
      method: 'POST',
      body: JSON.stringify({ invite_code }),
    });
  }

  async updateRoomSettings(roomId: string, settings: any): Promise<Room> {
    return this.request<Room>(`/api/rooms/${roomId}/settings`, {
      method: 'PATCH',
      body: JSON.stringify(settings),
    });
  }

  // --- Members & Presence ---

  async getMembers(roomId: string): Promise<{ members: Member[] }> {
    return this.request<{ members: Member[] }>(`/api/rooms/${roomId}/members`);
  }

  async updateMemberRole(roomId: string, userId: string, role: string): Promise<Member> {
    return this.request<Member>(`/api/rooms/${roomId}/members/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    });
  }

  async getPresence(roomId: string): Promise<PresenceResponse> {
    const res = await this.request<any>(`/api/rooms/${roomId}/presence`);
    return this.isMockMode ? res : adaptPresence(res);
  }

  // --- Agents ---

  async getAgents(roomId: string): Promise<{ agents: Agent[] }> {
    return this.request<{ agents: Agent[] }>(`/api/rooms/${roomId}/agents`);
  }

  async createAgent(
    roomId: string,
    payload: { name: string; tool?: string; role: string; provider?: string; model?: string }
  ): Promise<{ agent: Agent; token: string; config: AgentConfigResponse }> {
    const res = await this.request<{ agent: Agent; token: string; config: AgentConfigResponse }>(
      `/api/rooms/${roomId}/agents`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    );
    return this.isMockMode ? res : { ...res, config: adaptConfig(res.config) };
  }

  async getAgentConfig(roomId: string, agentId: string): Promise<AgentConfigResponse> {
    const res = await this.request<any>(`/api/rooms/${roomId}/agents/${agentId}/config`);
    if (this.isMockMode) return res;
    // The config endpoint doesn't repeat the agent's tool and role; the dialog needs them.
    const { agents } = await this.getAgents(roomId);
    const agent = agents.find((a) => a.id === agentId);
    return { ...adaptConfig(res), tool: agent?.tool ?? 'claude_code', role: agent?.role ?? 'planner' };
  }

  async revokeAgent(roomId: string, agentId: string): Promise<{ revoked: boolean }> {
    return this.request<{ revoked: boolean }>(`/api/rooms/${roomId}/agents/${agentId}`, {
      method: 'DELETE',
    });
  }

  // --- Records & Board ---

  async getBoard(roomId: string): Promise<BoardResponse> {
    return this.request<BoardResponse>(`/api/rooms/${roomId}/board`);
  }

  async getRecords(
    roomId: string,
    params?: { type?: string; status?: string; parent_task_id?: string }
  ): Promise<{ records: BatonRecord[] }> {
    const query = new URLSearchParams();
    if (params?.type) query.set('type', params.type);
    if (params?.status) query.set('status', params.status);
    if (params?.parent_task_id) query.set('parent_task_id', params.parent_task_id);
    const qs = query.toString() ? `?${query.toString()}` : '';
    return this.request<{ records: BatonRecord[] }>(`/api/rooms/${roomId}/records${qs}`);
  }

  async getRecordDetail(recordId: string): Promise<{
    record: BatonRecord;
    revisions: Revision[];
    comments: Comment[];
  }> {
    const res = await this.request<any>(`/api/records/${recordId}`);
    if (this.isMockMode) return res;
    return {
      ...res,
      revisions: (res.revisions || []).map(adaptRevision),
      comments: (res.comments || []).map(adaptComment),
    };
  }

  async createRecord(
    roomId: string,
    payload: { type: string; title: string; content: any }
  ): Promise<BatonRecord> {
    const res = await this.request<any>(`/api/rooms/${roomId}/records`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    return res.record ?? res;
  }

  async createRevision(
    recordId: string,
    payload: { content: any; based_on?: any[]; sources?: any[] }
  ): Promise<{ record: BatonRecord; revision: Revision }> {
    // The UI keeps the edit note inside `content`; the API takes it as a separate field.
    const { note, ...content } = payload.content || {};
    return this.request<{ record: BatonRecord; revision: Revision }>(
      `/api/records/${recordId}/revisions`,
      {
        method: 'POST',
        body: JSON.stringify({ content, ...(note ? { note } : {}) }),
      }
    );
  }

  async previewRevision(recordId: string, content: any): Promise<StalePreviewResponse> {
    const { note: _note, ...rest } = content || {};
    const res = await this.request<any>(`/api/records/${recordId}/revisions/preview`, {
      method: 'POST',
      body: JSON.stringify({ content: rest }),
    });
    return this.isMockMode ? res : adaptPreview(res);
  }

  async addComment(
    recordId: string,
    payload: { body: string; revision_id?: string }
  ): Promise<Comment> {
    const res = await this.request<any>(`/api/records/${recordId}/comments`, {
      method: 'POST',
      body: JSON.stringify({ text: payload.body }),
    });
    return this.isMockMode ? res : adaptComment(res);
  }

  // --- Submissions & Approvals ---

  async getSubmissions(roomId: string, limit = 50): Promise<{ submissions: Submission[] }> {
    const res = await this.request<any>(`/api/rooms/${roomId}/submissions?limit=${limit}`);
    return this.isMockMode ? res : { ...res, submissions: (res.submissions || []).map(adaptSubmission) };
  }

  async getApprovals(roomId: string): Promise<{ approvals: Approval[] }> {
    return this.request<{ approvals: Approval[] }>(`/api/rooms/${roomId}/approvals`);
  }

  async decideApproval(
    approvalId: string,
    decision: 'approve' | 'reject',
    comment?: string
  ): Promise<Approval> {
    const res = await this.request<any>(`/api/approvals/${approvalId}/decide`, {
      method: 'POST',
      body: JSON.stringify({
        decision: decision === 'approve' ? 'approved' : decision === 'reject' ? 'rejected' : decision,
        ...(comment ? { comment } : {}),
      }),
    });
    return res.approval ?? res;
  }

  // --- Evidence & Events ---

  async getEvents(
    roomId: string,
    limit = 100,
    since_seq?: number
  ): Promise<{ events: Event[]; latest_seq: number }> {
    const qs = since_seq !== undefined ? `&since_seq=${since_seq}` : '';
    return this.request<{ events: Event[]; latest_seq: number }>(
      `/api/rooms/${roomId}/events?limit=${limit}${qs}`
    );
  }

  async getTrace(recordId: string): Promise<TraceResponse> {
    return this.request<TraceResponse>(`/api/records/${recordId}/trace`);
  }

  async getRecovery(roomId: string): Promise<RecoveryResponse> {
    const res = await this.request<any>(`/api/rooms/${roomId}/recovery`);
    return this.isMockMode ? res : adaptRecovery(res);
  }

  // --- Shared context across AI tools ---

  async getContext(roomId: string): Promise<{ entries: ContextEntry[]; handoff_markdown: string }> {
    return this.request(`/api/rooms/${roomId}/context`);
  }

  async getChat(roomId: string): Promise<any> {
    return this.request(`/api/rooms/${roomId}/context/chat`);
  }

  async sendChat(roomId: string, provider: string, text: string): Promise<any> {
    return this.request(`/api/rooms/${roomId}/context/chat`, { method: 'POST', body: JSON.stringify({ provider, text }) });
  }

  async clearChat(roomId: string): Promise<void> {
    await this.request(`/api/rooms/${roomId}/context/chat`, { method: 'DELETE' });
  }

  async getDemo(roomId: string): Promise<any> {
    return this.request(`/api/rooms/${roomId}/context/demo`);
  }

  async startDemo(roomId: string): Promise<{ started: boolean }> {
    return this.request(`/api/rooms/${roomId}/context/demo/start`, { method: 'POST' });
  }

  async resetDemo(roomId: string): Promise<{ ok: boolean }> {
    return this.request(`/api/rooms/${roomId}/context/demo/reset`, { method: 'POST' });
  }

  async addContextNote(roomId: string, summary: string, next_steps?: string): Promise<ContextEntry> {
    return this.request(`/api/rooms/${roomId}/context`, {
      method: 'POST',
      body: JSON.stringify({ summary, ...(next_steps ? { next_steps } : {}) }),
    });
  }

  // --- AI models & running agents ---

  async getProviders(): Promise<{ providers: ProviderInfo[]; connect: ConnectTool[] }> {
    return this.request('/api/providers');
  }

  async updateProvider(id: string, body: { api_key?: string; model?: string }): Promise<ProviderInfo> {
    return this.request(`/api/providers/${id}`, { method: 'PUT', body: JSON.stringify(body) });
  }

  async testProvider(id: string): Promise<{ ok: boolean; error?: string; models?: string[]; provider: ProviderInfo }> {
    return this.request(`/api/providers/${id}/test`, { method: 'POST' });
  }

  async runTask(roomId: string, taskRef: string, agentId?: string): Promise<{ run_id: string; agent: string; task: string }> {
    return this.request(`/api/rooms/${roomId}/tasks/${encodeURIComponent(taskRef)}/run`, {
      method: 'POST',
      body: JSON.stringify(agentId ? { agent_id: agentId } : {}),
    });
  }

  async runOpenTasks(roomId: string): Promise<{ run_id: string }> {
    return this.request(`/api/rooms/${roomId}/run-open`, { method: 'POST' });
  }

  async getRun(runId: string): Promise<RunStatus> {
    return this.request(`/api/runs/${runId}`);
  }

  // --- Mock Request Handler ---
  private handleMockRequest<T>(endpoint: string, options: RequestInit): T {
    if (endpoint === '/api/rooms') {
      return { rooms: [mockData.MOCK_ROOM] } as unknown as T;
    }
    if (endpoint.startsWith('/api/rooms/join')) {
      return mockData.MOCK_ROOM as unknown as T;
    }
    if (endpoint.includes('/board')) {
      return {
        columns: ['open', 'claimed', 'in_review', 'stale', 'approved', 'rejected'],
        tasks: mockData.MOCK_BOARD_TASKS,
      } as unknown as T;
    }
    if (endpoint.includes('/records') && !endpoint.includes('/revisions')) {
      return { records: mockData.MOCK_RECORDS } as unknown as T;
    }
    if (endpoint.includes('/revisions/preview')) {
      return {
        stale_count: 1,
        unaffected_count: 3,
        stale_outputs: [
          {
            record_id: 'rec_draft1',
            label: 'Draft 1',
            title: 'Write launch plan',
            current_revision: 1,
            path: ['Decision 2 v1', 'Draft 1 v1'],
            reason: 'based on Decision 2 v1, now v2',
          },
        ],
      } as unknown as T;
    }
    if (endpoint.includes('/submissions')) {
      return { submissions: mockData.MOCK_SUBMISSIONS } as unknown as T;
    }
    if (endpoint.includes('/recovery')) {
      return { items: mockData.MOCK_RECOVERY } as unknown as T;
    }
    if (endpoint.includes('/trace')) {
      return mockData.MOCK_TRACE as unknown as T;
    }
    if (endpoint.includes('/events')) {
      return { events: mockData.MOCK_EVENTS, latest_seq: 62 } as unknown as T;
    }
    if (endpoint.includes('/members')) {
      return { members: mockData.MOCK_MEMBERS } as unknown as T;
    }
    if (endpoint.includes('/agents')) {
      return { agents: mockData.MOCK_AGENTS } as unknown as T;
    }
    if (endpoint.includes('/presence')) {
      return {
        users: mockData.MOCK_MEMBERS.map((m) => ({
          id: m.user.id,
          display_name: m.user.display_name,
          online: m.online,
        })),
        agents: mockData.MOCK_AGENTS,
      } as unknown as T;
    }
    if (endpoint.startsWith('/api/records/')) {
      const record = mockData.MOCK_RECORDS[0];
      return {
        record,
        revisions: [
          {
            id: 'rev_1',
            record_id: record.id,
            number: 1,
            content: record.content,
            based_on: [],
            sources: [],
            author: record.updated_by,
            status: record.status,
            created_at: record.created_at,
          },
        ],
        comments: [],
      } as unknown as T;
    }
    if (endpoint.startsWith('/api/rooms/')) {
      return mockData.MOCK_ROOM as unknown as T;
    }
    return {} as unknown as T;
  }
}

export const api = new ApiClient();
