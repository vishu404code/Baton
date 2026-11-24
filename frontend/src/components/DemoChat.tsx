import React, { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Play, RotateCcw, Check, Loader2, Sparkles } from 'lucide-react';
import { api } from '../api/client';

const COLORS: Record<string, string> = { claude_code: '#F59E0B', codex: '#22D3EE', antigravity: '#A78BFA', gemini_cli: '#60A5FA' };

interface Demo {
  running: boolean; done: boolean; step: number; total: number; tool: string | null; name: string | null;
  prompt: string; reply: string; phase: string; read_count: number; is_demo_room: boolean; scenario: string;
  scenarios: Array<{ id: string; title: string; blurb: string; steps: number }>;
  transcript: Array<{ tool: string; name: string; prompt: string; reply: string }>;
}

const Avatar: React.FC<{ tool: string; name: string }> = ({ tool, name }) => (
  <span className="w-8 h-8 rounded-full flex items-center justify-center text-[12px] font-semibold shrink-0"
    style={{ background: `${COLORS[tool] || '#8B8FA3'}26`, color: COLORS[tool] || '#8B8FA3', boxShadow: `inset 0 0 0 1.5px ${(COLORS[tool] || '#8B8FA3')}66` }}>{name[0]}</span>
);

const Exchange: React.FC<{ tool: string; name: string; prompt: string; reply: string; caret?: boolean }> = ({ tool, name, prompt, reply, caret }) => (
  <div className="space-y-2.5 baton-fade">
    <div className="flex justify-end">
      <div className="max-w-[78%] rounded-2xl rounded-br-md bg-[#6366F1]/15 border border-[#6366F1]/30 px-4 py-2.5 text-[13.5px] text-[#E6E7EB]">
        <div className="text-[10px] uppercase tracking-wider text-[#818CF8] mb-0.5">You to {name}</div>
        {prompt}
      </div>
    </div>
    {(reply || caret) && (
      <div className="flex gap-2.5">
        <Avatar tool={tool} name={name} />
        <div className="max-w-[84%] rounded-2xl rounded-tl-md bg-[#1D1F27] border border-[#2A2D37] px-4 py-3 text-[13.5px] leading-relaxed text-[#E6E7EB]">
          <div className="text-[11px] font-semibold mb-1" style={{ color: COLORS[tool] }}>{name}</div>
          {reply}
          {caret && <span className="inline-block w-[7px] h-[15px] align-[-2px] ml-0.5 bg-[#818CF8] animate-pulse" />}
        </div>
      </div>
    )}
  </div>
);

const PHASES = [
  { id: 'connecting', label: 'Connecting to Baton' },
  { id: 'reading', label: 'Reading the handoff' },
  { id: 'answering', label: 'Answering' },
  { id: 'saving', label: 'Saving context' },
];

