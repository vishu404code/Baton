import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Loader2, Plug, X } from 'lucide-react';
import { api } from '../api/client';
import { TOOLS, ago } from '../lib/tools';
import { ModelsView } from './ModelsView';

export const SetupView: React.FC<{ roomId: string }> = ({ roomId }) => {
  const qc = useQueryClient();
  const { data } = useQuery<any>({ queryKey: ['hooks'], queryFn: () => api.getHooksStatus(), refetchInterval: 3000 });
  const [folder, setFolder] = useState('');
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState('');
  const dir = folder || data?.project_dir || '~/Desktop/baton';

  const connect = async () => {
    setBusy(true);
    setErr('');
    try {
      setRes(await api.installHooks(dir));
      qc.invalidateQueries({ queryKey: ['hooks'] });
    } catch (e: any) {
      setErr(e?.message || 'Could not connect.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto baton-fade">
      <div className="px-10 pt-9 pb-5 border-b border-[#2A2D37]">
        <h1 className="text-[34px] leading-tight text-[#E6E7EB]">Setup</h1>
        <p className="mt-1.5 text-[14px] text-[#8B8FA3]">Connect your AI tools once. After that they report and listen on their own.</p>
      </div>
      <div className="px-10 py-7 space-y-6 max-w-4xl">
        <div className="baton-lift rounded-3xl border border-[#2A2D37] bg-[#111217] p-5 space-y-3">
          <div className="text-[15px] font-semibold text-[#E6E7EB]">1. Your project folder</div>
          <div className="text-[12px] text-[#8B8FA3]">Only work inside this folder is shared. Other projects on your Mac are ignored.</div>
          <div className="flex gap-2.5">
            <input value={folder || data?.project_dir || ''} onChange={(e) => setFolder(e.target.value)} placeholder="~/Desktop/baton"
              className="flex-1 px-4 py-2.5 bg-[#1D1F27] border border-[#2A2D37] rounded-2xl text-[13px] font-mono text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]" />
            <button onClick={connect} disabled={busy} className="px-5 py-2.5 rounded-2xl bg-[#6366F1] text-white text-[13px] font-semibold flex items-center gap-2 disabled:opacity-60">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plug className="w-4 h-4" />} Connect all tools
            </button>
          </div>
          {err && <div className="text-[12px] text-[#EF4444]">{err}</div>}
          {res && <div className="text-[12px] text-[#22C55E]">Connected {Object.values(res.results).filter((r: any) => r.ok).length} tools to “{res.room}”. Now restart each tool once and open a new chat.</div>}
        </div>

        <div className="baton-lift rounded-3xl border border-[#2A2D37] bg-[#111217] p-5">
          <div className="text-[15px] font-semibold text-[#E6E7EB] mb-3">2. Tool status</div>
          <div className="divide-y divide-[#2A2D37]">
            {TOOLS.filter((t) => t.id !== 'gemini_cli').map((t) => {
              const ok = data?.installed?.[t.id];
              return (
                <div key={t.id} className="py-3 flex items-center gap-3 text-[13px]">
                  <span className="w-8 h-8 rounded-full flex items-center justify-center text-[12px] font-semibold" style={{ background: `${t.color}26`, color: t.color }}>{t.label[0]}</span>
                  <div className="flex-1">
                    <div className="text-[#E6E7EB] font-medium">{t.long}</div>
                    <div className="text-[12px] text-[#8B8FA3]">Last heard from: {ago(data?.last_seen?.[t.id])}</div>
                  </div>
                  <span className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] border ${ok ? 'border-[#22C55E]/40 text-[#22C55E]' : 'border-[#2A2D37] text-[#8B8FA3]'}`}>
                    {ok ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />} {ok ? 'Hooks installed' : 'Not connected'}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="mt-3 text-[12px] leading-relaxed text-[#8B8FA3]">
            <b className="text-[#E6E7EB]">Codex:</b> the first time, type <code>/hooks</code> in Codex and trust the Baton hooks. Codex asks you to approve any new hook before it runs.
          </div>
        </div>

        <div className="rounded-3xl border border-dashed border-[#2A2D37] p-5">
          <div className="text-[13px] font-semibold text-[#E6E7EB]">Optional: API keys</div>
          <div className="text-[12px] text-[#8B8FA3] mb-2">Not needed. Baton uses the apps already signed in on this Mac.</div>
          <details>
            <summary className="text-[12px] text-[#818CF8] cursor-pointer">Show API keys</summary>
            <div className="mt-4 -mx-10"><ModelsView roomId={roomId} /></div>
          </details>
        </div>
      </div>
    </div>
  );
};
