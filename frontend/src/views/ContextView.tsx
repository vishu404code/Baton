import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Check, Send, ArrowRight, FileText, Sparkles } from 'lucide-react';
import { api } from '../api/client';
import { Agent, ContextEntry } from '../api/types';
import { formatTimeAgo } from '../lib/utils';
import { DemoChat } from '../components/DemoChat';
import { ChatPanel } from '../components/ChatPanel';
import { KnowledgeCard } from '../components/KnowledgeCard';

const TOOLS: Array<{ id: string; label: string; color: string }> = [
  { id: 'claude_code', label: 'Claude Code', color: '#F59E0B' },
  { id: 'codex', label: 'Codex / ChatGPT', color: '#22D3EE' },
  { id: 'antigravity', label: 'Antigravity', color: '#A78BFA' },
  { id: 'gemini_cli', label: 'Gemini CLI', color: '#60A5FA' },
];
const colorOf = (tool: string) => TOOLS.find((t) => t.id === tool)?.color || '#8B8FA3';
const labelOf = (tool: string) => (tool === 'user' ? 'You' : TOOLS.find((t) => t.id === tool)?.label || 'AI tool');

export const ContextView: React.FC<{ roomId: string; demoRoomId?: string; onOpenDemo?: () => void; onOpenKeys?: () => void }> = ({ roomId, demoRoomId, onOpenDemo, onOpenKeys }) => {
  const qc = useQueryClient();
  const [note, setNote] = useState('');
  const [next, setNext] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const isDemo = demoRoomId === roomId;

  const { data } = useQuery<{ entries: ContextEntry[]; handoff_markdown: string }>({
    queryKey: ['context', roomId],
    queryFn: () => api.getContext(roomId),
    refetchInterval: 2500,
  });
  const { data: agentsData } = useQuery<{ agents: Agent[] }>({
    queryKey: ['agents', roomId],
    queryFn: () => api.getAgents(roomId),
    refetchInterval: 5000,
  });
  const agents = agentsData?.agents || [];
  const entries = data?.entries || [];

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!note.trim()) return;
    setBusy(true);
    try {
      await api.addContextNote(roomId, note.trim(), next.trim() || undefined);
      setNote('');
      setNext('');
      qc.invalidateQueries({ queryKey: ['context', roomId] });
    } finally {
      setBusy(false);
    }
  };

  const copy = () => {
    navigator.clipboard.writeText(data?.handoff_markdown || '');
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="h-full flex flex-col baton-fade">
      {/* Hero */}
      <div className={`relative px-10 ${isDemo ? "pt-5 pb-4" : "pt-9 pb-7"} border-b border-[#2A2D37] overflow-hidden`}>
        <div className="baton-hero-glow" />
        <div className="relative max-w-5xl">
          <div className={`${isDemo ? "hidden" : "inline-flex"} items-center gap-2 px-3 py-1 rounded-full border border-[#6366F1]/40 bg-[#6366F1]/10 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#818CF8]`}>
            <Sparkles className="w-3.5 h-3.5" /> One memory for every AI
          </div>
          <h1 className={`${isDemo ? "text-[30px]" : "mt-4 text-[44px]"} leading-[1.05] text-[#E6E7EB]`}>
            Switch tools. <span className="baton-accent">Keep the thread.</span>
          </h1>
          <p className={`${isDemo ? "hidden" : ""} mt-3 text-[15px] leading-relaxed text-[#8B8FA3] max-w-2xl`}>
            Claude Code, ChatGPT, Antigravity and Gemini share one briefing. Each reads it the moment it starts and logs what it did when it
            stops, so you never explain the project twice.
          </p>
          <div className={`${isDemo ? "mt-3" : "mt-6"} grid grid-cols-2 lg:grid-cols-4 gap-3 max-w-4xl`}>
            {TOOLS.map((t) => {
              const agent = agents.find((a) => a.tool === t.id && !a.revoked);
              const live = !!agent?.last_seen_at;
              return (
                <div
                  key={t.id}
                  className="baton-lift rounded-2xl border border-[#2A2D37] bg-[#111217] px-4 py-3 flex items-center gap-3"
                  title={live ? `Last seen ${formatTimeAgo(agent!.last_seen_at)}` : agent ? 'Wired up. Waiting for its first conversation' : 'Not connected yet'}
                >
                  <span className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-semibold shrink-0" style={{ background: `${t.color}26`, color: t.color, boxShadow: `inset 0 0 0 1.5px ${t.color}66` }}>
                    {t.label[0]}
                  </span>
                  <div className="min-w-0">
                    <div className="text-[13px] font-semibold text-[#E6E7EB] truncate">{t.label}</div>
                    <div className="text-[11px] text-[#8B8FA3] flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full" style={{ background: live ? '#22C55E' : agent ? '#E8A93A' : '#9A8FA6' }} />
                      {live ? 'Connected' : agent ? 'Ready' : 'Not connected'}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_440px]">
        {/* Progress log */}
        <div className="overflow-y-auto px-10 py-7 space-y-6">
          {demoRoomId && demoRoomId !== roomId && onOpenDemo && (
            <button onClick={onOpenDemo} className="w-full baton-lift rounded-3xl border border-[#6366F1]/40 bg-[#6366F1]/10 px-5 py-4 flex items-center justify-between text-left">
              <span>
                <span className="block text-[15px] font-semibold text-[#E6E7EB]">Watch the live demo</span>
                <span className="block text-[12px] text-[#8B8FA3]">Four AIs plan a trip together without anyone re-explaining.</span>
              </span>
              <ArrowRight className="w-5 h-5 text-[#818CF8]" />
            </button>
          )}
          <ChatPanel roomId={roomId} onOpenKeys={onOpenKeys} />
          <DemoChat roomId={roomId} />
          <KnowledgeCard />
          <form onSubmit={save} className="baton-lift rounded-3xl border border-[#2A2D37] bg-[#111217] p-5 space-y-3">
            <div className="text-[13px] font-semibold text-[#E6E7EB]">Leave a note for the next AI</div>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder="e.g. We chose Postgres. Login is done, payments are next."
              className="w-full px-4 py-3 bg-[#1D1F27] border border-[#2A2D37] rounded-2xl text-[13px] text-[#E6E7EB] focus:outline-none focus:border-[#6366F1] resize-none"
            />
            <div className="flex gap-2.5">
              <input
                value={next}
                onChange={(e) => setNext(e.target.value)}
                placeholder="What should happen next? (optional)"
                className="flex-1 px-4 py-2.5 bg-[#1D1F27] border border-[#2A2D37] rounded-2xl text-[13px] text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]"
              />
              <button
                disabled={busy || !note.trim()}
                className="px-5 py-2.5 rounded-2xl bg-[#6366F1] text-white text-[13px] font-semibold flex items-center gap-2 disabled:opacity-50 transition-transform hover:-translate-y-px"
              >
                <Send className="w-4 h-4" /> Save
              </button>
            </div>
          </form>

          <div className="flex items-center gap-3">
            <h2 className="text-lg text-[#E6E7EB]">What your AIs have been doing</h2>
            <div className="flex-1 h-px bg-[#2A2D37]" />
          </div>

          {entries.length === 0 && (
            <div className="rounded-3xl border border-dashed border-[#2A2D37] p-10 text-center text-[13px] text-[#8B8FA3]">
              Nothing yet. Open any connected tool and start a chat: it calls <code className="text-[#E6E7EB]">get_handoff</code> by itself
              and logs its progress here.
            </div>
          )}

          <div className="relative space-y-4 pl-7">
            {entries.length > 0 && <div className="absolute left-[13px] top-2 bottom-2 w-px bg-[#2A2D37]" />}
            {entries.map((e) => (
              <div key={e.id} className="relative baton-lift rounded-3xl border border-[#2A2D37] bg-[#111217] p-5 baton-fade">
                <span
                  className="absolute -left-[34px] top-5 w-[22px] h-[22px] rounded-full flex items-center justify-center text-[10px] font-bold ring-4 ring-[#0B0C0F]/0"
                  style={{ background: colorOf(e.tool), color: '#fff', boxShadow: '0 0 0 4px rgba(255,255,255,0.04)' }}
                >
                  {e.author[0]?.toUpperCase()}
                </span>
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 min-w-0 text-[13px]">
                    <span className="font-semibold text-[#E6E7EB] truncate">{e.author}</span>
                    {labelOf(e.tool) !== e.author && !e.author.includes(labelOf(e.tool)) && <span className="text-[#8B8FA3] truncate">· {labelOf(e.tool)}</span>}
                    {e.kind !== 'progress' && (
                      <span className="px-2 py-0.5 rounded-full bg-[#1D1F27] border border-[#2A2D37] text-[10px] uppercase tracking-wide text-[#8B8FA3]">{e.kind}</span>
                    )}
                  </div>
                  <span className="text-[11px] text-[#8B8FA3] whitespace-nowrap">{formatTimeAgo(e.created_at)}</span>
                </div>
                <p className="mt-2.5 text-[14px] leading-relaxed text-[#E6E7EB]">{e.summary}</p>
                {e.next_steps && (
                  <div className="mt-3 flex items-start gap-2 text-[13px] text-[#818CF8] bg-[#6366F1]/10 rounded-2xl px-3.5 py-2.5">
                    <ArrowRight className="w-4 h-4 mt-0.5 shrink-0" />
                    <span>{e.next_steps}</span>
                  </div>
                )}
                {e.files.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {e.files.slice(0, 6).map((f) => (
                      <span key={f} className="px-2.5 py-1 rounded-lg bg-[#1D1F27] border border-[#2A2D37] text-[11px] font-mono text-[#8B8FA3] flex items-center gap-1.5">
                        <FileText className="w-3 h-3" /> {f}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* The briefing the next AI receives */}
        <div className="border-l border-[#2A2D37] flex flex-col min-h-0 bg-[#0F1015]">
          <div className="px-6 py-5 border-b border-[#2A2D37] flex items-center justify-between">
            <div>
              <h2 className="text-lg text-[#E6E7EB]">The next AI reads this</h2>
              <div className="text-[12px] text-[#8B8FA3] mt-0.5">Fetched automatically via <code>get_handoff</code></div>
            </div>
            <button onClick={copy} className="px-3 py-2 rounded-xl bg-[#1D1F27] border border-[#2A2D37] text-[12px] text-[#E6E7EB] flex items-center gap-1.5 hover:border-[#6366F1] transition-colors">
              {copied ? <Check className="w-3.5 h-3.5 text-[#22C55E]" /> : <Copy className="w-3.5 h-3.5" />} {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <div className="flex-1 overflow-auto p-5">
            <pre className="rounded-2xl border border-[#2A2D37] bg-[#111217] p-5 text-[12px] leading-[1.7] font-mono text-[#C9CBD6] whitespace-pre-wrap">{data?.handoff_markdown || 'Loading…'}</pre>
          </div>
        </div>
      </div>
    </div>
  );
};
