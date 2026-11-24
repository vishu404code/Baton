import React, { useState } from 'react';
import {
  ChevronRight,
  ChevronLeft,
  Activity,
  Users,
  Circle,
  Radio,
  Clock,
} from 'lucide-react';
import { Member, Agent, Event } from '../../api/types';
import { AgentBadge } from '../common/AgentBadge';
import { formatTimeAgo, formatTimestamp } from '../../lib/utils';

interface RightPanelProps {
  members: Member[];
  agents: Agent[];
  events: Event[];
  wsStatus: 'connected' | 'connecting' | 'disconnected';
}

export const RightPanel: React.FC<RightPanelProps> = ({
  members,
  agents,
  events,
  wsStatus,
}) => {
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        title="Open Activity & Online Panel"
        className="fixed right-0 top-14 bottom-0 w-8 bg-[#111217] border-l border-[#2A2D37] flex flex-col items-center justify-center text-[#8B8FA3] hover:text-[#E6E7EB] hover:bg-[#16171D] z-20 transition-colors"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
    );
  }

  return (
    <aside className="w-[300px] bg-[#111217] border-l border-[#2A2D37] flex flex-col justify-between select-none flex-shrink-0 z-20">
      {/* Panel header with collapse toggle */}
      <div className="h-14 px-4 border-b border-[#2A2D37] flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
          <Activity className="w-4 h-4 text-[#6366F1]" />
          <span>Live Activity</span>
        </div>

        <div className="flex items-center gap-2">
          {/* WebSocket status indicator */}
          <span
            className={`w-2 h-2 rounded-full ${
              wsStatus === 'connected'
                ? 'bg-[#22C55E]'
                : wsStatus === 'connecting'
                ? 'bg-[#F59E0B] animate-pulse'
                : 'bg-[#EF4444]'
            }`}
            title={`WebSocket: ${wsStatus}`}
          />
          <button
            onClick={() => setCollapsed(true)}
            title="Collapse panel"
            className="p-1 rounded hover:bg-[#1D1F27] text-[#8B8FA3] hover:text-[#E6E7EB]"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Top half: ONLINE NOW */}
      <div className="p-3 border-b border-[#2A2D37] max-h-[40%] overflow-y-auto">
        <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-[#8B8FA3] mb-2 px-1">
          <span className="flex items-center gap-1.5">
            <Users className="w-3.5 h-3.5 text-[#6366F1]" />
            <span>Online now</span>
          </span>
          <span className="text-[10px] font-mono text-[#8B8FA3]">
            {members.filter((m) => m.online).length} / {members.length}
          </span>
        </div>

        <div className="space-y-3">
          {members.map((member) => {
            const memberAgents = agents.filter(
              (a) => a.user_id === member.user.id || member.agent_ids?.includes(a.id)
            );

            return (
              <div key={member.user.id} className="space-y-1">
                {/* Member row */}
                <div className="flex items-center justify-between px-1.5 py-1 rounded hover:bg-[#16171D]">
                  <div className="flex items-center gap-2 truncate">
                    <span
                      className={`w-2 h-2 rounded-full flex-shrink-0 ${
                        member.online ? 'bg-[#22C55E]' : 'bg-[#6B7280]'
                      }`}
                    />
                    <span className="text-xs font-medium text-[#E6E7EB] truncate">
                      {member.user.display_name}
                    </span>
                    <span className="text-[10px] text-[#8B8FA3] font-mono">
                      ({member.role})
                    </span>
                  </div>
                </div>

                {/* Member's agents */}
                {memberAgents.length > 0 && (
                  <div className="pl-4 space-y-1 border-l border-[#2A2D37] ml-2">
                    {memberAgents.map((agent) => (
                      <div
                        key={agent.id}
                        className="flex flex-col gap-0.5 text-[11px] py-1 px-1.5 rounded hover:bg-[#16171D]"
                      >
                        <div className="flex items-center justify-between">
                          <AgentBadge agent={agent} size="sm" />
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              agent.online ? 'bg-[#22C55E]' : 'bg-[#6B7280]'
                            }`}
                          />
                        </div>
                        {agent.working_on ? (
                          <div className="text-[10px] text-[#818CF8] truncate flex items-center gap-1 pl-1">
                            <span className="font-mono">↳</span>
                            <span className="truncate">
                              claimed {agent.working_on.label}: {agent.working_on.title}
                            </span>
                          </div>
                        ) : (
                          <div className="text-[10px] text-[#8B8FA3] italic pl-1">
                            idle
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Bottom half: LIVE ACTIVITY FEED */}
      <div className="flex-1 flex flex-col min-h-0">
        <div className="p-3 pb-1 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-[#8B8FA3]">
          <span className="flex items-center gap-1.5">
            <Radio className="w-3.5 h-3.5 text-[#22C55E]" />
            <span>Event stream</span>
          </span>
          <span className="text-[10px] font-mono">#{events[0]?.seq ?? 0}</span>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
          {events.length === 0 ? (
            <div className="text-center py-8 text-xs text-[#8B8FA3] italic">
              No recent activity yet.
            </div>
          ) : (
            events.map((event, idx) => {
              const isStaleEvent =
                event.type === 'record.stale' || event.type === 'decision.changed';
              const isCheckEvent = event.type.startsWith('verification');
              const isRejected = event.type.includes('rejected');

              return (
                <div
                  key={`${event.id || event.seq}-${idx}`}
                  className={`p-2 rounded-lg border text-xs transition-all ${
                    isStaleEvent
                      ? 'bg-[#F59E0B]/10 border-[#F59E0B]/30'
                      : isRejected
                      ? 'bg-[#EF4444]/10 border-[#EF4444]/30'
                      : isCheckEvent
                      ? 'bg-[#1D1F27] border-[#2A2D37]'
                      : 'bg-[#16171D] border-[#2A2D37]'
                  }`}
                >
                  <div className="flex items-center justify-between text-[10px] text-[#8B8FA3] mb-1">
                    <span className="font-mono">
                      {formatTimestamp(event.created_at)}
                    </span>
                    {event.seq && (
                      <span className="font-mono text-[#8B8FA3]">#{event.seq}</span>
                    )}
                  </div>

                  <div className="flex items-start gap-1.5 mb-1">
                    {event.actor?.kind === 'agent' ? (
                      <AgentBadge agent={event.actor} size="sm" />
                    ) : event.actor?.kind === 'user' ? (
                      <span className="text-[11px] font-medium text-[#E6E7EB]">
                        {event.actor.name}
                      </span>
                    ) : (
                      <span className="text-[11px] font-mono text-[#8B8FA3]">
                        Baton
                      </span>
                    )}
                  </div>

                  <p
                    className={`text-[11px] leading-tight ${
                      isStaleEvent
                        ? 'text-[#F59E0B] font-medium'
                        : isRejected
                        ? 'text-[#EF4444] font-medium'
                        : 'text-[#E6E7EB]'
                    }`}
                  >
                    {event.summary}
                  </p>
                </div>
              );
            })
          )}
        </div>
      </div>
    </aside>
  );
};
