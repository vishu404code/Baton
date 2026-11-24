import React, { useState } from 'react';
import {
  CheckCircle2,
  XCircle,
  Clock,
  MinusCircle,
  Loader2,
  ShieldAlert,
  Sparkles,
  ArrowRight,
  Filter,
} from 'lucide-react';
import { Submission, CheckName, VerificationCheck } from '../api/types';
import { api } from '../api/client';
import { AgentBadge } from '../components/common/AgentBadge';
import { StatusChip } from '../components/common/StatusChip';
import { formatTimeAgo, formatTimestamp } from '../lib/utils';
import { useQuery } from '@tanstack/react-query';

interface VerificationViewProps {
  roomId: string;
}

const CHECK_DISPLAY_NAMES: Record<CheckName, string> = {
  claim_valid: 'Holds the claim',
  permission: 'Allowed for role',
  revisions_current: 'Based on current revisions',
  no_conflicting_edit: 'No conflicting edit',
  citations_present: 'Cites sources',
  sources_exist: 'Sources exist',
  content_schema: 'Content complete',
};

const ALL_CHECK_NAMES: CheckName[] = [
  'claim_valid',
  'permission',
  'revisions_current',
  'no_conflicting_edit',
  'citations_present',
  'sources_exist',
  'content_schema',
];