export const DemoChat: React.FC<{ roomId: string }> = ({ roomId }) => {
  const qc = useQueryClient();
  const endRef = useRef<HTMLDivElement>(null);
  const [pick, setPick] = useState('trip');
  const { data } = useQuery<Demo>({
    queryKey: ['demo', roomId],
    queryFn: () => api.getDemo(roomId),
    refetchInterval: (q) => ((q.state.data as Demo | undefined)?.running ? 500 : 2500),
  });

  const phase = data?.phase;
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ['context', roomId] });
  }, [phase === 'saved', data?.step]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [data?.reply, data?.transcript.length, data?.phase]);

  if (!data?.is_demo_room) return null;
  const idx = PHASES.findIndex((p) => p.id === phase);
  const current = data.running && data.step > data.transcript.length;
  const started = data.running || data.done || data.transcript.length > 0;

  const start = async () => {
    await api.startDemo(roomId, pick);
    qc.invalidateQueries({ queryKey: ['demo', roomId] });
  };
  const reset = async () => {
    await api.resetDemo(roomId);
    qc.invalidateQueries({ queryKey: ['demo', roomId] });
    qc.invalidateQueries({ queryKey: ['context', roomId] });
  };

  return (
    <div className="baton-lift rounded-3xl border border-[#6366F1]/40 bg-[#111217] overflow-hidden">
      <div className="px-5 py-4 flex items-center justify-between gap-3 border-b border-[#2A2D37]">
        <div className="flex items-center gap-2.5">
          <Sparkles className="w-4 h-4 text-[#818CF8]" />
          <div>
            <div className="text-[15px] font-semibold text-[#E6E7EB]">Live demo: four AIs, one conversation</div>
            <div className="text-[12px] text-[#8B8FA3]">Each AI starts a fresh chat and already knows what the others did. Pick a scenario and run it.</div>
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          {started && !data.running && (
            <button onClick={reset} className="px-3 py-2 rounded-xl bg-[#1D1F27] border border-[#2A2D37] text-[12px] text-[#E6E7EB] flex items-center gap-1.5">
              <RotateCcw className="w-3.5 h-3.5" /> Reset
            </button>
          )}
          <button onClick={start} disabled={data.running} className="px-4 py-2 rounded-xl bg-[#6366F1] text-white text-[13px] font-semibold flex items-center gap-2 disabled:opacity-60">
            {data.running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {data.running ? `Step ${data.step} of ${data.total}` : data.done ? 'Run selected' : 'Run live demo'}
          </button>
        </div>
      </div>

      <div className="px-5 pt-4 flex flex-wrap gap-2">
        {data.scenarios.map((sc) => {
          const on = (data.running ? data.scenario : pick) === sc.id;
          return (
            <button key={sc.id} disabled={data.running} onClick={() => setPick(sc.id)} title={sc.blurb}
              className={`px-3.5 py-1.5 rounded-full border text-[12.5px] font-medium transition-colors disabled:cursor-default ${on ? 'border-[#6366F1] bg-[#6366F1]/10 text-[#E6E7EB]' : 'border-[#2A2D37] bg-[#1D1F27] text-[#8B8FA3] hover:text-[#E6E7EB]'}`}>
              {sc.title} <span className="opacity-60">· {sc.steps} steps</span>
            </button>
          );
        })}
      </div>
      {!started && <div className="px-5 pt-2 pb-4 text-[12px] text-[#8B8FA3]">{data.scenarios.find((x) => x.id === pick)?.blurb}</div>}

      {started && (
        <div className="px-5 py-5 space-y-5">
          {data.transcript.map((t, i) => <Exchange key={i} {...t} />)}
          {current && data.tool && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                {PHASES.map((p, i) => {
                  const done = idx > i || phase === 'saved';
                  const active = idx === i;
                  return (
                    <span key={p.id} className={`px-2.5 py-1 rounded-full border flex items-center gap-1.5 ${active ? 'border-[#6366F1] text-[#818CF8] bg-[#6366F1]/10' : done ? 'border-[#22C55E]/40 text-[#22C55E]' : 'border-[#2A2D37] text-[#8B8FA3]'}`}>
                      {done ? <Check className="w-3 h-3" /> : active ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                      {p.id === 'reading' && active ? `Reading the handoff (${data.read_count} earlier ${data.read_count === 1 ? 'entry' : 'entries'})` : p.label}
                    </span>
                  );
                })}
              </div>
              <Exchange tool={data.tool} name={data.name || ''} prompt={data.prompt} reply={data.reply} caret={phase === 'answering'} />
            </div>
          )}
          {data.done && (
            <div className="rounded-2xl border border-[#22C55E]/30 bg-[#22C55E]/10 px-4 py-3 text-[13px] text-[#22C55E]">
              Done. Four tools, one thread: nobody re-explained anything. Every step is in the timeline below.
            </div>
          )}
          <div ref={endRef} />
        </div>
      )}
    </div>
  );
};
