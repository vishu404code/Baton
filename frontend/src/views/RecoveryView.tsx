import React from 'react';
import {
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  ShieldCheck,
  Cpu,
  Clock,
  ArrowRight,
  Terminal,
} from 'lucide-react';
import { RecoveryResponse, RecoveryItem } from '../api/types';
import { api } from '../api/client';
import { AgentBadge } from '../components/common/AgentBadge';
import { formatTimeAgo, formatTimestamp } from '../lib/utils';
import { useQuery } from '@tanstack/react-query';

interface RecoveryViewProps {
  roomId: string;
}

export const RecoveryView: React.FC<RecoveryViewProps> = ({ roomId }) => {
  const { data: recoveryData, isLoading } = useQuery<RecoveryResponse>({
    queryKey: ['recovery', roomId],
    queryFn: () => api.getRecovery(roomId),
    refetchInterval: 3000,
  });

  const items = recoveryData?.items || [];

  return (
    <div className="flex-1 flex flex-col h-full bg-[#16171D] overflow-hidden select-none">
      {/* Header bar */}
      <div className="h-16 px-6 border-b border-[#2A2D37] flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-base font-bold text-[#E6E7EB] flex items-center gap-2">
            <RotateCcw className="w-4 h-4 text-[#22C55E]" />
            <span>Crash Recovery & Idempotency</span>
          </h1>
          <p className="text-xs text-[#8B8FA3]">
            Proof of exact-once application: crashed agent submissions resume safely without double-writes.
          </p>
        </div>

        <div className="px-3 py-1.5 rounded-lg bg-[#22C55E]/10 border border-[#22C55E]/30 text-xs font-semibold text-[#22C55E] flex items-center gap-1.5">
          <ShieldCheck className="w-4 h-4" />
          <span>Idempotent execution guaranteed</span>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Banner about Test 5 crash demo */}
        <div className="p-4 rounded-xl bg-[#1D1F27] border border-[#2A2D37] space-y-2">
          <div className="flex items-center gap-2 text-xs font-semibold text-[#E6E7EB]">
            <Terminal className="w-4 h-4 text-[#6366F1]" />
            <span>How Crash Recovery Works (Demo Test 5)</span>
          </div>
          <p className="text-xs text-[#8B8FA3] leading-relaxed">
            When an AI tool dies mid-submission (e.g. timeout or crashed container), Baton stores the saved state.
            When the agent retries with the same <code className="text-[#6366F1] font-mono">idempotency_key</code>,
            Baton resumes and returns the exact same revision without duplicating work.
          </p>
        </div>

        {/* List of recovery items */}
        {isLoading ? (
          <div className="space-y-4">
            {[1, 2].map((i) => (
              <div
                key={i}
                className="h-36 bg-[#1D1F27]/60 border border-[#2A2D37] rounded-xl animate-pulse"
              />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="h-64 flex flex-col items-center justify-center text-center text-[#8B8FA3] border border-dashed border-[#2A2D37] rounded-2xl p-6">
            <RotateCcw className="w-8 h-8 text-[#6366F1] mb-2 opacity-50" />
            <p className="text-sm font-semibold text-[#E6E7EB]">No crash events recorded</p>
            <p className="text-xs mt-1 max-w-sm">
              Trigger a crash test from the terminal using <code className="text-[#6366F1] font-mono">crash_demo.py</code> to see live recovery in action.
            </p>
          </div>
        ) : (
          items.map((item: RecoveryItem) => (
            <div
              key={item.submission_id}
              className="p-5 rounded-2xl bg-[#111217] border border-[#2A2D37] hover:border-[#3B3E4A] transition-all space-y-4 shadow-sm"
            >
              {/* Item Header */}
              <div className="flex items-center justify-between border-b border-[#2A2D37] pb-3">
                <div className="flex items-center gap-3">
                  <AgentBadge agent={item.agent} size="md" />
                  <span className="text-[#8B8FA3]">·</span>
                  <span className="font-mono text-xs font-bold text-[#6366F1]">
                    {item.task_label}
                  </span>
                </div>

                {/* Big Green "Applied once ✓" badge */}
                <div className="px-3.5 py-1.5 bg-[#22C55E]/15 border border-[#22C55E]/40 rounded-full text-xs font-bold text-[#22C55E] flex items-center gap-1.5 shadow-sm">
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Applied once ✓</span>
                </div>
              </div>

              {/* Idempotency Details */}
              <div className="grid grid-cols-3 gap-4 text-xs bg-[#1D1F27] p-3 rounded-xl border border-[#2A2D37]">
                <div>
                  <div className="text-[10px] text-[#8B8FA3] font-mono uppercase">
                    Idempotency Key
                  </div>
                  <div className="font-mono text-xs text-[#E6E7EB] truncate mt-0.5">
                    {item.idempotency_key}
                  </div>
                </div>

                <div>
                  <div className="text-[10px] text-[#8B8FA3] font-mono uppercase">
                    Attempts Handled
                  </div>
                  <div className="font-mono text-xs text-[#6366F1] font-bold mt-0.5">
                    {item.attempts} attempts
                  </div>
                </div>

                <div>
                  <div className="text-[10px] text-[#8B8FA3] font-mono uppercase">
                    Resulting Revision
                  </div>
                  <div className="font-mono text-xs text-[#22C55E] font-bold mt-0.5">
                    {item.result_revision || 'Draft 1 v2'}
                  </div>
                </div>
              </div>

              {/* Attempts Timeline */}
              <div className="space-y-2 pt-1">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-[#8B8FA3]">
                  Attempt Sequence & Proof
                </div>

                <div className="space-y-2">
                  {item.timeline?.map((step, idx) => {
                    const isCrash = step.status.includes('crashed') || step.status.includes('interrupted');
                    const isResumed = step.status.includes('resumed');
                    const isCompleted = step.status.includes('completed');
                    const isDup = step.status.includes('duplicate');

                    return (
                      <div
                        key={idx}
                        className={`flex items-center justify-between text-xs py-2 px-3 rounded-lg border ${
                          isCrash
                            ? 'bg-[#EF4444]/10 border-[#EF4444]/30 text-[#EF4444]'
                            : isResumed
                            ? 'bg-[#6366F1]/10 border-[#6366F1]/30 text-[#818CF8]'
                            : isCompleted
                            ? 'bg-[#22C55E]/10 border-[#22C55E]/30 text-[#22C55E]'
                            : 'bg-[#1D1F27] border-[#2A2D37] text-[#8B8FA3]'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[10px] opacity-75">
                            Attempt {step.attempt}:
                          </span>
                          <span className="font-medium text-[#E6E7EB]">
                            {step.status}
                          </span>
                        </div>

                        <span className="font-mono text-[10px] opacity-75">
                          {formatTimestamp(step.at)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