export const VerificationView: React.FC<VerificationViewProps> = ({ roomId }) => {
  const [selectedAgentId, setSelectedAgentId] = useState<string>('all');

  const { data: subData, isLoading } = useQuery<{ submissions: Submission[] }>({
    queryKey: ['submissions', roomId],
    queryFn: () => api.getSubmissions(roomId, 50),
    refetchInterval: 3000,
  });

  const submissions = subData?.submissions || [];

  // Filter by agent
  const filteredSubmissions = submissions.filter((sub) => {
    if (selectedAgentId !== 'all' && sub.agent?.id !== selectedAgentId) {
      return false;
    }
    return true;
  });

  // Extract unique agents for filter chips
  const agentMap = new Map<string, any>();
  submissions.forEach((s) => {
    if (s.agent?.id) {
      agentMap.set(s.agent.id, s.agent);
    }
  });
  const agents = Array.from(agentMap.values());

  return (
    <div className="flex-1 flex flex-col h-full bg-[#16171D] overflow-hidden select-none">
      {/* Header bar */}
      <div className="h-16 px-6 border-b border-[#2A2D37] flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-base font-bold text-[#E6E7EB] flex items-center gap-2">
            <span>Live Verification Pipeline</span>
            <span className="w-2 h-2 rounded-full bg-[#22C55E] animate-pulse" />
          </h1>
          <p className="text-xs text-[#8B8FA3]">
            Every agent submission undergoes 7 deterministic checks before it is accepted.
          </p>
        </div>

        {/* Agent Filter Chips */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-[#8B8FA3] flex items-center gap-1">
            <Filter className="w-3.5 h-3.5" />
            <span>Filter:</span>
          </span>
          <button
            onClick={() => setSelectedAgentId('all')}
            className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
              selectedAgentId === 'all'
                ? 'bg-[#6366F1]/20 border-[#6366F1] text-[#E6E7EB]'
                : 'bg-[#111217] border-[#2A2D37] text-[#8B8FA3] hover:text-[#E6E7EB]'
            }`}
          >
            All Agents
          </button>
          {agents.map((agt) => (
            <button
              key={agt.id}
              onClick={() => setSelectedAgentId(agt.id)}
              className={`border rounded-full transition-all ${
                selectedAgentId === agt.id
                  ? 'ring-1 ring-[#6366F1]'
                  : 'opacity-70 hover:opacity-100'
              }`}
            >
              <AgentBadge agent={agt} size="sm" />
            </button>
          ))}
        </div>
      </div>

      {/* Main Submissions Stream */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {isLoading ? (
          <div className="space-y-4">
            {[1, 2].map((i) => (
              <div
                key={i}
                className="h-48 bg-[#1D1F27]/60 border border-[#2A2D37] rounded-2xl animate-pulse"
              />
            ))}
          </div>
        ) : filteredSubmissions.length === 0 ? (
          <div className="h-72 flex flex-col items-center justify-center text-center text-[#8B8FA3] border border-dashed border-[#2A2D37] rounded-2xl p-6">
            <ShieldAlert className="w-8 h-8 text-[#6366F1] mb-2 opacity-60" />
            <p className="text-sm font-semibold text-[#E6E7EB]">No submissions yet</p>
            <p className="text-xs mt-1 max-w-sm">
              Submissions appear here in real-time as Claude Code or Codex claims tasks and
              submits work over MCP.
            </p>
          </div>
        ) : (
          filteredSubmissions.map((sub) => {
            const isCompleted = sub.status === 'completed';
            const isRejected = sub.status === 'rejected';
            const isRunning = sub.status === 'running' || sub.status === 'saved';

            // Index map of existing checks
            const checkMap = new Map<CheckName, VerificationCheck>();
            (sub.checks || []).forEach((c: VerificationCheck) => checkMap.set(c.name, c));

            // Determine if a check failed earlier in the pipeline
            let hasFailedBefore = false;

            return (
              <div
                key={sub.id}
                className={`rounded-2xl border transition-all duration-300 shadow-md ${
                  isRejected
                    ? 'bg-[#191316] border-[#EF4444]/40'
                    : isCompleted
                    ? 'bg-[#121915] border-[#22C55E]/40'
                    : 'bg-[#1D1F27] border-[#2A2D37]'
                }`}
              >
                {/* Submission Card Header */}
                <div className="p-4 px-6 border-b border-[#2A2D37] flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <AgentBadge agent={sub.agent} size="md" showToolName />
                    <span className="text-[#8B8FA3]">·</span>
                    <span className="font-mono text-xs font-bold text-[#6366F1]">
                      {sub.task_label}
                    </span>
                    {sub.task_title && (
                      <span className="text-xs font-semibold text-[#E6E7EB]">
                        {sub.task_title}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-3">
                    <span className="text-[11px] font-mono text-[#8B8FA3]">
                      {formatTimeAgo(sub.created_at)}
                    </span>
                    <StatusChip
                      status={
                        isCompleted
                          ? 'approved'
                          : isRejected
                          ? 'rejected'
                          : 'claimed'
                      }
                      label={
                        isCompleted
                          ? 'Verified'
                          : isRejected
                          ? 'Failed'
                          : 'Checking...'
                      }
                    />
                  </div>
                </div>

                {/* Vertical Checklist of 7 Checks */}
                <div className="p-6 space-y-3.5">
                  {ALL_CHECK_NAMES.map((name, idx) => {
                    const check = checkMap.get(name);
                    const passed = check?.passed;
                    const isSkipped = check && passed === null;
                    const order = idx + 1;

                    // If a previous check failed, subsequent checks are "not run"
                    const notRun = hasFailedBefore;
                    if (passed === false) {
                      hasFailedBefore = true;
                    }

                    return (
                      <div
                        key={name}
                        className={`flex items-start justify-between text-xs py-1.5 px-3 rounded-lg transition-colors ${
                          passed === false
                            ? 'bg-[#EF4444]/15 border border-[#EF4444]/30'
                            : passed === true
                            ? 'bg-[#22C55E]/5'
                            : 'bg-transparent'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          {/* Check Icon */}
                          <div className="w-5 flex items-center justify-center">
                            {passed === true ? (
                              <CheckCircle2 className="w-4 h-4 text-[#22C55E]" />
                            ) : passed === false ? (
                              <XCircle className="w-4 h-4 text-[#EF4444]" />
                            ) : isRunning && !notRun ? (
                              <Loader2 className="w-4 h-4 text-[#6366F1] animate-spin" />
                            ) : (
                              <MinusCircle className="w-4 h-4 text-[#6B7280]" />
                            )}
                          </div>

                          {/* Check Name */}
                          <span
                            className={`font-medium ${
                              passed === false
                                ? 'text-[#EF4444] font-bold'
                                : passed === true
                                ? 'text-[#E6E7EB]'
                                : notRun
                                ? 'text-[#6B7280]'
                                : 'text-[#8B8FA3]'
                            }`}
                          >
                            <span className="font-mono text-[11px] opacity-60 mr-1.5">
                              {order}.
                            </span>
                            {CHECK_DISPLAY_NAMES[name]}
                          </span>
                        </div>

                        {/* Detail / Reason */}
                        <div className="text-right max-w-md truncate">
                          {check?.detail ? (
                            <span
                              className={`font-mono text-[11px] ${
                                passed === false
                                  ? 'text-[#EF4444] font-bold'
                                  : 'text-[#8B8FA3]'
                              }`}
                            >
                              {check.detail}
                            </span>
                          ) : notRun ? (
                            <span className="text-[10px] text-[#6B7280] italic">
                              not run
                            </span>
                          ) : isSkipped ? (
                            <span className="text-[10px] text-[#8B8FA3] italic">
                              skipped
                            </span>
                          ) : isRunning ? (
                            <span className="text-[10px] text-[#818CF8] italic">
                              evaluating...
                            </span>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Footer: Outcome Summary */}
                {isRejected && (
                  <div className="px-6 py-3 bg-[#EF4444]/15 border-t border-[#EF4444]/30 flex items-center justify-between text-xs text-[#EF4444] rounded-b-2xl">
                    <div className="flex items-center gap-2">
                      <ShieldAlert className="w-4 h-4 flex-shrink-0" />
                      <span className="font-bold">
                        Rejection reason:{' '}
                        <span className="font-mono text-[#E6E7EB]">
                          {sub.reason || `Failed check: ${sub.failed_check}`}
                        </span>
                      </span>
                    </div>
                    <span className="text-[10px] font-mono text-[#8B8FA3]">
                      Attempt {sub.attempt} · Idempotency key: {sub.idempotency_key}
                    </span>
                  </div>
                )}

                {isCompleted && (
                  <div className="px-6 py-3 bg-[#22C55E]/15 border-t border-[#22C55E]/30 flex items-center justify-between text-xs text-[#22C55E] rounded-b-2xl">
                    <div className="flex items-center gap-2 font-semibold">
                      <CheckCircle2 className="w-4 h-4" />
                      <span>
                        All 7 checks passed.{' '}
                        {sub.result_revision_id
                          ? `Applied as revision ${sub.result_revision_id}`
                          : 'Draft applied.'}
                      </span>
                    </div>
                    <span className="text-[10px] font-mono text-[#8B8FA3]">
                      Attempt {sub.attempt} · Idempotency key: {sub.idempotency_key}
                    </span>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
