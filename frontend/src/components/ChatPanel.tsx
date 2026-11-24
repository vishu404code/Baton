import React, { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Send, Check, Loader2, MessageSquare, Trash2, KeyRound } from 'lucide-react';
import { api } from '../api/client';

const COLORS: Record<string, string> = { anthropic: '#F59E0B', openai: '#22D3EE', gemini: '#60A5FA', deepseek: '#34D399' };

interface Seat { provider: string; label: string; model: string; ready: boolean }
interface Msg { id: string; role: 'user' | 'ai' | 'error'; provider: string | null; label: string | null; model: string | null; content: string }
interface Pending { provider: string; label: string; prompt: string; phase: string; reply: string; read_count: number }
interface ChatState { messages: Msg[]; pending: Pending | null; seats: Seat[] }

const PHASES = [
  { id: 'connecting', label: 'Connecting to Baton' },
  { id: 'reading', label: 'Reading the shared memory' },
  { id: 'answering', label: 'Answering' },
  { id: 'saving', label: 'Saving to memory' },
];

const Avatar: React.FC<{ provider: string | null; label: string }> = ({ provider, label }) => (
  <span className="w-8 h-8 rounded-full flex items-center justify-center text-[12px] font-semibold shrink-0"
    style={{ background: `${COLORS[provider || ''] || '#8B8FA3'}26`, color: COLORS[provider || ''] || '#8B8FA3', boxShadow: `inset 0 0 0 1.5px ${(COLORS[provider || ''] || '#8B8FA3')}66` }}>{label[0]}</span>
);

const UserBubble: React.FC<{ label: string | null; text: string }> = ({ label, text }) => (
  <div className="flex justify-end baton-fade">
    <div className="max-w-[80%] rounded-2xl rounded-br-md bg-[#6366F1]/15 border border-[#6366F1]/30 px-4 py-2.5 text-[13.5px] text-[#E6E7EB] whitespace-pre-wrap">
      <div className="text-[10px] uppercase tracking-wider text-[#818CF8] mb-0.5">You to {label}</div>
      {text}
    </div>
  </div>
);

const AiBubble: React.FC<{ provider: string | null; label: string; model?: string | null; text: string; caret?: boolean; error?: boolean }> = ({ provider, label, model, text, caret, error }) => (
  <div className="flex gap-2.5 baton-fade">
    <Avatar provider={provider} label={label} />
    <div className={`max-w-[86%] rounded-2xl rounded-tl-md border px-4 py-3 text-[13.5px] leading-relaxed whitespace-pre-wrap ${error ? 'bg-[#EF4444]/10 border-[#EF4444]/30 text-[#EF4444]' : 'bg-[#1D1F27] border-[#2A2D37] text-[#E6E7EB]'}`}>
      <div className="text-[11px] font-semibold mb-1" style={{ color: error ? undefined : COLORS[provider || ''] }}>
        {label}{model ? <span className="font-normal text-[#8B8FA3]"> · {model}</span> : null}
      </div>
      {text}
      {caret && <span className="inline-block w-[7px] h-[15px] align-[-2px] ml-0.5 bg-[#818CF8] animate-pulse" />}
    </div>
  </div>
);

const IDEAS = [
  'Plan a 3-day Jaipur trip for 4 friends under 40,000 rupees.',
  'Explain how a bill becomes a law in simple words.',
  'Give me a 4-week plan to learn Python from zero.',
];

