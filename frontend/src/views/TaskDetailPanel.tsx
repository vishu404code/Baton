import React, { useState } from 'react';
import {
  X,
  CheckCircle2,
  XCircle,
  Clock,
  History,
  AlertTriangle,
  GitCompare,
  MessageSquare,
  ExternalLink,
} from 'lucide-react';
import { BoardTask, BatonRecord, Revision, Role, BasedOnRef, SourceRef } from '../api/types';
import { api } from '../api/client';
import { AgentBadge } from '../components/common/AgentBadge';
import { StatusChip } from '../components/common/StatusChip';
import { RevisionPill } from '../components/common/RevisionPill';
import { formatTimeAgo, formatTimestamp } from '../lib/utils';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

interface TaskDetailPanelProps {
  taskItem: BoardTask | null;
  roomId: string;
  myRole: Role;
  onClose: () => void;
  onOpenRevision?: (revisionId: string) => void;
}

export const TaskDetailPanel: React.FC<TaskDetailPanelProps> = ({
  taskItem,
  roomId,
  myRole,
  onClose,
  onOpenRevision,
}) => {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'details' | 'history' | 'comments'>('details');
  const [commentText, setCommentText] = useState('');
  const [selectedRevisionNum, setSelectedRevisionNum] = useState<number | null>(null);

  if (!taskItem) return null;

  const { task, output, claim, stale_reason, pending_approval } = taskItem;
  const isMentorOrOwner = myRole === 'owner' || myRole === 'mentor';

  // Fetch full details of output if output exists, or task record
  const recordIdToFetch = output?.record_id || task.id;
  const { data: recordDetail, isLoading } = useQuery<{
    record: BatonRecord;
    revisions: Revision[];
    comments: any[];
  }>({
    queryKey: ['recordDetail', recordIdToFetch],
    queryFn: () => api.getRecordDetail(recordIdToFetch),
    enabled: !!recordIdToFetch,
  });

  // Decide approval mutation
  const decideMutation = useMutation({
    mutationFn: ({
      approvalId,
      decision,
      comment,
    }: {
      approvalId: string;
      decision: 'approve' | 'reject';
      comment?: string;
    }) => api.decideApproval(approvalId, decision, comment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['board', roomId] });
      queryClient.invalidateQueries({ queryKey: ['approvals', roomId] });
      queryClient.invalidateQueries({ queryKey: ['recordDetail', recordIdToFetch] });
    },
  });

  // Add comment mutation
  const commentMutation = useMutation({
    mutationFn: ({ body, revisionId }: { body: string; revisionId?: string }) =>
      api.addComment(recordIdToFetch, { body, revision_id: revisionId }),
    onSuccess: () => {
      setCommentText('');
      queryClient.invalidateQueries({ queryKey: ['recordDetail', recordIdToFetch] });
    },
  });

  const revisions: Revision[] = recordDetail?.revisions || [];
  const latestRevision = revisions[revisions.length - 1];
  const activeRevision =
    selectedRevisionNum !== null
      ? revisions.find((r: Revision) => r.number === selectedRevisionNum) || latestRevision
      : latestRevision;

  // Comparison revision for diff (previous revision)
  const previousRevision =
    activeRevision && activeRevision.number > 1
      ? revisions.find((r: Revision) => r.number === activeRevision.number - 1)
      : null;

  return (
    <div className="fixed inset-y-0 right-0 w-[560px] bg-[#16171D] border-l border-[#2A2D37] shadow-2xl z-40 flex flex-col animate-slideLeft">
      {/* Top Header */}
      <div className="h-16 px-6 border-b border-[#2A2D37] flex items-center justify-between">
        <div className="flex items-center gap-3 truncate">
          <span className="font-mono text-sm font-semibold text-[#6366F1]">
            {task.label}
          </span>
          <span className="text-[#8B8FA3]">·</span>
          <h2 className="text-sm font-semibold text-[#E6E7EB] truncate">
            {task.title}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <StatusChip status={output?.status || task.status} />
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[#2A2D37] text-[#8B8FA3] hover:text-[#E6E7EB] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[#2A2D37] px-6 text-xs font-medium">
        <button
          onClick={() => setActiveTab('details')}
          className={`py-3 border-b-2 mr-6 transition-colors ${
            activeTab === 'details'
              ? 'border-[#6366F1] text-[#E6E7EB]'
              : 'border-transparent text-[#8B8FA3] hover:text-[#E6E7EB]'
          }`}
        >
          Draft & Context
        </button>
        <button
          onClick={() => setActiveTab('history')}
          className={`py-3 border-b-2 mr-6 transition-colors flex items-center gap-1.5 ${
            activeTab === 'history'
              ? 'border-[#6366F1] text-[#E6E7EB]'
              : 'border-transparent text-[#8B8FA3] hover:text-[#E6E7EB]'
          }`}
        >
          <History className="w-3.5 h-3.5" />
          Revisions ({revisions.length || 1})
        </button>
        <button
          onClick={() => setActiveTab('comments')}
          className={`py-3 border-b-2 transition-colors flex items-center gap-1.5 ${
            activeTab === 'comments'
              ? 'border-[#6366F1] text-[#E6E7EB]'
              : 'border-transparent text-[#8B8FA3] hover:text-[#E6E7EB]'
          }`}
        >
          <MessageSquare className="w-3.5 h-3.5" />
          Comments ({recordDetail?.comments?.length || 0})
        </button>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Amber Stale Warning banner if stale */}
        {stale_reason && (
          <div className="p-3.5 rounded-xl bg-[#F59E0B]/10 border border-[#F59E0B]/40 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-[#F59E0B] flex-shrink-0 mt-0.5" />
            <div>
              <div className="text-xs font-semibold text-[#F59E0B]">
                This output is marked STALE
              </div>
              <div className="text-xs text-[#E6E7EB] mt-0.5">{stale_reason}</div>
            </div>
          </div>
        )}

        {/* Pending Approval Action Box */}
        {pending_approval && pending_approval.status === 'pending' && (
          <div className="p-4 rounded-xl bg-[#6366F1]/10 border border-[#6366F1]/40 space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold text-[#818CF8] flex items-center gap-1.5">
                <Clock className="w-4 h-4" />
                <span>Approval Required</span>
              </div>
              <span className="text-[10px] text-[#8B8FA3] font-mono">
                Reason: {pending_approval.reason}
              </span>
            </div>
            <p className="text-xs text-[#E6E7EB]">
              {pending_approval.record_label} was submitted and is waiting for mentor review.
            </p>

            {isMentorOrOwner ? (
              <div className="flex items-center gap-3 pt-1">
                <button
                  onClick={() =>
                    decideMutation.mutate({
                      approvalId: pending_approval.id,
                      decision: 'approve',
                    })
                  }
                  disabled={decideMutation.isPending}
                  className="flex-1 py-2 bg-[#22C55E] hover:bg-[#16A34A] text-white text-xs font-semibold rounded-lg flex items-center justify-center gap-1.5 transition-colors"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Approve Draft
                </button>
                <button
                  onClick={() =>
                    decideMutation.mutate({
                      approvalId: pending_approval.id,
                      decision: 'reject',
                      comment: 'Changes requested',
                    })
                  }
                  disabled={decideMutation.isPending}
                  className="flex-1 py-2 bg-[#EF4444]/20 hover:bg-[#EF4444]/30 border border-[#EF4444]/40 text-[#EF4444] text-xs font-semibold rounded-lg flex items-center justify-center gap-1.5 transition-colors"
                >
                  <XCircle className="w-3.5 h-3.5" />
                  Reject
                </button>
              </div>
            ) : (
              <div className="text-[11px] text-[#8B8FA3] italic">
                Only mentors and the room owner can approve submissions.
              </div>
            )}
          </div>
        )}

        {activeTab === 'details' && (
          <>
            {/* Task Brief */}
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
                Task Description
              </div>
              <div className="p-3.5 bg-[#1D1F27] border border-[#2A2D37] rounded-xl text-xs text-[#E6E7EB] leading-relaxed">
                {task.content?.description || 'No description provided.'}
              </div>
            </div>

            {/* Based On & Sources */}
            {activeRevision && (
              <div className="space-y-4">
                {activeRevision.based_on && activeRevision.based_on.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-[#8B8FA3] mb-2">
                      Based on decisions & brief
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {activeRevision.based_on.map((b: BasedOnRef, i: number) => (
                        <RevisionPill
                          key={i}
                          label={b.label || `Decision ${i + 1}`}
                          revision={b.revision}
                          isCurrent={b.is_current}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {activeRevision.sources && activeRevision.sources.length > 0 && (
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wider text-[#8B8FA3] mb-2">
                      Cited Sources
                    </div>
                    <div className="space-y-1.5">
                      {activeRevision.sources.map((src: SourceRef, i: number) => (
                        <div
                          key={i}
                          className="p-2.5 bg-[#1D1F27] border border-[#2A2D37] rounded-lg text-xs flex items-center justify-between"
                        >
                          <span className="font-mono text-[#6366F1] font-medium">
                            {src.label}
                          </span>
                          {src.url && (
                            <a
                              href={src.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[11px] text-[#8B8FA3] hover:text-[#E6E7EB] flex items-center gap-1"
                            >
                              <span>{src.url}</span>
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Latest Output / Draft Content */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
                <span>{output ? `${output.label} Content` : 'Current Draft'}</span>
                {output?.author && <AgentBadge agent={output.author} size="sm" />}
              </div>

              <div className="p-4 bg-[#111217] border border-[#2A2D37] rounded-xl font-sans text-xs text-[#E6E7EB] leading-relaxed whitespace-pre-wrap">
                {activeRevision?.content?.body ||
                  activeRevision?.content?.statement ||
                  (output
                    ? 'Draft content is loading...'
                    : 'No draft has been submitted for this task yet.')}
              </div>
            </div>
          </>
        )}

        {activeTab === 'history' && (
          <div className="space-y-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
              Revision History
            </div>

            <div className="space-y-3">
              {revisions.map((rev: Revision) => (
                <div
                  key={rev.id || rev.number}
                  className={`p-3.5 rounded-xl border transition-all ${
                    (selectedRevisionNum === rev.number ||
                      (selectedRevisionNum === null && rev.number === latestRevision?.number))
                      ? 'bg-[#1D1F27] border-[#6366F1]'
                      : 'bg-[#111217] border-[#2A2D37] hover:border-[#3B3E4A]'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-[#E6E7EB]">
                        Revision v{rev.number}
                      </span>
                      <StatusChip status={rev.status} size="sm" />
                    </div>
                    <span className="text-[10px] text-[#8B8FA3] font-mono">
                      {formatTimeAgo(rev.created_at)}
                    </span>
                  </div>

                  <div className="text-xs text-[#8B8FA3] mb-2 flex items-center gap-1.5">
                    <span>Authored by:</span>
                    <AgentBadge agent={rev.author} size="sm" />
                  </div>

                  <button
                    onClick={() => setSelectedRevisionNum(rev.number)}
                    className="text-xs text-[#6366F1] hover:underline font-medium"
                  >
                    View Revision Content →
                  </button>
                </div>
              ))}
            </div>

            {/* Before / After Diff */}
            {previousRevision && activeRevision && (
              <div className="mt-6 pt-4 border-t border-[#2A2D37] space-y-3">
                <div className="text-xs font-semibold uppercase tracking-wider text-[#8B8FA3] flex items-center gap-1.5">
                  <GitCompare className="w-4 h-4 text-[#6366F1]" />
                  <span>
                    Diff: v{previousRevision.number} → v{activeRevision.number}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div className="p-3 bg-[#EF4444]/5 border border-[#EF4444]/20 rounded-lg">
                    <div className="text-[10px] font-mono text-[#EF4444] mb-1">
                      Before (v{previousRevision.number})
                    </div>
                    <div className="font-mono text-[11px] text-[#E6E7EB] whitespace-pre-wrap">
                      {previousRevision.content?.body || previousRevision.content?.statement}
                    </div>
                  </div>

                  <div className="p-3 bg-[#22C55E]/5 border border-[#22C55E]/20 rounded-lg">
                    <div className="text-[10px] font-mono text-[#22C55E] mb-1">
                      After (v{activeRevision.number})
                    </div>
                    <div className="font-mono text-[11px] text-[#E6E7EB] whitespace-pre-wrap">
                      {activeRevision.content?.body || activeRevision.content?.statement}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'comments' && (
          <div className="space-y-4">
            <div className="space-y-3">
              {recordDetail?.comments && recordDetail.comments.length > 0 ? (
                recordDetail.comments.map((c: any) => (
                  <div
                    key={c.id}
                    className="p-3 bg-[#1D1F27] border border-[#2A2D37] rounded-xl text-xs space-y-1.5"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {c.author?.kind === 'agent' ? (
                          <AgentBadge agent={c.author} size="sm" />
                        ) : (
                          <span className="font-medium text-[#E6E7EB]">{c.author?.name}</span>
                        )}
                      </div>
                      <span className="text-[10px] text-[#8B8FA3] font-mono">
                        {formatTimeAgo(c.created_at)}
                      </span>
                    </div>
                    <p className="text-[#E6E7EB] leading-relaxed">{c.body}</p>
                  </div>
                ))
              ) : (
                <div className="text-center py-6 text-xs text-[#8B8FA3] italic">
                  No comments yet. Leave a note or finding below.
                </div>
              )}
            </div>

            {/* Comment input form */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!commentText.trim()) return;
                commentMutation.mutate({ body: commentText.trim() });
              }}
              className="space-y-2 pt-2"
            >
              <textarea
                rows={3}
                placeholder="Write a comment or reviewer feedback..."
                value={commentText}
                onChange={(e) => setCommentText(e.target.value)}
                className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
              />
              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={commentMutation.isPending || !commentText.trim()}
                  className="px-3.5 py-1.5 bg-[#6366F1] hover:bg-[#4F46E5] disabled:opacity-50 text-white rounded-lg text-xs font-medium transition-colors"
                >
                  {commentMutation.isPending ? 'Posting...' : 'Post Comment'}
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  );
};
