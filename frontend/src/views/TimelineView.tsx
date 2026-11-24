import React, { useState } from 'react';
import {
  History,
  Filter,
  Search,
  Radio,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { Event, Agent, BatonRecord } from '../api/types';
import { api } from '../api/client';
import { AgentBadge } from '../components/common/AgentBadge';
import { formatTimeAgo, formatTimestamp } from '../lib/utils';
import { useQuery } from '@tanstack/react-query';

interface TimelineViewProps {
  roomId: string;
}

export const TimelineView: React.FC<TimelineViewProps> = ({ roomId }) => {
  const [selectedAgentId, setSelectedAgentId] = useState<string>('all');
  const [selectedType, setSelectedType] = useState<string>('all');
  const [expandedSeq, setExpandedSeq] = useState<number | null>(null);

  const { data: eventsData, isLoading } = useQuery<{ events: Event[]; latest_seq: number }>({
    queryKey: ['events', roomId],
    queryFn: () => api.getEvents(roomId, 100),
    refetchInterval: 3000,
  });

  const { data: agentsData } = useQuery<{ agents: Agent[] }>({
    queryKey: ['agents', roomId],
    queryFn: () => api.getAgents(roomId),
  });

  const events = eventsData?.events || [];
  const agents = agentsData?.agents || [];

  // Filter events
  const filteredEvents = events.filter((ev) => {
    if (selectedAgentId !== 'all') {
      if (ev.actor?.id !== selectedAgentId) return false;
    }
    if (selectedType !== 'all') {
      if (!ev.type.startsWith(selectedType)) return false;
    }
    return true;
  });

  return (
    <div className="flex-1 flex flex-col h-full bg-[#16171D] overflow-hidden select-none">
      {/* Header bar with filters */}
      <div className="h-16 px-6 border-b border-[#2A2D37] flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-base font-bold text-[#E6E7EB] flex items-center gap-2">
            <History className="w-4 h-4 text-[#6366F1]" />
            <span>Room Timeline & Audit Trail</span>
          </h1>
          <p className="text-xs text-[#8B8FA3]">
            Immutable record of all human decisions, agent submits, verification checks, and approvals.
          </p>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs">
            <Filter className="w-3.5 h-3.5 text-[#8B8FA3]" />
            <select
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              className="bg-[#111217] border border-[#2A2D37] rounded-lg px-2.5 py-1 text-xs text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]"
            >
              <option value="all">All event types</option>
              <option value="decision">Decisions</option>
              <option value="task">Tasks</option>
              <option value="verification">Verification</option>
              <option value="submission">Submissions</option>
              <option value="record.stale">Stale warnings</option>
              <option value="approval">Approvals</option>
            </select>
          </div>

          <select
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            className="bg-[#111217] border border-[#2A2D37] rounded-lg px-2.5 py-1 text-xs text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]"
          >
            <option value="all">All actors</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Events List */}
      <div className="flex-1 overflow-y-auto p-6 space-y-3">
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="h-16 bg-[#1D1F27]/60 border border-[#2A2D37] rounded-xl animate-pulse"
              />
            ))}
          </div>
        ) : filteredEvents.length === 0 ? (
          <div className="h-64 flex flex-col items-center justify-center text-center text-xs text-[#8B8FA3] border border-dashed border-[#2A2D37] rounded-2xl">
            No events match the selected filters.
          </div>
        ) : (
          filteredEvents.map((ev) => {
            const isStale = ev.type.includes('stale') || ev.type.includes('decision.changed');
            const isFailed = ev.type.includes('failed') || ev.type.includes('rejected');
            const isApproved = ev.type.includes('completed') || ev.type.includes('approved');
            const isExpanded = expandedSeq === ev.seq;

            return (
              <div
                key={`${ev.seq}-${ev.id}`}
                className={`p-4 rounded-xl border transition-all ${
                  isStale
                    ? 'bg-[#F59E0B]/5 border-[#F59E0B]/30'
                    : isFailed
                    ? 'bg-[#EF4444]/5 border-[#EF4444]/30'
                    : isApproved
                    ? 'bg-[#22C55E]/5 border-[#22C55E]/30'
                    : 'bg-[#111217] border-[#2A2D37]'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {/* Actor badge */}
                    {ev.actor?.kind === 'agent' ? (
                      <AgentBadge agent={ev.actor} size="sm" />
                    ) : ev.actor?.kind === 'user' ? (
                      <span className="font-semibold text-xs text-[#E6E7EB]">
                        {ev.actor.name}
                      </span>
                    ) : (
                      <span className="font-mono text-xs text-[#8B8FA3]">Baton</span>
                    )}

                    <span className="text-[#8B8FA3]">·</span>

                    <span className="font-mono text-xs text-[#8B8FA3]">{ev.type}</span>
                  </div>

                  <div className="flex items-center gap-3">
                    <span className="text-[11px] font-mono text-[#8B8FA3]">
                      {formatTimeAgo(ev.created_at)}
                    </span>
                    <span className="px-1.5 py-0.5 rounded bg-[#1D1F27] border border-[#2A2D37] text-[10px] font-mono text-[#8B8FA3]">
                      #{ev.seq}
                    </span>
                    <button
                      onClick={() => setExpandedSeq(isExpanded ? null : ev.seq)}
                      className="p-1 text-[#8B8FA3] hover:text-[#E6E7EB]"
                    >
                      {isExpanded ? (
                        <ChevronUp className="w-3.5 h-3.5" />
                      ) : (
                        <ChevronDown className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>
                </div>

                <div className="mt-2 text-xs text-[#E6E7EB] font-medium">
                  {ev.summary}
                </div>

                {/* Collapsible raw payload */}
                {isExpanded && ev.payload && (
                  <div className="mt-3 pt-3 border-t border-[#2A2D37]">
                    <div className="text-[10px] uppercase font-mono text-[#8B8FA3] mb-1">
                      Event Payload
                    </div>
                    <pre className="p-3 bg-[#0B0C0F] border border-[#2A2D37] rounded-lg text-[11px] font-mono text-[#E6E7EB] overflow-x-auto">
                      {JSON.stringify(ev.payload, null, 2)}
                    </pre>
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