export const ChatPanel: React.FC<{ roomId: string; onOpenKeys?: () => void }> = ({ roomId, onOpenKeys }) => {
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const [provider, setProvider] = useState('anthropic');
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState('');
  const box = useRef<HTMLDivElement>(null);

  const { data } = useQuery<ChatState>({
    queryKey: ['chat', roomId],
    queryFn: () => api.getChat(roomId),
    refetchInterval: (q) => ((q.state.data as ChatState | undefined)?.pending ? 400 : 2500),
  });
  const seats = data?.seats || [];
  const pending = data?.pending || null;
  const seat = seats.find((s) => s.provider === provider);

  // Pick the first AI that has a key, once we know.
  const picked = useRef(false);
  useEffect(() => {
    if (!picked.current && seats.length) {
      picked.current = true;
      const first = seats.find((s) => s.ready);
      if (first) setProvider(first.provider);
    }
  }, [seats]);

  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight, behavior: 'smooth' });
  }, [data?.messages.length, pending?.reply, pending?.phase]);

  const lastPhase = useRef<string | null>(null);
  useEffect(() => {
    if (lastPhase.current && !pending) {
      qc.invalidateQueries({ queryKey: ['context', roomId] });
      qc.invalidateQueries({ queryKey: ['agents', roomId] });
    }
    lastPhase.current = pending ? pending.phase : null;
  }, [pending, qc, roomId]);

  const send = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const t = text.trim();
    if (!t || sending || pending) return;
    setSending(true);
    setErr('');
    try {
      await api.sendChat(roomId, provider, t);
      setText('');
      qc.invalidateQueries({ queryKey: ['chat', roomId] });
    } catch (ex: any) {
      setErr(ex?.message || 'Could not send.');
    } finally {
      setSending(false);
    }
  };

  const clear = async () => {
    await api.clearChat(roomId);
    qc.invalidateQueries({ queryKey: ['chat', roomId] });
  };

  const idx = pending ? PHASES.findIndex((p) => p.id === pending.phase) : -1;
  const empty = !data?.messages.length && !pending;
  const anyReady = seats.some((s) => s.ready);

  return (
    <div className="baton-lift rounded-3xl border border-[#6366F1]/40 bg-[#111217] overflow-hidden">
      <div className="px-5 py-4 flex items-center justify-between gap-3 border-b border-[#2A2D37]">
        <div className="flex items-center gap-2.5">
          <MessageSquare className="w-4 h-4 text-[#818CF8]" />
          <div>
            <div className="text-[15px] font-semibold text-[#E6E7EB]">Chat with your AIs</div>
            <div className="text-[12px] text-[#8B8FA3]">Ask one AI, then switch. The next one already knows what was said.</div>
          </div>
        </div>
        {!empty && !pending && (
          <button onClick={clear} className="px-3 py-2 rounded-xl bg-[#1D1F27] border border-[#2A2D37] text-[12px] text-[#E6E7EB] flex items-center gap-1.5">
            <Trash2 className="w-3.5 h-3.5" /> Clear chat
          </button>
        )}
      </div>

      <div ref={box} className="px-5 py-5 space-y-5 overflow-y-auto" style={{ minHeight: 150, maxHeight: 460 }}>
        {empty && (
          <div className="text-center py-4 space-y-3">
            <div className="text-[13px] text-[#8B8FA3]">
              {anyReady ? 'Pick an AI below and ask anything. Try:' : 'Add an API key for at least one AI to start chatting.'}
            </div>
            {anyReady ? (
              <div className="flex flex-wrap justify-center gap-2">
                {IDEAS.map((i) => (
                  <button key={i} onClick={() => setText(i)} className="px-3 py-1.5 rounded-full border border-[#2A2D37] bg-[#1D1F27] text-[12px] text-[#E6E7EB] hover:border-[#6366F1] transition-colors">{i}</button>
                ))}
              </div>
            ) : (
              onOpenKeys && (
                <button onClick={onOpenKeys} className="px-4 py-2 rounded-xl bg-[#6366F1] text-white text-[13px] font-semibold inline-flex items-center gap-2">
                  <KeyRound className="w-4 h-4" /> Add API keys
                </button>
              )
            )}
          </div>
        )}
        {data?.messages.map((m) =>
          m.role === 'user' ? (
            <UserBubble key={m.id} label={m.label} text={m.content} />
          ) : (
            <AiBubble key={m.id} provider={m.provider} label={m.label || 'AI'} model={m.model} text={m.content} error={m.role === 'error'} />
          ),
        )}
        {pending && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              {PHASES.map((p, i) => {
                const done = idx > i || pending.phase === 'saved';
                const active = idx === i;
                return (
                  <span key={p.id} className={`px-2.5 py-1 rounded-full border flex items-center gap-1.5 ${active ? 'border-[#6366F1] text-[#818CF8] bg-[#6366F1]/10' : done ? 'border-[#22C55E]/40 text-[#22C55E]' : 'border-[#2A2D37] text-[#8B8FA3]'}`}>
                    {done ? <Check className="w-3 h-3" /> : active ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                    {p.id === 'reading' && active ? `Reading the shared memory (${pending.read_count} ${pending.read_count === 1 ? 'entry' : 'entries'})` : p.label}
                  </span>
                );
              })}
            </div>
            {(pending.reply || pending.phase === 'answering') && (
              <AiBubble provider={pending.provider} label={pending.label} text={pending.reply} caret={pending.phase === 'answering' || pending.reply.length > 0} />
            )}
          </div>
        )}
      </div>

      <form onSubmit={send} className="border-t border-[#2A2D37] px-5 py-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] uppercase tracking-wider text-[#8B8FA3] mr-1">Ask</span>
          {seats.map((s) => {
            const on = s.provider === provider;
            return (
              <button type="button" key={s.provider} onClick={() => setProvider(s.provider)}
                className={`px-3 py-1.5 rounded-full border text-[12.5px] font-medium flex items-center gap-2 transition-colors ${on ? 'border-[#6366F1] bg-[#6366F1]/10 text-[#E6E7EB]' : 'border-[#2A2D37] bg-[#1D1F27] text-[#8B8FA3] hover:text-[#E6E7EB]'}`}
                title={s.ready ? `${s.label} (${s.model})` : `No API key for ${s.label} yet`}>
                <span className="w-2 h-2 rounded-full" style={{ background: s.ready ? COLORS[s.provider] : 'transparent', boxShadow: s.ready ? 'none' : 'inset 0 0 0 1.5px #9A8FA6' }} />
                {s.label}
              </button>
            );
          })}
        </div>
        {seat && !seat.ready && (
          <div className="text-[12px] text-[#8B8FA3]">
            {seat.label} has no API key yet.{' '}
            {onOpenKeys && <button type="button" onClick={onOpenKeys} className="text-[#818CF8] underline">Add one under Tools & keys</button>}
          </div>
        )}
        <div className="flex gap-2.5 items-end">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
            rows={2}
            placeholder={`Message ${seat?.label || 'an AI'}…  (Enter to send, Shift+Enter for a new line)`}
            className="flex-1 px-4 py-3 bg-[#1D1F27] border border-[#2A2D37] rounded-2xl text-[13.5px] text-[#E6E7EB] focus:outline-none focus:border-[#6366F1] resize-none"
          />
          <button disabled={sending || !!pending || !text.trim()} className="px-5 py-3 rounded-2xl bg-[#6366F1] text-white text-[13px] font-semibold flex items-center gap-2 disabled:opacity-50">
            <Send className="w-4 h-4" /> Send
          </button>
        </div>
        {err && <div className="text-[12px] text-[#EF4444]">{err}</div>}
        <div className="text-[11px] text-[#8B8FA3]">Tools like Claude Code, Codex and Antigravity join the same memory through MCP and show up in the timeline below.</div>
      </form>
    </div>
  );
};
