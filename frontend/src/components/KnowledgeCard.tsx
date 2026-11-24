import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { BookOpen, Globe, Loader2, Plus } from 'lucide-react';
import { api } from '../api/client';

interface Src { source: string; url: string | null; documents: number }

export const KnowledgeCard: React.FC = () => {
  const qc = useQueryClient();
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const { data } = useQuery<{ sources: Src[] }>({ queryKey: ['knowledge'], queryFn: () => api.getKnowledge(), refetchInterval: 8000 });
  const sources = data?.sources || [];

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim() || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.addKnowledgeUrl(url.trim());
      setMsg({ ok: true, text: `Added ${r.added} documents from ${r.source}. Every AI can use them now.` });
      setUrl('');
      qc.invalidateQueries({ queryKey: ['knowledge'] });
      qc.invalidateQueries({ queryKey: ['context'] });
    } catch (ex: any) {
      setMsg({ ok: false, text: ex?.message || 'Could not read that website.' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="baton-lift rounded-3xl border border-[#2A2D37] bg-[#111217] p-5 space-y-3">
      <div className="flex items-start gap-2.5">
        <BookOpen className="w-4 h-4 mt-0.5 text-[#818CF8]" />
        <div className="flex-1">
          <div className="text-[15px] font-semibold text-[#E6E7EB]">What your AIs know</div>
          <div className="text-[12px] text-[#8B8FA3]">Reference material every AI reads before answering. Add a website and they learn it.</div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {sources.map((s) => (
          <span key={s.source} className="px-3 py-1.5 rounded-full border border-[#2A2D37] bg-[#1D1F27] text-[12px] text-[#E6E7EB] flex items-center gap-1.5" title={s.url || ''}>
            <Globe className="w-3 h-3 text-[#818CF8]" /> {s.source.length > 40 ? s.source.slice(0, 40) + '…' : s.source}
            <span className="text-[#8B8FA3]">· {s.documents} documents</span>
          </span>
        ))}
        {!sources.length && <span className="text-[12px] text-[#8B8FA3]">Nothing added yet.</span>}
      </div>
      <form onSubmit={add} className="flex gap-2.5">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://your-website.com"
          className="flex-1 px-4 py-2.5 bg-[#1D1F27] border border-[#2A2D37] rounded-2xl text-[13px] text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]" />
        <button disabled={busy || !url.trim()} className="px-4 py-2.5 rounded-2xl bg-[#6366F1] text-white text-[13px] font-semibold flex items-center gap-2 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Add website
        </button>
      </form>
      {msg && <div className={`text-[12px] ${msg.ok ? 'text-[#22C55E]' : 'text-[#EF4444]'}`}>{msg.text}</div>}
    </div>
  );
};
