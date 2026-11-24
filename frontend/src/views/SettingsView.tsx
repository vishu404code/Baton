import React, { useState } from 'react';
import {
  Settings as SettingsIcon,
  Check,
  Copy,
  Lock,
  ShieldCheck,
  Clock,
  FileCheck,
} from 'lucide-react';
import { Room, Role } from '../api/types';
import { api } from '../api/client';
import { useQueryClient } from '@tanstack/react-query';

interface SettingsViewProps {
  room: Room | null;
  myRole: Role;
}

export const SettingsView: React.FC<SettingsViewProps> = ({ room, myRole }) => {
  const queryClient = useQueryClient();
  const [savedField, setSavedField] = useState<string | null>(null);
  const [copiedCode, setCopiedCode] = useState(false);

  const isMentor = myRole === 'owner' || myRole === 'mentor';
  const settings = room?.settings || {
    lease_minutes: 15,
    require_approval: false,
  };

  const handleUpdate = async (patch: any, fieldKey: string) => {
    if (!room || !isMentor) return;
    try {
      await api.updateRoomSettings(room.id, patch);
      setSavedField(fieldKey);
      setTimeout(() => setSavedField(null), 1500);
      queryClient.invalidateQueries({ queryKey: ['room', room.id] });
      queryClient.invalidateQueries({ queryKey: ['rooms'] });
    } catch (e: any) {
      alert(e.message || 'Failed to update settings');
    }
  };

  const copyCode = () => {
    if (!room) return;
    navigator.clipboard.writeText(room.invite_code);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[#16171D] overflow-hidden select-none">
      {/* Header bar */}
      <div className="h-16 px-6 border-b border-[#2A2D37] flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-base font-bold text-[#E6E7EB] flex items-center gap-2">
            <SettingsIcon className="w-4 h-4 text-[#6366F1]" />
            <span>Room Settings</span>
          </h1>
          <p className="text-xs text-[#8B8FA3]">
            Configure verification strictness, claim timeouts, and approval policies.
          </p>
        </div>

        {!isMentor && (
          <span className="text-xs text-[#8B8FA3] italic">
            Read-only (only mentors can edit settings)
          </span>
        )}
      </div>

      {/* Settings Sections */}
      <div className="flex-1 overflow-y-auto p-6 max-w-3xl space-y-8">
        {/* The three checks every submission passes (not configurable) */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
            <ShieldCheck className="w-4 h-4 text-[#22C55E]" />
            <span>Verification</span>
          </div>

          <div className="bg-[#111217] border border-[#2A2D37] rounded-2xl divide-y divide-[#2A2D37] overflow-hidden">
            {[
              ['1. Holds the claim', 'Only the agent that claimed a task can submit for it.'],
              ['2. Based on current revisions', 'Work built on an outdated decision is rejected and flagged stale.'],
              ['3. Content complete', 'The output has the fields its type needs, and every cited source exists.'],
            ].map(([title, text]) => (
              <div key={title} className="p-4 flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold text-[#E6E7EB]">{title}</div>
                  <div className="text-[11px] text-[#8B8FA3] mt-0.5">{text}</div>
                </div>
                <span className="px-2 py-0.5 rounded-full bg-[#2A2D37] text-[10px] font-mono text-[#8B8FA3] flex items-center gap-1">
                  <Lock className="w-2.5 h-2.5" /> Always on
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Numeric parameters */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
            <Clock className="w-4 h-4 text-[#F59E0B]" />
            <span>Task Leases & Limits</span>
          </div>

          <div className="bg-[#111217] border border-[#2A2D37] rounded-2xl divide-y divide-[#2A2D37] overflow-hidden">
            {/* Lease minutes */}
            <div className="p-4 flex items-center justify-between">
              <div>
                <div className="text-xs font-semibold text-[#E6E7EB]">
                  Claim Lease Duration (Minutes)
                </div>
                <div className="text-[11px] text-[#8B8FA3] mt-0.5">
                  How long an agent holds an exclusive task lock before expiration (1–120m).
                </div>
              </div>

              <div className="flex items-center gap-2">
                {savedField === 'lease_minutes' && (
                  <span className="text-[11px] text-[#22C55E] flex items-center gap-1 font-mono">
                    <Check className="w-3.5 h-3.5" /> Saved
                  </span>
                )}
                <input
                  type="number"
                  min={1}
                  max={120}
                  disabled={!isMentor}
                  defaultValue={settings.lease_minutes}
                  onBlur={(e) =>
                    handleUpdate(
                      { lease_minutes: parseInt(e.target.value, 10) || 15 },
                      'lease_minutes'
                    )
                  }
                  className="w-20 px-3 py-1.5 bg-[#1D1F27] border border-[#2A2D37] rounded-lg text-xs font-mono text-[#E6E7EB] text-center focus:outline-none focus:border-[#6366F1]"
                />
              </div>
            </div>

            {/* Require approval toggle */}
            <div className="p-4 flex items-center justify-between">
              <div>
                <div className="text-xs font-semibold text-[#E6E7EB]">
                  Require Human Approval for All Agent Work
                </div>
                <div className="text-[11px] text-[#8B8FA3] mt-0.5">
                  When enabled, all submissions pause for mentor review. (Redone stale work always requires approval).
                </div>
              </div>

              <div className="flex items-center gap-2">
                {savedField === 'require_approval' && (
                  <span className="text-[11px] text-[#22C55E] flex items-center gap-1 font-mono">
                    <Check className="w-3.5 h-3.5" /> Saved
                  </span>
                )}
                <input
                  type="checkbox"
                  disabled={!isMentor}
                  checked={settings.require_approval}
                  onChange={(e) =>
                    handleUpdate({ require_approval: e.target.checked }, 'require_approval')
                  }
                  className="w-4 h-4 rounded text-[#6366F1] bg-[#1D1F27] border-[#2A2D37] focus:ring-0"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Invite code box */}
        <div className="space-y-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-[#8B8FA3]">
            Room Invite Code
          </div>
          <div className="p-4 bg-[#111217] border border-[#2A2D37] rounded-xl flex items-center justify-between">
            <span className="font-mono text-sm font-bold text-[#6366F1]">
              {room?.invite_code}
            </span>
            <button
              onClick={copyCode}
              className="px-3 py-1.5 bg-[#1D1F27] hover:bg-[#2A2D37] border border-[#2A2D37] rounded-lg text-xs text-[#E6E7EB] flex items-center gap-1.5 transition-colors"
            >
              {copiedCode ? (
                <Check className="w-3.5 h-3.5 text-[#22C55E]" />
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
              <span>{copiedCode ? 'Copied' : 'Copy Code'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
