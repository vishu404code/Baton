import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { TOOLS, colorOf, ago } from '../lib/tools';

interface Card { tool: string; label: string; last_seen_at: string | null; last: { summary: string; at: string } | null }
interface Ev { id: string; seq: number; type: string; summary: string; created_at: string; payload?: { tool?: string; event?: string; path?: string }; actor?: { tool?: string } }

const KIND: Record<string, { label: string; color: string }> = {
  prompt: { label: 'PROMPT', color: '#818CF8' },
  edit: { label: 'EDIT', color: '#22C55E' },
  read: { label: 'READ', color: '#8B8FA3' },
  command: { label: 'COMMAND', color: '#F59E0B' },
  start: { label: 'START', color: '#8B8FA3' },
  stop: { label: 'DONE', color: '#8B8FA3' },
  task: { label: 'TASK', color: '#22D3EE' },
  roadmap: { label: 'ROADMAP', color: '#22D3EE' },
  note: { label: 'NOTE', color: '#818CF8' },
};

const kindOf = (e: Ev): string => {
  if (e.type === 'activity.logged') return e.payload?.event || 'start';
  if (e.type === 'task.updated') return 'task';
  if (e.type === 'roadmap.saved') return 'roadmap';
  if (e.type === 'context.saved') return 'note';
  return 'start';
};

export const LiveView: React.FC<{ roomId: string }> = ({ roomId }) => {
  const [only, setOnly] = useState<string>('all');
  const { data } = useQuery<{ events: Ev[]; tools: Card[] }>({ queryKey: ['activity', roomId], queryFn: () => api.getActivity(roomId), refetchInterval: 1200 });
  const { data: rm } = useQuery<{ tasks: any[] }>({ queryKey: ['roadmap', roomId], queryFn: () => api.getRoadmap(roomId), refetchInterval: 3000 });
  const tasks = rm?.tasks || [];
  const cards = data?.tools || [];
  const events = (data?.events || []).filter((e) => only === 'all' || (e.payload?.tool || e.actor?.tool) === only);

  return (
    <div className="h-full overflow-y-auto baton-fade">
      <div className="px-10 pt-9 pb-5 border-b border-[#2A2D37]">
        <h1 className="text-[34px] leading-tight text-[#E6E7EB]">Live</h1>
        <p className="mt-1.5 text-[14px] text-[#8B8FA3]">Every prompt, file change, command and task update from every tool, as it happens.</p>
      </div>
      <div className="px-10 py-7 space-y-6 max-w-5xl">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {TOOLS.map((t) => {
            const c = cards.find((x) => x.tool === t.id);
            const seen = c?.last_seen_at ? Date.now() - new Date(c.last_seen_at).getTime() : Infinity;
            const active = seen < 90_000;
            const task = tasks.find((x) => x.owner_tool === t.id && x.status === 'in_progress') || tasks.find((x) => x.owner_tool === t.id && x.status === 'waiting');
            return (
              <div key={t.id} className="baton-lift rounded-2xl border bg-[#111217] p-4" style={{ borderColor: active ? `${t.color}88` : undefined, boxShadow: active ? `0 0 0 3px ${t.color}18` : undefined }}>
                <div className="flex items-center gap-2.5">
                  <span className="w-8 h-8 rounded-full flex items-center justify-center text-[12px] font-semibold" style={{ background: `${t.color}26`, color: t.color, boxShadow: `inset 0 0 0 1.5px ${t.color}66` }}>{t.label[0]}</span>
                  <div className="min-w-0">
                    <div className="text-[13px] font-semibold text-[#E6E7EB] truncate">{t.long}</div>
                    <div className="text-[11px] flex items-center gap-1.5 text-[#8B8FA3]">
                      <span className={`w-1.5 h-1.5 rounded-full ${active ? 'animate-pulse' : ''}`} style={{ background: active ? '#22C55E' : seen === Infinity ? '#9A8FA6' : '#E8A93A' }} />
                      {active ? 'Active now' : seen === Infinity ? 'Not seen yet' : `Idle · ${ago(c?.last_seen_at)}`}
                    </div>
                  </div>
                </div>
                {task && <div className="mt-3 text-[11.5px] text-[#8B8FA3] truncate">Task {task.number}: <span className="text-[#E6E7EB]">{task.title}</span></div>}
              </div>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {[{ id: 'all', label: 'Everything' }, ...TOOLS.map((t) => ({ id: t.id as string, label: t.label }))].map((f) => (
            <button key={f.id} onClick={() => setOnly(f.id)}
              className={`px-3 py-1.5 rounded-full border text-[12px] transition-colors ${only === f.id ? 'border-[#6366F1] bg-[#6366F1]/10 text-[#E6E7EB]' : 'border-[#2A2D37] bg-[#1D1F27] text-[#8B8FA3] hover:text-[#E6E7EB]'}`}>{f.label}</button>
          ))}
          <span className="ml-auto text-[12px] text-[#8B8FA3]">{events.length} events</span>
        </div>

        {events.length === 0 && <div className="rounded-3xl border border-dashed border-[#2A2D37] p-8 text-center text-[13px] text-[#8B8FA3]">Nothing yet. Open a tool in your project folder and give it a prompt.</div>}
        <div className="space-y-1.5">
          {events.map((e) => {
            const tool = e.payload?.tool || e.actor?.tool || '';
            const k = KIND[kindOf(e)] || KIND.start;
            const text = e.summary.replace(/^(Claude|ChatGPT \(Codex\)|ChatGPT|Antigravity|Gemini|Claude Code|Codex[^:]*): /, '');
            return (
              <div key={e.id} className="flex items-center gap-3 rounded-xl border border-[#2A2D37] bg-[#111217] px-3.5 py-2 baton-fade">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: colorOf(tool) }} />
                <span className="text-[10px] font-semibold tracking-wider w-[62px] shrink-0" style={{ color: k.color }}>{k.label}</span>
                <span className="text-[11.5px] text-[#8B8FA3] w-[84px] shrink-0 truncate">{TOOLS.find((t) => t.id === tool)?.label || 'Baton'}</span>
                <span className={`flex-1 text-[13px] text-[#E6E7EB] truncate ${kindOf(e) === 'command' ? 'font-mono text-[12px]' : ''}`} title={text}>{text}</span>
                <span className="text-[11px] text-[#8B8FA3] whitespace-nowrap">{ago(e.created_at)}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
