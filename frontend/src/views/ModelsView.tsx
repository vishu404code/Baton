import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Cpu, KeyRound, CheckCircle2, AlertTriangle, Loader2, Plug, Eye, EyeOff } from 'lucide-react';
import { api } from '../api/client';
import { ProviderInfo, ConnectTool } from '../api/types';

const ACCENT: Record<string, string> = {
  anthropic: '#F59E0B',
  openai: '#22D3EE',
  deepseek: '#60A5FA',
  gemini: '#A78BFA',
  mock: '#8B8FA3',
};

function ProviderCard({ p, onChanged }: { p: ProviderInfo; onChanged: () => void }) {
  const [key, setKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState<'save' | 'test' | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const color = ACCENT[p.id] || '#6366F1';

  const save = async () => {
    setBusy('save');
    setNote(null);
    try {
      await api.updateProvider(p.id, { api_key: key });
      setKey('');
      setNote({ ok: true, text: key.trim() ? 'Key saved on this computer.' : 'Key removed.' });
      onChanged();
    } catch (e: any) {
      setNote({ ok: false, text: e.message || 'Could not save' });
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy('test');
    setNote(null);
    try {
      if (key.trim()) await api.updateProvider(p.id, { api_key: key });
      setKey('');
      const res = await api.testProvider(p.id);
      setNote(
        res.ok
          ? { ok: true, text: `Works. ${res.models?.length ?? 0} models available.` }
          : { ok: false, text: res.error || 'The key did not work.' }
      );
      onChanged();
    } catch (e: any) {
      setNote({ ok: false, text: e.message || 'Test failed' });
    } finally {
      setBusy(null);
    }
  };

  const setModel = async (model: string) => {
    try {
      await api.updateProvider(p.id, { model });
      onChanged();
    } catch (e: any) {
      setNote({ ok: false, text: e.message });
    }
  };

  const models = p.models.includes(p.model) ? p.models : [p.model, ...p.models];

  return (
    <div className="bg-[#111217] border border-[#2A2D37] rounded-2xl p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
          <div>
            <div className="text-sm font-semibold text-[#E6E7EB]">{p.label}</div>
            <div className="text-[11px] text-[#8B8FA3]">{p.help}</div>
          </div>
        </div>
        {p.ready ? (
          <span className="shrink-0 px-2 py-0.5 rounded-full bg-[#22C55E]/15 border border-[#22C55E]/40 text-[10px] font-mono text-[#22C55E] flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" /> {p.needs_key ? `Ready ${p.key_hint ?? ''}` : 'Ready'}
          </span>
        ) : (
          <span className="shrink-0 px-2 py-0.5 rounded-full bg-[#2A2D37] text-[10px] font-mono text-[#8B8FA3]">No key</span>
        )}
      </div>

      {p.needs_key && (
        <div className="flex gap-2">
          <div className="relative flex-1">
            <KeyRound className="w-3.5 h-3.5 text-[#8B8FA3] absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type={showKey ? 'text' : 'password'}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={p.has_key ? 'Key saved. Paste a new one to replace it' : 'Paste API key'}
              autoComplete="off"
              spellCheck={false}
              className="w-full pl-8 pr-8 py-2 bg-[#1D1F27] border border-[#2A2D37] rounded-lg text-xs font-mono text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[#8B8FA3] hover:text-[#E6E7EB]"
              title={showKey ? 'Hide' : 'Show'}
            >
              {showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            </button>
          </div>
          <button
            onClick={save}
            disabled={busy !== null || (!key.trim() && !p.has_key)}
            className="px-3 py-2 text-xs rounded-lg bg-[#1D1F27] border border-[#2A2D37] text-[#E6E7EB] hover:border-[#6366F1] disabled:opacity-40"
          >
            {busy === 'save' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : key.trim() || !p.has_key ? 'Save' : 'Remove'}
          </button>
          <button
            onClick={test}
            disabled={busy !== null || (!key.trim() && !p.has_key)}
            className="px-3 py-2 text-xs rounded-lg bg-[#6366F1] text-white hover:bg-[#5558E6] disabled:opacity-40 flex items-center gap-1.5"
          >
            {busy === 'test' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null} Test
          </button>
        </div>
      )}

      <div className="flex items-center gap-2 text-xs">
        <span className="text-[#8B8FA3] w-14">Model</span>
        <select
          value={p.model}
          onChange={(e) => setModel(e.target.value)}
          className="flex-1 px-2.5 py-1.5 bg-[#1D1F27] border border-[#2A2D37] rounded-lg font-mono text-[#E6E7EB] focus:outline-none focus:border-[#6366F1]"
        >
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>

      {note && (
        <div className={`text-[11px] flex items-start gap-1.5 ${note.ok ? 'text-[#22C55E]' : 'text-[#EF4444]'}`}>
          {note.ok ? <CheckCircle2 className="w-3.5 h-3.5 mt-px" /> : <AlertTriangle className="w-3.5 h-3.5 mt-px" />}
          <span>{note.text}</span>
        </div>
      )}
    </div>
  );
}

export const ModelsView: React.FC = () => {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery<{ providers: ProviderInfo[]; connect: ConnectTool[] }>({
    queryKey: ['providers'],
    queryFn: () => api.getProviders(),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['providers'] });
    qc.invalidateQueries({ queryKey: ['agents'] });
  };

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-4 border-b border-[#2A2D37] bg-[#111217]">
        <div className="flex items-center gap-2 text-sm font-semibold text-[#E6E7EB]">
          <Cpu className="w-4 h-4 text-[#6366F1]" /> AI Models
        </div>
        <p className="text-[11px] text-[#8B8FA3] mt-1">
          Add a key for each AI you want on your team. Keys stay on this computer. Then create an agent for it
          in <b>Members &amp; Agents</b>, and press <b>Run</b> on a task.
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 max-w-3xl space-y-6">
        {isLoading && <div className="text-xs text-[#8B8FA3]">Loading…</div>}
        {error && <div className="text-xs text-[#EF4444]">{(error as Error).message}</div>}

        <div className="grid gap-4">
          {data?.providers.map((p) => (
            <ProviderCard key={p.id} p={p} onChanged={refresh} />
          ))}
        </div>

        {data && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
              <Plug className="w-4 h-4 text-[#22C55E]" /> Tools that connect themselves (MCP)
            </div>
            <div className="bg-[#111217] border border-[#2A2D37] rounded-2xl divide-y divide-[#2A2D37]">
              {data.connect.map((t) => (
                <div key={t.id} className="p-3.5 text-xs">
                  <div className="font-semibold text-[#E6E7EB]">{t.label}</div>
                  <div className="text-[11px] text-[#8B8FA3] mt-0.5">{t.help}</div>
                </div>
              ))}
              <div className="p-3.5 text-[11px] text-[#8B8FA3]">
                In <b>Members &amp; Agents → Connect an agent</b>, pick the tool. Baton shows the exact config to paste, with its
                token. These tools work tasks on their own; they don't use the keys above.
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
