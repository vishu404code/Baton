import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ClipboardPaste, Loader2, Plus, Sparkles, Trash2, Check } from 'lucide-react';
import { api } from '../api/client';
import { TOOLS, colorOf, EXAMPLE_ROADMAP } from '../lib/tools';

interface Task { number: number; title: string; owner_tool: string; description: string; done_when: string; depends_on: number[]; area: string; status: string; note: string }

const STATUS = [
  { id: 'waiting', label: 'Waiting', color: '#8B8FA3' },
  { id: 'in_progress', label: 'In progress', color: '#F59E0B' },
  { id: 'done', label: 'Done', color: '#22C55E' },
  { id: 'blocked', label: 'Blocked', color: '#EF4444' },
];

export const RoadmapView: React.FC<{ roomId: string }> = ({ roomId }) => {
  const qc = useQueryClient();
  const [paste, setPaste] = useState('');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [title, setTitle] = useState('');
  const [owner, setOwner] = useState('claude');
  const { data } = useQuery<{ tasks: Task[] }>({ queryKey: ['roadmap', roomId], queryFn: () => api.getRoadmap(roomId), refetchInterval: 2000 });
  const tasks = data?.tasks || [];
  const refresh = () => qc.invalidateQueries({ queryKey: ['roadmap', roomId] });
  const byNo = new Map(tasks.map((t) => [t.number, t]));
  const done = tasks.filter((t) => t.status === 'done').length;

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setErr('');
    try {
      await fn();
      refresh();
    } catch (e: any) {
      setErr(e?.message || 'Something went wrong.');
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="h-full overflow-y-auto baton-fade">
      <div className="px-10 pt-9 pb-5 border-b border-[#2A2D37]">
        <div className="flex items-end justify-between gap-6">
          <div>
            <h1 className="text-[34px] leading-tight text-[#E6E7EB]">Roadmap</h1>
            <p className="mt-1.5 text-[14px] text-[#8B8FA3] max-w-2xl">
              One plan, one owner per task. Every AI tool on this Mac reads it when it starts and hears when anything changes.
            </p>
          </div>
          {tasks.length > 0 && (
            <div className="text-right shrink-0">
              <div className="text-[28px] text-[#E6E7EB]">{done}<span className="text-[#8B8FA3]"> / {tasks.length}</span></div>
              <div className="text-[11px] uppercase tracking-wider text-[#8B8FA3]">tasks done</div>
            </div>
          )}
        </div>
        {tasks.length > 0 && (
          <div className="mt-4 h-1.5 rounded-full bg-[#1D1F27] overflow-hidden">
            <div className="h-full rounded-full bg-[#22C55E] transition-all duration-700" style={{ width: `${(done / tasks.length) * 100}%` }} />
          </div>
        )}
      </div>

      <div className="px-10 py-7 space-y-6 max-w-5xl">
        {tasks.length === 0 && (
          <div className="baton-lift rounded-3xl border border-[#2A2D37] bg-[#111217] p-6 space-y-4">
            <div className="text-[15px] font-semibold text-[#E6E7EB]">Start with a roadmap</div>
            <ol className="text-[13px] text-[#8B8FA3] space-y-1.5 list-decimal pl-5">
              <li>Plan it in ChatGPT (or Codex). Ask for tasks, and say which AI should do each one.</li>
              <li>Paste the plan below, or let Codex save it to Baton by itself.</li>
              <li>Open Claude or Antigravity. It already knows its task.</li>
            </ol>
            <button onClick={() => run('example', () => api.saveRoadmap(roomId, EXAMPLE_ROADMAP, true))}
              className="px-4 py-2.5 rounded-xl bg-[#6366F1]/15 border border-[#6366F1]/40 text-[#E6E7EB] text-[13px] font-semibold flex items-center gap-2">
              {busy === 'example' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4 text-[#818CF8]" />} Load the login page example
            </button>
          </div>
        )}

        <div className="space-y-3">
          {tasks.map((t) => {
            const waits = t.depends_on.filter((n) => byNo.get(n) && byNo.get(n)!.status !== 'done');
            const st = STATUS.find((s) => s.id === t.status) || STATUS[0];
            return (
              <div key={t.number} className="baton-lift rounded-3xl border border-[#2A2D37] bg-[#111217] p-5 flex gap-4">
                <div className="w-9 h-9 rounded-full shrink-0 flex items-center justify-center text-[13px] font-semibold"
                  style={{ background: `${colorOf(t.owner_tool)}26`, color: colorOf(t.owner_tool), boxShadow: `inset 0 0 0 1.5px ${colorOf(t.owner_tool)}66` }}>
                  {t.status === 'done' ? <Check className="w-4 h-4" /> : t.number}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-3">
                    <div className={`text-[15px] font-semibold ${t.status === 'done' ? 'text-[#8B8FA3] line-through' : 'text-[#E6E7EB]'}`}>{t.title}</div>
                    <button onClick={() => run('del', () => api.deleteRoadmapTask(roomId, t.number))} className="text-[#8B8FA3] hover:text-[#EF4444] shrink-0" title="Remove task">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                  {t.description && <p className="mt-1 text-[13px] leading-relaxed text-[#8B8FA3]">{t.description}</p>}
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-[12px]">
                    <select value={TOOLS.find((x) => x.id === t.owner_tool)?.id} onChange={(e) => run('owner', () => api.patchRoadmapTask(roomId, t.number, { owner: e.target.value }))}
                      className="px-2.5 py-1.5 rounded-full border bg-[#1D1F27] text-[#E6E7EB]" style={{ borderColor: `${colorOf(t.owner_tool)}77` }}>
                      {TOOLS.map((x) => <option key={x.id} value={x.id}>{x.long}</option>)}
                    </select>
                    <select value={t.status} onChange={(e) => run('status', () => api.patchRoadmapTask(roomId, t.number, { status: e.target.value }))}
                      className="px-2.5 py-1.5 rounded-full border bg-[#1D1F27]" style={{ borderColor: `${st.color}77`, color: st.color }}>
                      {STATUS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                    </select>
                    {waits.length > 0 && t.status !== 'done' && <span className="px-2.5 py-1.5 rounded-full bg-[#F59E0B]/10 text-[#F59E0B]">waits for task {waits.join(', ')}</span>}
                    {t.area && <span className="px-2.5 py-1.5 rounded-full bg-[#1D1F27] border border-[#2A2D37] text-[#8B8FA3] font-mono">{t.area}</span>}
                  </div>
                  {t.done_when && <div className="mt-2.5 text-[12px] text-[#8B8FA3]"><span className="text-[#E6E7EB]">Done when:</span> {t.done_when}</div>}
                  {t.note && <div className="mt-2 text-[12.5px] text-[#818CF8] bg-[#6366F1]/10 rounded-xl px-3 py-2">{t.note}</div>}
                </div>
              </div>
            );
          })}
        </div>

        <form onSubmit={(e) => { e.preventDefault(); if (!title.trim()) return; run('add', async () => { await api.saveRoadmap(roomId, [{ title: title.trim(), owner }], false); setTitle(''); }); }}
          className="flex gap-2.5">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Add a task…"
            className="flex-1 px-4 py-2.5 bg-[#1D1F27] border border-[#2A2D37] rounded-2xl text-[13px] text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]" />
          <select value={owner} onChange={(e) => setOwner(e.target.value)} className="px-3 rounded-2xl bg-[#1D1F27] border border-[#2A2D37] text-[13px] text-[#E6E7EB]">
            {TOOLS.map((x) => <option key={x.id} value={x.label.toLowerCase()}>{x.label}</option>)}
          </select>
          <button disabled={!title.trim() || !!busy} className="px-4 rounded-2xl bg-[#6366F1] text-white text-[13px] font-semibold flex items-center gap-2 disabled:opacity-50"><Plus className="w-4 h-4" /> Add</button>
        </form>

        <div className="baton-lift rounded-3xl border border-[#2A2D37] bg-[#111217] p-5 space-y-3">
          <div className="flex items-center gap-2 text-[14px] font-semibold text-[#E6E7EB]"><ClipboardPaste className="w-4 h-4 text-[#818CF8]" /> Paste a roadmap from anywhere</div>
          <div className="text-[12px] text-[#8B8FA3]">Written in ChatGPT, a doc, anywhere. Baton reads it and assigns each task. This replaces the current roadmap.</div>
          <textarea value={paste} onChange={(e) => setPaste(e.target.value)} rows={4} placeholder="1. Research competitors (ChatGPT)&#10;2. Build the REST API (Claude)&#10;3. Build the screens (Antigravity)"
            className="w-full px-4 py-3 bg-[#1D1F27] border border-[#2A2D37] rounded-2xl text-[13px] text-[#E6E7EB] focus:outline-none focus:border-[#6366F1] resize-none" />
          <button disabled={paste.trim().length < 20 || !!busy} onClick={() => run('import', async () => { await api.importRoadmap(roomId, paste); setPaste(''); })}
            className="px-4 py-2.5 rounded-xl bg-[#6366F1] text-white text-[13px] font-semibold flex items-center gap-2 disabled:opacity-50">
            {busy === 'import' ? <><Loader2 className="w-4 h-4 animate-spin" /> Reading it (about 10 seconds)…</> : 'Import roadmap'}
          </button>
        </div>
        {err && <div className="text-[13px] text-[#EF4444]">{err}</div>}
      </div>
    </div>
  );
};
