import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Check, Send, ArrowRight, FileText, Sparkles } from 'lucide-react';
import { api } from '../api/client';
import { Agent, ContextEntry } from '../api/types';
import { formatTimeAgo } from '../lib/utils';

const TOOLS: Array<{ id: string; label: string; color: string }> = [
  { id: 'claude_code', label: 'Claude Code', color: '#F59E0B' },
  { id: 'codex', label: 'Codex / ChatGPT', color: '#22D3EE' },
  { id: 'antigravity', label: 'Antigravity', color: '#A78BFA' },
  { id: 'gemini_cli', label: 'Gemini CLI', color: '#60A5FA' },
];
const colorOf = (tool: string) => TOOLS.find((t) => t.id === tool)?.color || '#8B8FA3';
const labelOf = (tool: string) => (tool === 'user' ? 'You' : TOOLS.find((t) => t.id === tool)?.label || 'AI tool');

export const ContextView: React.FC<{ roomId: string }> = ({ roomId }) => {
  const qc = useQueryClient();
  const [note, setNote] = useState('');
  const [next, setNext] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

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
    <div className="h-full flex flex-col">
      <div className="px-8 pt-7 pb-5 border-b border-[#2A2D37] bg-gradient-to-b from-[#16171D] to-transparent">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#818CF8]">
          <Sparkles className="w-3.5 h-3.5" /> One memory for every AI
        </div>
        <h1 className="mt-1.5 text-2xl font-semibold tracking-tight text-[#E6E7EB]">Shared context</h1>
        <p className="mt-1 text-sm text-[#8B8FA3] max-w-2xl">
          Switch between Claude Code, ChatGPT, Antigravity and Gemini without re-explaining anything. Each tool reads this
          briefing when it starts and logs what it did when it stops.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {TOOLS.map((t) => {
            const agent = agents.find((a) => a.tool === t.id && !a.revoked);
            const live = !!agent?.last_seen_at;
            return (
              <span
                key={t.id}
                className="px-3 py-1.5 rounded-full border text-xs flex items-center gap-2"
                style={{ borderColor: `${t.color}55`, background: `${t.color}12`, color: t.color }}
                title={live ? `Last seen ${formatTimeAgo(agent!.last_seen_at)}` : agent ? 'Wired up, waiting for its first conversation' : 'Not connected yet'}
              >
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: live ? '#22C55E' : agent ? t.color : '#6B7280' }} />
                {t.label}
                <span className="opacity-70">{live ? 'connected' : agent ? 'ready' : 'not connected'}</span>
              </span>
            );
          })}
        </div>
      </div>

      <div className="flex-1 overflow-hidden grid grid-cols-1 xl:grid-cols-[1fr_420px] gap-0">
        {/* Live progress log */}
        <div className="overflow-y-auto px-8 py-6 space-y-5">
          <form onSubmit={save} className="rounded-2xl border border-[#2A2D37] bg-[#111217] p-4 space-y-2.5 shadow-sm">
            <div className="text-xs font-semibold text-[#E6E7EB]">Add a note for the next AI</div>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              placeholder="e.g. Decided to use Postgres for the backend. Auth is done, payments are next."
              className="w-full px-3 py-2 bg-[#1D1F27] border border-[#2A2D37] rounded-xl text-xs text-[#E6E7EB] focus:outline-none focus:border-[#6366F1] resize-none"
            />
            <div className="flex gap-2">
              <input
                value={next}
                onChange={(e) => setNext(e.target.value)}
                placeholder="Next steps (optional)"
                className="flex-1 px-3 py-2 bg-[#1D1F27] border border-[#2A2D37] rounded-xl text-xs text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]"
              />
              <button
                disabled={busy || !note.trim()}
                className="px-4 py-2 rounded-xl bg-[#6366F1] hover:bg-[#5558E6] text-white text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50"
              >
                <Send className="w-3.5 h-3.5" /> Save
              </button>
            </div>
          </form>

          <div className="text-[11px] font-semibold uppercase tracking-wider text-[#8B8FA3]">Activity across your AI tools</div>
          {entries.length === 0 && (
            <div className="rounded-2xl border border-dashed border-[#2A2D37] p-8 text-center text-xs text-[#8B8FA3]">
              Nothing yet. Start a conversation in any connected tool: it will call <code className="text-[#E6E7EB]">get_handoff</code> by
              itself and log its progress here.
            </div>
          )}
          <div className="space-y-3">
            {entries.map((e) => (
              <div key={e.id} className="rounded-2xl border border-[#2A2D37] bg-[#111217] p-4 hover:border-[#3A3E4D] transition-colors">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="w-2 h-2 rounded-full" style={{ background: colorOf(e.tool) }} />
                    <span className="font-semibold text-[#E6E7EB]">{e.author}</span>
                    <span className="text-[#8B8FA3]">· {labelOf(e.tool)}</span>
                    {e.kind !== 'progress' && (
                      <span className="px-1.5 py-0.5 rounded bg-[#2A2D37] text-[10px] uppercase text-[#8B8FA3]">{e.kind}</span>
                    )}
                  </div>
                  <span className="text-[11px] text-[#8B8FA3] font-mono">{formatTimeAgo(e.created_at)}</span>
                </div>
                <p className="mt-2 text-[13px] leading-relaxed text-[#E6E7EB]">{e.summary}</p>
                {e.next_steps && (
                  <div className="mt-2 flex items-start gap-1.5 text-xs text-[#818CF8]">
                    <ArrowRight className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                    <span>{e.next_steps}</span>
                  </div>
                )}
                {e.files.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {e.files.slice(0, 6).map((f) => (
                      <span key={f} className="px-2 py-0.5 rounded-md bg-[#1D1F27] border border-[#2A2D37] text-[10px] font-mono text-[#8B8FA3] flex items-center gap-1">
                        <FileText className="w-3 h-3" /> {f}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* What the next AI receives */}
        <div className="border-l border-[#2A2D37] bg-[#0F1015] flex flex-col min-h-0">
          <div className="px-5 py-4 border-b border-[#2A2D37] flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold text-[#E6E7EB]">What the next AI receives</div>
              <div className="text-[11px] text-[#8B8FA3]">Fetched automatically via <code>get_handoff</code></div>
            </div>
            <button onClick={copy} className="px-2.5 py-1.5 rounded-lg bg-[#1D1F27] border border-[#2A2D37] text-[11px] text-[#E6E7EB] flex items-center gap-1.5 hover:border-[#6366F1]">
              {copied ? <Check className="w-3.5 h-3.5 text-[#22C55E]" /> : <Copy className="w-3.5 h-3.5" />} {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <pre className="flex-1 overflow-auto p-5 text-[11px] leading-relaxed font-mono text-[#C9CBD6] whitespace-pre-wrap">{data?.handoff_markdown || 'Loading…'}</pre>
        </div>
      </div>
    </div>
  );
};
