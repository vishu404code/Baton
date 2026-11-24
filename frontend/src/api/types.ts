export type Role = 'owner' | 'mentor' | 'member';
export type AgentRole = 'planner' | 'reviewer' | 'observer';
export type ToolType = 'claude_code' | 'codex' | 'gemini_cli' | 'cursor' | 'antigravity' | 'other';
export type RecordType = 'brief' | 'decision' | 'task' | 'source' | 'draft' | 'review';
export type Status = 'approved' | 'stale' | 'rejected' | 'claimed' | 'in_review' | 'open';

export interface User {
  id: string;
  display_name: string;
  created_at: string;
}

export type ActorKind = 'agent' | 'user' | 'system';

export interface Actor {
  kind: ActorKind;
  id: string | null;
  name: string;
  tool?: ToolType;
  role?: AgentRole;
  color?: string;
  user_id?: string;
  user_name?: string;
  room_role?: Role;
}

export interface RoomSettings {
  checks: {
    citations_present: boolean;
    sources_exist: boolean;
    content_schema: boolean;
  };
  min_sources: number;
  lease_minutes: number;
  require_approval: boolean;
}

export interface RoomCounts {
  members: number;
  agents: number;
  open_tasks: number;
  stale: number;
  pending_approvals: number;
}

export interface Room {
  id: string;
  name: string;
  invite_code: string;
  owner_id: string;
  my_role: Role;
  settings: RoomSettings;
  counts: RoomCounts;
  latest_seq: number;
  created_at: string;
}

export interface Member {
  user: User;
  role: Role;
  joined_at: string;
  online: boolean;
  agent_ids: string[];
}

export interface AgentWorkingOn {
  task_id: string;
  label: string;
  title: string;
}

export interface Agent {
  id: string;
  room_id: string;
  user_id: string;
  user_name: string;
  name: string;
  tool: ToolType;
  role: AgentRole;
  color: string;
  provider?: string | null;
  model?: string | null;
  runnable?: boolean;
  online: boolean;
  last_seen_at: string;
  working_on: AgentWorkingOn | null;
  revoked: boolean;
  created_at: string;
}

export interface BasedOnRef {
  record_id: string;
  label?: string;
  revision: number;
  revision_id: string;
  is_current: boolean;
}

export interface SourceRef {
  source_id: string;
  label: string;
  url?: string;
  text?: string;
}

export interface BatonRecord {
  id: string;
  room_id: string;
  type: RecordType;
  number: number;
  label: string;
  title: string;
  status: Status;
  current_revision: number;
  current_revision_id: string;
  parent_task_id: string | null;
  content: any;
  updated_at: string;
  updated_by: Actor;
  created_at: string;
}

export type RecordItem = BatonRecord;

export interface Revision {
  id: string;
  record_id: string;
  number: number;
  content: any;
  based_on: BasedOnRef[];
  sources: SourceRef[];
  author: Actor;
  status: Status;
  stale_reason?: string | null;
  created_at: string;
}

export interface Claim {
  task_id: string;
  agent: Actor;
  claimed_at: string;
  lease_expires_at: string;
  heartbeat_count: number;
}

export interface BoardTaskOutput {
  record_id: string;
  label: string;
  type: 'draft' | 'review';
  revision: number;
  revision_id: string;
  status: Status;
  author: Actor;
}

export interface Approval {
  id: string;
  room_id?: string;
  revision_id: string;
  record_id: string;
  record_label: string;
  task_id: string;
  task_label: string;
  reason: string;
  status: 'pending' | 'approved' | 'rejected';
  requested_at: string;
  decided_by: Actor | null;
  decided_at: string | null;
  comment: string | null;
}

export interface BoardTask {
  task: BatonRecord;
  claim: Claim | null;
  output: BoardTaskOutput | null;
  stale_reason: string | null;
  pending_approval: Approval | null;
  last_submission: {
    id: string;
    status: string;
    created_at: string;
  } | null;
}

export interface BoardResponse {
  columns: string[];
  tasks: BoardTask[];
}

export type CheckName =
  | 'claim_valid'
  | 'permission'
  | 'revisions_current'
  | 'no_conflicting_edit'
  | 'citations_present'
  | 'sources_exist'
  | 'content_schema';

export interface VerificationCheck {
  name: CheckName;
  order: number;
  passed: boolean | null;
  detail: string | null;
}

export interface Submission {
  id: string;
  room_id: string;
  task_id: string;
  task_label: string;
  task_title?: string;
  agent: Actor;
  status: 'running' | 'saved' | 'completed' | 'rejected';
  attempt: number;
  idempotency_key: string;
  checks: VerificationCheck[];
  failed_check: CheckName | null;
  reason: string | null;
  result_revision_id: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface Comment {
  id: string;
  record_id: string;
  revision_id?: string;
  author: Actor;
  body: string;
  created_at: string;
}

export interface Event {
  seq: number;
  id: string;
  room_id: string;
  type: string;
  summary: string;
  actor: Actor;
  created_at: string;
  payload: any;
}

export interface TraceNode {
  id: string;
  kind: 'revision' | 'agent' | 'user';
  label: string;
  subtitle?: string;
  status?: Status;
  color?: string;
  is_current?: boolean;
  number?: number;
}

export interface TraceEdge {
  from: string;
  to: string;
  kind: 'based_on' | 'cites' | 'supersedes' | 'authored_by' | 'approved_by' | 'rejected_by' | 'claimed_by' | 'owned_by';
  label?: string;
}

export interface TraceStoryItem {
  seq: number;
  at: string;
  text: string;
}

export interface TraceResponse {
  record: {
    id: string;
    label: string;
    title: string;
    current_revision: number;
  };
  nodes: TraceNode[];
  edges: TraceEdge[];
  story: TraceStoryItem[];
}

export interface RecoveryAttemptTimeline {
  at: string;
  status: string;
  attempt: number;
}

export interface RecoveryItem {
  submission_id: string;
  idempotency_key: string;
  attempts: number;
  task_label: string;
  agent: Actor;
  status: 'completed' | 'saved' | 'rejected' | 'running';
  result_revision?: string;
  timeline: RecoveryAttemptTimeline[];
}

export interface RecoveryResponse {
  items: RecoveryItem[];
}

export interface PresenceResponse {
  users: Array<{ id: string; display_name: string; online: boolean }>;
  agents: Agent[];
}

export interface StalePreviewResponse {
  stale_count: number;
  unaffected_count: number;
  stale_outputs: Array<{
    record_id: string;
    label: string;
    title: string;
    current_revision: number;
    path: string[];
    reason: string;
  }>;
}

export interface AgentConfigResponse {
  agent_id: string;
  tool: ToolType;
  role: AgentRole;
  env: { [key: string]: string };
  snippets: { [key: string]: string };
  instructions_md: string;
}

export interface ProviderInfo {
  id: string;
  label: string;
  kind: 'api' | 'offline' | 'mcp';
  needs_key: boolean;
  help: string;
  default_model: string;
  model: string;
  has_key: boolean;
  key_hint: string | null;
  key_source: string | null;
  ready: boolean;
  models: string[];
}

export interface ConnectTool {
  id: string;
  label: string;
  kind: string;
  help: string;
}

export interface RunStatus {
  run_id: string;
  status: 'running' | 'done' | 'rejected' | 'failed';
  agent?: string;
  task?: string;
  message?: string;
  steps?: Array<{ task: string; agent?: string; status: string; message?: string }>;
  seconds?: number;
}
