import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Loader2, Plug, X } from 'lucide-react';
import { api } from '../api/client';
import { TOOLS, ago } from '../lib/tools';

export const SetupView: React.FC<{ roomId: string }> = () => {
  const qc = useQueryClient();
  const { data } = useQuery<any>({ queryKey: ['hooks'], queryFn: () => api.getHooksStatus(), refetchInterval: 3000 });
  const [folder, setFolder] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const value = folder ?? data?.project_dir ?? '';

  const connect = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.installHooks(value || '~/Desktop/baton');
      const n = Object.values(r.results).filter((x: any) => x.ok).length;
      setMsg({ ok: true, text: `Connected ${n} tools. Restart each one and open a new chat.` });
      qc.invalidateQueries({ queryKey: ['hooks'] });
    } catch (e: any) {
      setMsg({ ok: false, text: e?.message || 'Could not connect.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto baton-fade">
      <div className="px-10 pt-9 pb-5 border-b border-[#2A2D37]">
        <h1 className="text-[34px] leading-tight text-[#E6E7EB]">Setup</h1>
      </div>
      <div className="px-10 py-7 space-y-5 max-w-3xl">
        <div className="baton-lift rounded-3xl border border-[#2A2D37] bg-[#111217] p-5 space-y-3">
          <div className="text-[14px] font-semibold text-[#E6E7EB]">Project folder</div>
          <div className="flex gap-2.5">
            <input value={value} onChange={(e) => setFolder(e.target.value)} placeholder="~/Desktop/my-project"
              className="flex-1 px-4 py-2.5 bg-[#1D1F27] border border-[#2A2D37] rounded-2xl text-[13px] font-mono text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]" />
            <button onClick={connect} disabled={busy} className="px-5 py-2.5 rounded-2xl bg-[#6366F1] text-white text-[13px] font-semibold flex items-center gap-2 disabled:opacity-60">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plug className="w-4 h-4" />} Connect tools
            </button>
          </div>
          <div className="text-[12px] text-[#8B8FA3]">Separate several folders with a comma. Work outside them is ignored.</div>
          {msg && <div className={`text-[12px] ${msg.ok ? 'text-[#22C55E]' : 'text-[#EF4444]'}`}>{msg.text}</div>}
        </div>

        <div className="baton-lift rounded-3xl border border-[#2A2D37] bg-[#111217] px-5 py-2">
          {TOOLS.map((t) => {
            const ok = data?.installed?.[t.id];
            return (
              <div key={t.id} className="py-3.5 flex items-center gap-3 text-[13px] border-b last:border-b-0 border-[#2A2D37]">
                <span className="w-8 h-8 rounded-full flex items-center justify-center text-[12px] font-semibold" style={{ background: `${t.color}26`, color: t.color }}>{t.label[0]}</span>
                <div className="flex-1 text-[#E6E7EB] font-medium">{t.long}</div>
                <span className="text-[12px] text-[#8B8FA3]">{data?.last_seen?.[t.id] ? `heard ${ago(data.last_seen[t.id])}` : ''}</span>
                <span className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] border ${ok ? 'border-[#22C55E]/40 text-[#22C55E]' : 'border-[#2A2D37] text-[#8B8FA3]'}`}>
                  {ok ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />} {ok ? 'Connected' : 'Not connected'}
                </span>
              </div>
            );
          })}
        </div>
        <div className="text-[12px] text-[#8B8FA3] px-1 space-y-1">
          <div>Codex: type <code>/hooks</code> once and trust Baton.</div>
          <div>Gemini: needs Google's Gemini CLI. Install it with <code>npm install -g @google/gemini-cli</code>, run <code>gemini</code> once to sign in, then press Connect tools.</div>
        </div>
      </div>
    </div>
  );
};
