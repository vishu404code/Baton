import React, { useState } from 'react';
import {
  GitBranch,
  Edit3,
  AlertTriangle,
  FileText,
  Bookmark,
  ExternalLink,
  Save,
  Plus,
} from 'lucide-react';
import { BatonRecord, Role, StalePreviewResponse } from '../api/types';
import { api } from '../api/client';
import { RevisionPill } from '../components/common/RevisionPill';
import { formatTimeAgo } from '../lib/utils';
import { useQuery, useQueryClient } from '@tanstack/react-query';

interface DecisionsViewProps {
  roomId: string;
  myRole: Role;
  onDecisionSaved?: (alert: { message: string; count: number }) => void;
}

export const DecisionsView: React.FC<DecisionsViewProps> = ({
  roomId,
  myRole,
  onDecisionSaved,
}) => {
  const queryClient = useQueryClient();
  const [editingRecord, setEditingRecord] = useState<BatonRecord | null>(null);
  const [editStatement, setEditStatement] = useState('');
  const [editRationale, setEditRationale] = useState('');
  const [editNote, setEditNote] = useState('exams clash');
  const [previewData, setPreviewData] = useState<StalePreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);

  // New decision modal
  const [showNewModal, setShowNewModal] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newStatement, setNewStatement] = useState('');
  const [newRationale, setNewRationale] = useState('');
  const [newLoading, setNewLoading] = useState(false);

  const isMentor = myRole === 'owner' || myRole === 'mentor';

  // Fetch all records
  const { data: recordsData } = useQuery<{ records: BatonRecord[] }>({
    queryKey: ['records', roomId],
    queryFn: () => api.getRecords(roomId, { type: 'brief,decision,source' }),
  });

  const records = recordsData?.records || [];
  const briefs = records.filter((r) => r.type === 'brief');
  const decisions = records.filter((r) => r.type === 'decision');
  const sources = records.filter((r) => r.type === 'source');

  // Start edit
  const handleOpenEdit = async (record: BatonRecord) => {
    setEditingRecord(record);
    const statement = record.content?.statement || record.content?.body || '';
    const rationale = record.content?.rationale || '';
    setEditStatement(statement);
    setEditRationale(rationale);
    setEditNote('exams clash');
    setPreviewData(null);

    // Fetch initial preview
    try {
      setPreviewLoading(true);
      const prev = await api.previewRevision(record.id, {
        statement,
        rationale,
      });
      setPreviewData(prev);
    } catch (e) {
      console.warn('Preview error:', e);
    } finally {
      setPreviewLoading(false);
    }
  };

  // On form change in edit modal, re-run preview
  const handleUpdatePreview = async () => {
    if (!editingRecord) return;
    try {
      setPreviewLoading(true);
      const prev = await api.previewRevision(editingRecord.id, {
        statement: editStatement,
        rationale: editRationale,
      });
      setPreviewData(prev);
    } catch (e) {
      console.warn('Preview error:', e);
    } finally {
      setPreviewLoading(false);
    }
  };

  // Save new revision
  const handleSaveRevision = async () => {
    if (!editingRecord) return;
    try {
      setSaveLoading(true);
      const content = {
        statement: editStatement,
        rationale: editRationale,
        note: editNote,
      };

      await api.createRevision(editingRecord.id, { content });

      const staleCount = previewData?.stale_count ?? 1;
      const alert = {
        message: `${editingRecord.label} changed: ${staleCount} output(s) now stale`,
        count: staleCount,
      };
      onDecisionSaved?.(alert);

      setEditingRecord(null);
      queryClient.invalidateQueries({ queryKey: ['records', roomId] });
      queryClient.invalidateQueries({ queryKey: ['board', roomId] });
      queryClient.invalidateQueries({ queryKey: ['events', roomId] });
    } catch (err: any) {
      alert(err.message || 'Failed to save revision');
    } finally {
      setSaveLoading(false);
    }
  };

  const handleCreateDecision = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim() || !newStatement.trim()) return;
    try {
      setNewLoading(true);
      await api.createRecord(roomId, {
        type: 'decision',
        title: newTitle.trim(),
        content: {
          statement: newStatement.trim(),
          rationale: newRationale.trim(),
        },
      });
      setShowNewModal(false);
      setNewTitle('');
      setNewStatement('');
      setNewRationale('');
      queryClient.invalidateQueries({ queryKey: ['records', roomId] });
    } catch (err: any) {
      alert(err.message || 'Failed to create decision');
    } finally {
      setNewLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#16171D] overflow-hidden select-none">
      {/* Header bar */}
      <div className="h-16 px-6 border-b border-[#2A2D37] flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-base font-bold text-[#E6E7EB]">
            Decisions, Brief & Sources
          </h1>
          <p className="text-xs text-[#8B8FA3]">
            The single source of truth. AI agents read these before drafting work.
          </p>
        </div>

        {isMentor && (
          <button
            onClick={() => setShowNewModal(true)}
            className="px-3.5 py-1.5 bg-[#6366F1] hover:bg-[#4F46E5] text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors"
          >
            <Plus className="w-4 h-4" />
            <span>New Decision</span>
          </button>
        )}
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-6 space-y-8">
        {/* Section 1: Brief */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
            <FileText className="w-4 h-4 text-[#6366F1]" />
            <span>Project Brief</span>
          </div>

          {briefs.map((b) => (
            <div
              key={b.id}
              className="p-4 bg-[#111217] border border-[#2A2D37] rounded-xl text-xs space-y-2"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[#6366F1] font-semibold">
                  {b.label} · v{b.current_revision}
                </span>
                <span className="text-[11px] text-[#8B8FA3] font-mono">
                  Updated by {b.updated_by?.name} · {formatTimeAgo(b.updated_at)}
                </span>
              </div>
              <div className="text-[#E6E7EB] font-sans leading-relaxed whitespace-pre-wrap">
                {b.content?.body || 'No brief content available.'}
              </div>
            </div>
          ))}
        </div>

        {/* Section 2: Decisions */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
              <GitBranch className="w-4 h-4 text-[#22C55E]" />
              <span>Decisions ({decisions.length})</span>
            </div>
            {!isMentor && (
              <span className="text-[11px] text-[#8B8FA3] italic">
                Only mentors can edit decisions
              </span>
            )}
          </div>

          <div className="space-y-3">
            {decisions.map((dec) => (
              <div
                key={dec.id}
                className="p-4 bg-[#111217] border border-[#2A2D37] hover:border-[#3B3E4A] rounded-xl text-xs space-y-3 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <RevisionPill
                      label={dec.label}
                      revision={dec.current_revision}
                      isCurrent={true}
                    />
                    <span className="font-semibold text-sm text-[#E6E7EB]">
                      {dec.title}
                    </span>
                  </div>

                  <div className="flex items-center gap-3">
                    <span className="text-[11px] text-[#8B8FA3] font-mono">
                      Updated by {dec.updated_by?.name} · {formatTimeAgo(dec.updated_at)}
                    </span>
                    {isMentor && (
                      <button
                        onClick={() => handleOpenEdit(dec)}
                        className="px-2.5 py-1 bg-[#1D1F27] hover:bg-[#6366F1]/20 border border-[#2A2D37] hover:border-[#6366F1]/40 text-[#6366F1] text-xs font-medium rounded-lg flex items-center gap-1 transition-colors"
                      >
                        <Edit3 className="w-3 h-3" />
                        <span>Edit</span>
                      </button>
                    )}
                  </div>
                </div>

                {/* Decision statement & rationale */}
                <div className="p-3 bg-[#1D1F27] border border-[#2A2D37] rounded-lg space-y-1">
                  <div className="text-[#E6E7EB] font-medium text-xs">
                    {dec.content?.statement}
                  </div>
                  {dec.content?.rationale && (
                    <div className="text-[11px] text-[#8B8FA3] italic">
                      Rationale: {dec.content.rationale}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Section 3: Sources */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
            <Bookmark className="w-4 h-4 text-[#F59E0B]" />
            <span>Sources & Evidence ({sources.length})</span>
          </div>

          <div className="space-y-2">
            {sources.map((src) => (
              <div
                key={src.id}
                className="p-3.5 bg-[#111217] border border-[#2A2D37] rounded-xl text-xs flex items-center justify-between"
              >
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-mono text-[#6366F1] font-semibold">
                      {src.label}
                    </span>
                    <span className="font-medium text-[#E6E7EB]">{src.title}</span>
                  </div>
                  <div className="text-[11px] text-[#8B8FA3]">
                    {src.content?.summary || src.content?.text || 'No summary'}
                  </div>
                </div>

                {src.content?.url && (
                  <a
                    href={src.content.url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-1 text-[#8B8FA3] hover:text-[#6366F1] font-mono text-[11px] transition-colors"
                  >
                    <span>{src.content.url}</span>
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Edit Decision Modal with Live Stale Preview */}
      {editingRecord && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#1D1F27] border border-[#2A2D37] rounded-2xl w-full max-w-xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#2A2D37] pb-3">
              <div>
                <h3 className="text-base font-semibold text-[#E6E7EB]">
                  Edit {editingRecord.label}: {editingRecord.title}
                </h3>
                <p className="text-xs text-[#8B8FA3]">
                  Saving will create Revision v{editingRecord.current_revision + 1}
                </p>
              </div>
              <RevisionPill
                label={editingRecord.label}
                revision={editingRecord.current_revision}
              />
            </div>

            {/* Inputs */}
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                  Statement
                </label>
                <input
                  type="text"
                  value={editStatement}
                  onChange={(e) => setEditStatement(e.target.value)}
                  onBlur={handleUpdatePreview}
                  className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                  Rationale
                </label>
                <input
                  type="text"
                  value={editRationale}
                  onChange={(e) => setEditRationale(e.target.value)}
                  onBlur={handleUpdatePreview}
                  className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                  Reason for edit (Note)
                </label>
                <input
                  type="text"
                  value={editNote}
                  placeholder="e.g. exams clash"
                  onChange={(e) => setEditNote(e.target.value)}
                  className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
                />
              </div>
            </div>

            {/* STALE PREVIEW BOX */}
            <div className="p-4 rounded-xl bg-[#F59E0B]/10 border border-[#F59E0B]/30 space-y-2">
              <div className="flex items-center gap-2 text-xs font-semibold text-[#F59E0B]">
                <AlertTriangle className="w-4 h-4 flex-shrink-0 animate-pulse" />
                <span>
                  {previewLoading
                    ? 'Calculating stale impact...'
                    : previewData
                    ? `Saving this will mark ${previewData.stale_count} output(s) stale; ${previewData.unaffected_count} stay approved`
                    : 'Saving this will calculate affected downstream outputs'}
                </span>
              </div>

              {previewData?.stale_outputs && previewData.stale_outputs.length > 0 && (
                <div className="pl-6 space-y-1 text-xs">
                  {previewData.stale_outputs.map((out: any, i: number) => (
                    <div key={i} className="text-[#E6E7EB] flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#F59E0B]" />
                      <span className="font-semibold text-[#F59E0B]">{out.label}:</span>
                      <span>{out.title}</span>
                      {out.path && (
                        <span className="text-[10px] text-[#8B8FA3] font-mono">
                          (via {out.path.join(' → ')})
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <p className="text-[11px] text-[#8B8FA3] pl-6">
                Independent work stays approved and unaffected.
              </p>
            </div>

            {/* Action buttons */}
            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setEditingRecord(null)}
                className="px-4 py-2 text-xs text-[#8B8FA3] hover:text-[#E6E7EB] transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={saveLoading || !editStatement.trim()}
                onClick={handleSaveRevision}
                className="px-4 py-2 bg-[#F59E0B] hover:bg-[#D97706] disabled:opacity-50 text-black rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors"
              >
                <Save className="w-4 h-4" />
                <span>
                  {saveLoading
                    ? 'Saving...'
                    : `Save as v${editingRecord.current_revision + 1}`}
                </span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* New Decision Modal */}
      {showNewModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#1D1F27] border border-[#2A2D37] rounded-xl w-full max-w-md p-6 shadow-2xl">
            <h3 className="text-base font-semibold text-[#E6E7EB] mb-2">Create New Decision</h3>
            <p className="text-xs text-[#8B8FA3] mb-4">
              Decisions establish constraints that AI agent outputs are verified against.
            </p>

            <form onSubmit={handleCreateDecision} className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                  Title
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Target platform"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                  Statement
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Target iOS first, Android in Phase 2."
                  value={newStatement}
                  onChange={(e) => setNewStatement(e.target.value)}
                  className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                  Rationale
                </label>
                <input
                  type="text"
                  placeholder="e.g. 80% of students use iOS."
                  value={newRationale}
                  onChange={(e) => setNewRationale(e.target.value)}
                  className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-xs focus:outline-none focus:border-[#6366F1]"
                />
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowNewModal(false)}
                  className="px-3.5 py-2 text-xs text-[#8B8FA3] hover:text-[#E6E7EB]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={newLoading || !newTitle.trim()}
                  className="px-4 py-2 bg-[#6366F1] hover:bg-[#4F46E5] text-white text-xs font-semibold rounded-lg"
                >
                  {newLoading ? 'Creating...' : 'Create Decision'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
