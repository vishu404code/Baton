import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { Agent } from '../api/types';
import { TOOLS, ago } from '../lib/tools';

/** The connected apps and whether each one is live right now. Nothing else. */
export const ContextView: React.FC<{ roomId: string }> = ({ roomId }) => {
  const { data } = useQuery<{ agents: Agent[] }>({ queryKey: ['agents', roomId], queryFn: () => api.getAgents(roomId), refetchInterval: 2000 });
  const agents = data?.agents || [];

  return (
    <div className="h-full overflow-y-auto baton-fade">
      <div className="px-10 pt-9 pb-5 border-b border-[#2A2D37]">
        <h1 className="text-[34px] leading-tight text-[#E6E7EB]">Connected apps</h1>
      </div>
      <div className="px-10 py-7 grid grid-cols-1 md:grid-cols-2 gap-4 max-w-4xl">
        {TOOLS.map((t) => {
          const mine = agents.filter((a) => a.tool === t.id && !a.revoked);
          const seenAt = mine.map((a) => a.last_seen_at).filter(Boolean).sort().pop() as string | undefined;
          const active = seenAt ? Date.now() - new Date(seenAt).getTime() < 90_000 : false;
          const connected = mine.length > 0;
          return (
            <div key={t.id} className="baton-lift rounded-3xl border bg-[#111217] p-5 flex items-center gap-4"
              style={{ borderColor: active ? `${t.color}88` : undefined, boxShadow: active ? `0 0 0 3px ${t.color}18` : undefined }}>
              <span className="w-12 h-12 rounded-full flex items-center justify-center text-[17px] font-semibold shrink-0"
                style={{ background: `${t.color}26`, color: t.color, boxShadow: `inset 0 0 0 1.5px ${t.color}66` }}>{t.label[0]}</span>
              <div className="min-w-0">
                <div className="text-[16px] font-semibold text-[#E6E7EB]">{t.long}</div>
                <div className="mt-0.5 text-[13px] flex items-center gap-2 text-[#8B8FA3]">
                  <span className={`w-2 h-2 rounded-full ${active ? 'animate-pulse' : ''}`} style={{ background: active ? '#22C55E' : connected ? '#E8A93A' : '#9A8FA6' }} />
                  {active ? 'Active now' : connected ? (seenAt ? `Connected · last seen ${ago(seenAt)}` : 'Connected') : 'Not connected'}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
