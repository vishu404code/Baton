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
} from './types';
import * as mockData from '../mocks/mockData';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export const IS_MOCK_ENV = import.meta.env.VITE_MOCK === 'true';

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

  setMockMode(mock: boolean) {
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

      return res.json() as Promise<T>;
    } catch (err: any) {
      // If network failed completely and not just 4xx/5xx from server, fallback to mock mode
      if (err.name === 'TypeError' || err.message.includes('fetch') || err.message.includes('Failed to fetch')) {
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
    } catch {
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
    } catch {
      const res = {
        user: { ...mockData.MOCK_USER, display_name },
        token: `bs_mock_${display_name.toLowerCase()}`,
      };
      this.setToken(res.token);
      return res;
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
    return this.request<PresenceResponse>(`/api/rooms/${roomId}/presence`);
  }

  // --- Agents ---

  async getAgents(roomId: string): Promise<{ agents: Agent[] }> {
    return this.request<{ agents: Agent[] }>(`/api/rooms/${roomId}/agents`);
  }

  async createAgent(
    roomId: string,
    payload: { name: string; tool: string; role: string }
  ): Promise<{ agent: Agent; token: string; config: AgentConfigResponse }> {
    return this.request<{ agent: Agent; token: string; config: AgentConfigResponse }>(
      `/api/rooms/${roomId}/agents`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    );
  }

  async getAgentConfig(roomId: string, agentId: string): Promise<AgentConfigResponse> {
    return this.request<AgentConfigResponse>(`/api/rooms/${roomId}/agents/${agentId}/config`);
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
    return this.request<{
      record: BatonRecord;
      revisions: Revision[];
      comments: Comment[];
    }>(`/api/records/${recordId}`);
  }

  async createRecord(
    roomId: string,
    payload: { type: string; title: string; content: any }
  ): Promise<BatonRecord> {
    return this.request<BatonRecord>(`/api/rooms/${roomId}/records`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async createRevision(
    recordId: string,
    payload: { content: any; based_on?: any[]; sources?: any[] }
  ): Promise<{ record: BatonRecord; revision: Revision }> {
    return this.request<{ record: BatonRecord; revision: Revision }>(
      `/api/records/${recordId}/revisions`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    );
  }

  async previewRevision(recordId: string, content: any): Promise<StalePreviewResponse> {
    return this.request<StalePreviewResponse>(`/api/records/${recordId}/revisions/preview`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    });
  }

  async addComment(
    recordId: string,
    payload: { body: string; revision_id?: string }
  ): Promise<Comment> {
    return this.request<Comment>(`/api/records/${recordId}/comments`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  // --- Submissions & Approvals ---

  async getSubmissions(roomId: string, limit = 50): Promise<{ submissions: Submission[] }> {
    return this.request<{ submissions: Submission[] }>(
      `/api/rooms/${roomId}/submissions?limit=${limit}`
    );
  }

  async getApprovals(roomId: string): Promise<{ approvals: Approval[] }> {
    return this.request<{ approvals: Approval[] }>(`/api/rooms/${roomId}/approvals`);
  }

  async decideApproval(
    approvalId: string,
    decision: 'approve' | 'reject',
    comment?: string
  ): Promise<Approval> {
    return this.request<Approval>(`/api/approvals/${approvalId}/decide`, {
      method: 'POST',
      body: JSON.stringify({ decision, comment }),
    });
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
    return this.request<RecoveryResponse>(`/api/rooms/${roomId}/recovery`);
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
