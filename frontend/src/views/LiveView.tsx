import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity } from 'lucide-react';
import { api } from '../api/client';
import { TOOLS, colorOf, ago } from '../lib/tools';

interface Card { tool: string; label: string; last_seen_at: string | null; last: { summary: string; at: string } | null }
interface Ev { id: string; type: string; summary: string; created_at: string; payload?: { tool?: string }; actor?: { tool?: string } }

export const LiveView: React.FC<{ roomId: string }> = ({ roomId }) => {
  const { data } = useQuery<{ events: Ev[]; tools: Card[] }>({ queryKey: ['activity', roomId], queryFn: () => api.getActivity(roomId), refetchInterval: 1500 });
  const { data: rm } = useQuery<{ tasks: any[] }>({ queryKey: ['roadmap', roomId], queryFn: () => api.getRoadmap(roomId), refetchInterval: 3000 });
  const tasks = rm?.tasks || [];
  const cards = data?.tools || [];
  const events = data?.events || [];

  return (
    <div className="h-full overflow-y-auto baton-fade">
      <div className="px-10 pt-9 pb-5 border-b border-[#2A2D37]">
        <h1 className="text-[34px] leading-tight text-[#E6E7EB]">Live</h1>
        <p className="mt-1.5 text-[14px] text-[#8B8FA3]">What each AI is doing right now. Work in one tool and watch the others hear about it.</p>
      </div>
      <div className="px-10 py-7 space-y-7 max-w-5xl">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {TOOLS.map((t) => {
            const c = cards.find((x) => x.tool === t.id);
            const seen = c?.last_seen_at ? Date.now() - new Date(c.last_seen_at).getTime() : Infinity;
            const active = seen < 90_000;
            const task = tasks.find((x) => x.owner_tool === t.id && x.status === 'in_progress') || tasks.find((x) => x.owner_tool === t.id && x.status === 'waiting');
            return (
              <div key={t.id} className="baton-lift rounded-3xl border bg-[#111217] p-5" style={{ borderColor: active ? `${t.color}88` : undefined, boxShadow: active ? `0 0 0 3px ${t.color}18` : undefined }}>
                <div className="flex items-center gap-3">
                  <span className="w-10 h-10 rounded-full flex items-center justify-center text-[14px] font-semibold" style={{ background: `${t.color}26`, color: t.color, boxShadow: `inset 0 0 0 1.5px ${t.color}66` }}>{t.label[0]}</span>
                  <div className="flex-1">
                    <div className="text-[15px] font-semibold text-[#E6E7EB]">{t.long}</div>
                    <div className="text-[12px] flex items-center gap-1.5 text-[#8B8FA3]">
                      <span className={`w-2 h-2 rounded-full ${active ? 'animate-pulse' : ''}`} style={{ background: active ? '#22C55E' : seen === Infinity ? '#9A8FA6' : '#E8A93A' }} />
                      {active ? 'Active now' : seen === Infinity ? 'Not seen yet' : `Idle · last seen ${ago(c?.last_seen_at)}`}
                    </div>
                  </div>
                </div>
                <div className="mt-4 text-[13px] text-[#E6E7EB] min-h-[40px]">
                  {c?.last ? <><span className="text-[#8B8FA3]">{ago(c.last.at)}:</span> {c.last.summary.replace(/^[^:]+: /, '')}</> : <span className="text-[#8B8FA3]">No activity yet.</span>}
                </div>
                {task && (
                  <div className="mt-3 text-[12px] rounded-xl px-3 py-2 bg-[#1D1F27] border border-[#2A2D37] text-[#8B8FA3]">
                    Task {task.number}: <span className="text-[#E6E7EB]">{task.title}</span> · {task.status.replace('_', ' ')}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div>
          <div className="flex items-center gap-3 mb-4">
            <h2 className="text-lg text-[#E6E7EB] flex items-center gap-2"><Activity className="w-4 h-4 text-[#818CF8]" /> Everything that happened</h2>
            <div className="flex-1 h-px bg-[#2A2D37]" />
          </div>
          {events.length === 0 && <div className="rounded-3xl border border-dashed border-[#2A2D37] p-8 text-center text-[13px] text-[#8B8FA3]">Nothing yet. Open Claude, Codex or Antigravity in your project folder and give it a prompt.</div>}
          <div className="space-y-2">
            {events.map((e) => {
              const tool = e.payload?.tool || e.actor?.tool || '';
              return (
                <div key={e.id} className="flex items-center gap-3 rounded-2xl border border-[#2A2D37] bg-[#111217] px-4 py-2.5 baton-fade">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: colorOf(tool) }} />
                  <span className="flex-1 text-[13px] text-[#E6E7EB] truncate">{e.summary}</span>
                  <span className="text-[11px] text-[#8B8FA3] whitespace-nowrap">{ago(e.created_at)}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
