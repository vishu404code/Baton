import React, { useState } from 'react';
import {
  Plus,
  Filter,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Sparkles,
  ArrowRight,
  Play,
  Loader2,
  X,
} from 'lucide-react';
import { BoardResponse, BoardTask, Role, Status } from '../api/types';
import { api } from '../api/client';
import { AgentBadge } from '../components/common/AgentBadge';
import { StatusChip } from '../components/common/StatusChip';
import { RevisionPill } from '../components/common/RevisionPill';
import { TaskDetailPanel } from './TaskDetailPanel';
import { formatTimeAgo } from '../lib/utils';
import { useQuery, useQueryClient } from '@tanstack/react-query';

interface BoardViewProps {
  roomId: string;
  myRole: Role;
}

export const BoardView: React.FC<BoardViewProps> = ({ roomId, myRole }) => {
  const queryClient = useQueryClient();
  const [selectedTask, setSelectedTask] = useState<BoardTask | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [agentFilter, setAgentFilter] = useState<string>('all');
  const [showNewTaskModal, setShowNewTaskModal] = useState(false);

  // New task form state
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskDesc, setNewTaskDesc] = useState('');
  const [newTaskRole, setNewTaskRole] = useState<'planner' | 'reviewer'>('planner');
  const [createLoading, setCreateLoading] = useState(false);

  const { data: boardData, isLoading } = useQuery<BoardResponse>({
    queryKey: ['board', roomId],
    queryFn: () => api.getBoard(roomId),
  });

  const isMentor = myRole === 'owner' || myRole === 'mentor';

  // --- Run AI agents on tasks ---
  const [runBanner, setRunBanner] = useState<{ ok: boolean; text: string } | null>(null);
  const [running, setRunning] = useState<Record<string, boolean>>({});

  const refreshAll = () => {
    for (const k of ['board', 'events', 'submissions', 'records', 'agents', 'approvals']) {
      queryClient.invalidateQueries({ queryKey: [k, roomId] });
    }
  };

  const waitForRun = async (runId: string) => {
    for (let i = 0; i < 900; i++) {
      const r = await api.getRun(runId);
      if (r.status !== 'running') return r;
      if (i % 2 === 0) refreshAll();
      await new Promise((res) => setTimeout(res, 1000));
    }
    throw new Error('Timed out waiting for the agent.');
  };

  const handleRun = async (label: string) => {
    setRunBanner(null);
    setRunning((p) => ({ ...p, [label]: true }));
    try {
      const started = await api.runTask(roomId, label);
      const r = await waitForRun(started.run_id);
      const ok = r.status === 'done';
      setRunBanner({
        ok,
        text: ok ? `${started.agent} finished ${label}. ${r.message ?? ''}` : `${started.agent}: ${r.message ?? 'did not finish.'}`,
      });
    } catch (e: any) {
      setRunBanner({ ok: false, text: e.message || 'Could not start the agent.' });
    } finally {
      setRunning((p) => ({ ...p, [label]: false }));
      refreshAll();
    }
  };

  const handleRunAll = async () => {
    setRunBanner(null);
    setRunning((p) => ({ ...p, __all: true }));
    try {
      const started = await api.runOpenTasks(roomId);
      const r = await waitForRun(started.run_id);
      const steps = r.steps || [];
      const failed = steps.filter((s) => s.status !== 'done');
      setRunBanner({
        ok: steps.length > 0 && failed.length === 0,
        text: steps.length
          ? steps.map((s) => `${s.task}: ${s.status}${s.agent ? ` (${s.agent})` : ''}${s.status !== 'done' && s.message ? ` — ${s.message}` : ''}`).join('  ·  ')
          : 'No open tasks to run.',
      });
    } catch (e: any) {
      setRunBanner({ ok: false, text: e.message || 'Could not start the agents.' });
    } finally {
      setRunning((p) => ({ ...p, __all: false }));
      refreshAll();
    }
  };

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTaskTitle.trim() || !newTaskDesc.trim()) return;

    try {
      setCreateLoading(true);
      await api.createRecord(roomId, {
        type: 'task',
        title: newTaskTitle.trim(),
        content: {
          description: newTaskDesc.trim(),
          role: newTaskRole,
        },
      });
      setShowNewTaskModal(false);
      setNewTaskTitle('');
      setNewTaskDesc('');
      queryClient.invalidateQueries({ queryKey: ['board', roomId] });
    } catch (err: any) {
      alert(err.message || 'Failed to create task');
    } finally {
      setCreateLoading(false);
    }
  };

  const tasks: BoardTask[] = boardData?.tasks || [];

  // Filter tasks
  const filteredTasks = tasks.filter((t: BoardTask) => {
    const taskStatus = t.output?.status || t.task.status;
    if (statusFilter !== 'all' && taskStatus !== statusFilter) return false;
    if (agentFilter !== 'all') {
      const authorId = t.output?.author?.id;
      const claimAgentId = t.claim?.agent?.id;
      if (authorId !== agentFilter && claimAgentId !== agentFilter) return false;
    }
    return true;
  });

  // Extract unique agents for filtering
  const agentOptions = Array.from(
    new Set(
      tasks
        .map((t: BoardTask) => t.output?.author || t.claim?.agent)
        .filter((a): a is NonNullable<typeof a> => !!a)
        .map((a) => JSON.stringify({ id: a.id, name: a.name }))
    )
  ).map((str: string) => JSON.parse(str));

  return (
    <div className="flex-1 flex flex-col h-full bg-[#16171D] overflow-hidden select-none">
      {/* Header bar with filters and "New task" */}
      <div className="h-16 px-6 border-b border-[#2A2D37] flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-4">
          <h1 className="text-base font-bold text-[#E6E7EB]">Board</h1>
          <span className="text-xs text-[#8B8FA3] font-mono">
            {filteredTasks.length} task{filteredTasks.length === 1 ? '' : 's'}
          </span>

          <div className="h-4 w-[1px] bg-[#2A2D37]" />

          {/* Status filter */}
          <div className="flex items-center gap-1.5 text-xs">
            <Filter className="w-3.5 h-3.5 text-[#8B8FA3]" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-[#111217] border border-[#2A2D37] rounded-lg px-2.5 py-1 text-xs text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]"
            >
              <option value="all">All statuses</option>
              <option value="open">Open</option>
              <option value="claimed">In progress</option>
              <option value="in_review">Needs approval</option>
              <option value="stale">Stale</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>
          </div>

          {/* Agent filter */}
          {agentOptions.length > 0 && (
            <select
              value={agentFilter}
              onChange={(e) => setAgentFilter(e.target.value)}
              className="bg-[#111217] border border-[#2A2D37] rounded-lg px-2.5 py-1 text-xs text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]"
            >
              <option value="all">All agents</option>
              {agentOptions.map((a: any) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {isMentor && (
          <button
            onClick={handleRunAll}
            disabled={!!running.__all}
            title="Run every open or stale task with a ready AI agent"
            className="px-3.5 py-1.5 bg-[#22C55E]/15 border border-[#22C55E]/40 hover:bg-[#22C55E]/25 text-[#22C55E] rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors disabled:opacity-60 mr-2"
          >
            {running.__all ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            <span>{running.__all ? 'Agents working…' : 'Run all open tasks'}</span>
          </button>
        )}
        {isMentor && (
          <button
            onClick={() => setShowNewTaskModal(true)}
            className="px-3.5 py-1.5 bg-[#6366F1] hover:bg-[#4F46E5] text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" />
            <span>New Task</span>
          </button>
        )}
      </div>

      {/* Main Board Table */}
      <div className="flex-1 overflow-y-auto p-6">
        {runBanner && (
          <div
            className={`mb-4 px-3.5 py-2.5 rounded-xl border text-xs flex items-start justify-between gap-3 ${
              runBanner.ok
                ? 'bg-[#22C55E]/10 border-[#22C55E]/30 text-[#22C55E]'
                : 'bg-[#EF4444]/10 border-[#EF4444]/30 text-[#EF4444]'
            }`}
          >
            <span>{runBanner.text}</span>
            <button onClick={() => setRunBanner(null)} className="opacity-70 hover:opacity-100">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="h-16 bg-[#1D1F27]/60 rounded-xl animate-pulse border border-[#2A2D37]"
              />
            ))}
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="h-64 flex flex-col items-center justify-center text-center text-xs text-[#8B8FA3] border border-dashed border-[#2A2D37] rounded-2xl">
            <p className="text-sm font-semibold text-[#E6E7EB] mb-1">No tasks found</p>
            <p>
              {isMentor
                ? 'Create a new task above for your team and AI agents.'
                : 'Waiting for a mentor to create tasks.'}
            </p>
          </div>
        ) : (
          <div className="border border-[#2A2D37] rounded-xl overflow-hidden bg-[#111217]/60 shadow-sm">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[#2A2D37] bg-[#16171D] text-[11px] font-semibold uppercase tracking-wider text-[#8B8FA3]">
                  <th className="py-3 px-4">Task</th>
                  <th className="py-3 px-4">Assigned / Author</th>
                  <th className="py-3 px-4">Output / Revision</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Last Updated</th>
                  {isMentor && <th className="py-3 px-4 w-24">AI</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#2A2D37] text-xs">
                {filteredTasks.map((item: BoardTask) => {
                  const effectiveStatus: Status = item.output?.status || item.task.status;
                  const isStale = effectiveStatus === 'stale';

                  return (
                    <tr
                      key={item.task.id}
                      onClick={() => setSelectedTask(item)}
                      className={`hover:bg-[#1D1F27] cursor-pointer transition-colors ${
                        isStale ? 'bg-[#F59E0B]/5 border-l-2 border-l-[#F59E0B]' : ''
                      }`}
                    >
                      {/* Task Title & Label */}
                      <td className="py-3.5 px-4">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs font-semibold text-[#6366F1]">
                            {item.task.label}
                          </span>
                          <span className="font-medium text-[#E6E7EB]">
                            {item.task.title}
                          </span>
                        </div>
                        {item.stale_reason && (
                          <div className="text-[11px] text-[#F59E0B] font-mono mt-0.5 flex items-center gap-1">
                            <AlertTriangle className="w-3 h-3 flex-shrink-0" />
                            <span>{item.stale_reason}</span>
                          </div>
                        )}
                      </td>

                      {/* Assigned Agent or Output Author */}
                      <td className="py-3.5 px-4">
                        {item.output?.author ? (
                          <AgentBadge agent={item.output.author} size="sm" />
                        ) : item.claim?.agent ? (
                          <div className="flex items-center gap-1.5">
                            <AgentBadge agent={item.claim.agent} size="sm" />
                            <span className="text-[10px] text-[#818CF8] font-mono">
                              claimed
                            </span>
                          </div>
                        ) : (
                          <span className="text-[#8B8FA3] text-[11px] italic">
                            Unassigned
                          </span>
                        )}
                      </td>

                      {/* Revision Used */}
                      <td className="py-3.5 px-4">
                        {item.output ? (
                          <RevisionPill
                            label={item.output.label}
                            revision={item.output.revision}
                            isCurrent={!isStale}
                          />
                        ) : (
                          <span className="text-[#8B8FA3] text-[11px] font-mono">
                            v{item.task.current_revision}
                          </span>
                        )}
                      </td>

                      {/* Status Chip */}
                      <td className="py-3.5 px-4">
                        <StatusChip status={effectiveStatus} size="sm" />
                      </td>

                      {/* Last Updated */}
                      <td className="py-3.5 px-4 text-[#8B8FA3] font-mono text-[11px]">
                        {formatTimeAgo(item.task.updated_at)}
                      </td>

                      {/* Run with an AI agent */}
                      {isMentor && (
                        <td className="py-3.5 px-4" onClick={(e) => e.stopPropagation()}>
                          {(item.task.status === 'open' || item.task.status === 'stale') && (
                            <button
                              onClick={() => handleRun(item.task.label)}
                              disabled={!!running[item.task.label] || !!running.__all}
                              className="px-2.5 py-1 rounded-lg bg-[#6366F1]/15 border border-[#6366F1]/40 text-[#818CF8] hover:bg-[#6366F1]/25 text-[11px] font-semibold flex items-center gap-1 disabled:opacity-50"
                            >
                              {running[item.task.label] ? (
                                <Loader2 className="w-3 h-3 animate-spin" />
                              ) : (
                                <Play className="w-3 h-3" />
                              )}
                              {running[item.task.label] ? 'Running' : item.task.status === 'stale' ? 'Fix' : 'Run'}
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Task Detail Slide-in Panel */}
      {selectedTask && (
        <TaskDetailPanel
          taskItem={selectedTask}
          roomId={roomId}
          myRole={myRole}
          onClose={() => setSelectedTask(null)}
        />
      )}

      {/* Create Task Modal */}
      {showNewTaskModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#1D1F27] border border-[#2A2D37] rounded-xl w-full max-w-lg p-6 shadow-2xl">
            <h3 className="text-base font-semibold text-[#E6E7EB] mb-2">Create New Task</h3>
            <p className="text-xs text-[#8B8FA3] mb-4">
              Mentors create tasks for AI agents to claim, draft and review.
            </p>

            <form onSubmit={handleCreateTask} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                  Task Title
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Write launch plan"
                  value={newTaskTitle}
                  onChange={(e) => setNewTaskTitle(e.target.value)}
                  className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                  Role
                </label>
                <select
                  value={newTaskRole}
                  onChange={(e) => setNewTaskRole(e.target.value as any)}
                  className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
                >
                  <option value="planner">Planner (e.g. Claude Code)</option>
                  <option value="reviewer">Reviewer (e.g. Codex)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                  Brief / Instructions
                </label>
                <textarea
                  required
                  rows={4}
                  placeholder="Describe the objective, citations needed, and constraints..."
                  value={newTaskDesc}
                  onChange={(e) => setNewTaskDesc(e.target.value)}
                  className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
                />
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowNewTaskModal(false)}
                  className="px-3.5 py-2 text-xs text-[#8B8FA3] hover:text-[#E6E7EB] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createLoading || !newTaskTitle.trim()}
                  className="px-4 py-2 bg-[#6366F1] hover:bg-[#4F46E5] disabled:opacity-50 text-white rounded-lg text-xs font-semibold transition-colors"
                >
                  {createLoading ? 'Creating...' : 'Create Task'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
