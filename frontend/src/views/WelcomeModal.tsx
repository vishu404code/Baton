import React, { useState } from 'react';
import { Bot, LogIn, Plus, Sparkles, UserCheck } from 'lucide-react';
import { api } from '../api/client';

interface WelcomeModalProps {
  onSignedIn: (user: { id: string; display_name: string }) => void;
}

export const WelcomeModal: React.FC<WelcomeModalProps> = ({ onSignedIn }) => {
  const [displayName, setDisplayName] = useState('');
  const [inviteCode, setInviteCode] = useState('CAMPUS-7KQ2');
  const [roomName, setRoomName] = useState('Campus App Launch');
  const [mode, setMode] = useState<'welcome' | 'join' | 'create'>('welcome');
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const handleDemoSignIn = async (name: string) => {
    try {
      setLoading(true);
      setErrorMsg('');
      const res = await api.demoSession(name);
      onSignedIn(res.user);
    } catch (err: any) {
      // If demoSession endpoint doesn't work, create standard session
      try {
        const res2 = await api.createSession(name);
        onSignedIn(res2.user);
      } catch (err2: any) {
        setErrorMsg(err2.message || 'Failed to sign in');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleCustomSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!displayName.trim()) return;

    try {
      setLoading(true);
      setErrorMsg('');
      const res = await api.createSession(displayName.trim());

      if (mode === 'join' && inviteCode.trim()) {
        try {
          await api.joinRoom(inviteCode.trim().toUpperCase());
        } catch (err) {
          console.warn('Room join failed, proceeding with session:', err);
        }
      } else if (mode === 'create' && roomName.trim()) {
        try {
          await api.createRoom(roomName.trim());
        } catch (err) {
          console.warn('Room create failed, proceeding with session:', err);
        }
      }

      onSignedIn(res.user);
    } catch (err: any) {
      setErrorMsg(err.message || 'Sign in failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-[#0B0C0F] flex items-center justify-center p-4 z-50">
      <div className="w-full max-w-lg bg-[#16171D] border border-[#2A2D37] rounded-2xl p-8 shadow-2xl">
        {/* App Logo and Title */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-xl bg-[#6366F1]/10 border border-[#6366F1]/40 flex items-center justify-center text-[#6366F1] font-bold text-2xl">
            B
          </div>
          <div>
            <h1 className="text-xl font-bold text-[#E6E7EB]">Baton</h1>
            <p className="text-xs text-[#8B8FA3]">
              Multi-agent coordination for AI coding tools
            </p>
          </div>
        </div>

        {/* Demo Fast-Track Section */}
        <div className="mb-6 p-4 rounded-xl bg-[#1D1F27] border border-[#2A2D37]">
          <div className="text-xs font-semibold uppercase tracking-wider text-[#8B8FA3] mb-3 flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-[#6366F1]" />
            <span>Fast-track demo sign-in</span>
          </div>

          <div className="grid grid-cols-3 gap-2">
            <button
              onClick={() => handleDemoSignIn('Asha')}
              disabled={loading}
              className="p-3 rounded-lg bg-[#111217] hover:bg-[#6366F1]/20 border border-[#2A2D37] hover:border-[#6366F1]/50 text-left transition-all"
            >
              <div className="font-semibold text-xs text-[#E6E7EB]">Asha</div>
              <div className="text-[10px] text-[#6366F1] font-mono">Owner</div>
              <div className="text-[10px] text-[#8B8FA3] mt-1">Planner (Claude)</div>
            </button>

            <button
              onClick={() => handleDemoSignIn('Ben')}
              disabled={loading}
              className="p-3 rounded-lg bg-[#111217] hover:bg-[#22D3EE]/20 border border-[#2A2D37] hover:border-[#22D3EE]/50 text-left transition-all"
            >
              <div className="font-semibold text-xs text-[#E6E7EB]">Ben</div>
              <div className="text-[10px] text-[#22D3EE] font-mono">Member</div>
              <div className="text-[10px] text-[#8B8FA3] mt-1">Reviewer (Codex)</div>
            </button>

            <button
              onClick={() => handleDemoSignIn('Chen')}
              disabled={loading}
              className="p-3 rounded-lg bg-[#111217] hover:bg-[#22C55E]/20 border border-[#2A2D37] hover:border-[#22C55E]/50 text-left transition-all"
            >
              <div className="font-semibold text-xs text-[#E6E7EB]">Chen</div>
              <div className="text-[10px] text-[#22C55E] font-mono">Mentor</div>
              <div className="text-[10px] text-[#8B8FA3] mt-1">Decisions & tasks</div>
            </button>
          </div>
        </div>

        {/* Custom Sign-in Form */}
        <form onSubmit={handleCustomSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
              Your Display Name
            </label>
            <input
              type="text"
              placeholder="e.g. Alex"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-sm focus:outline-none focus:border-[#6366F1]"
            />
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setMode('join')}
              className={`flex-1 py-2 text-xs font-medium rounded-lg border transition-all flex items-center justify-center gap-1.5 ${
                mode === 'join'
                  ? 'bg-[#6366F1]/10 border-[#6366F1] text-[#6366F1]'
                  : 'bg-[#111217] border-[#2A2D37] text-[#8B8FA3] hover:text-[#E6E7EB]'
              }`}
            >
              <LogIn className="w-3.5 h-3.5" />
              Join with invite code
            </button>

            <button
              type="button"
              onClick={() => setMode('create')}
              className={`flex-1 py-2 text-xs font-medium rounded-lg border transition-all flex items-center justify-center gap-1.5 ${
                mode === 'create'
                  ? 'bg-[#6366F1]/10 border-[#6366F1] text-[#6366F1]'
                  : 'bg-[#111217] border-[#2A2D37] text-[#8B8FA3] hover:text-[#E6E7EB]'
              }`}
            >
              <Plus className="w-3.5 h-3.5" />
              Create a new room
            </button>
          </div>

          {mode === 'join' && (
            <div>
              <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                Room Invite Code
              </label>
              <input
                type="text"
                placeholder="CAMPUS-7KQ2"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] font-mono text-sm uppercase tracking-wider focus:outline-none focus:border-[#6366F1]"
              />
            </div>
          )}

          {mode === 'create' && (
            <div>
              <label className="block text-xs font-medium text-[#8B8FA3] mb-1">
                Room Name
              </label>
              <input
                type="text"
                placeholder="e.g. Campus App Launch"
                value={roomName}
                onChange={(e) => setRoomName(e.target.value)}
                className="w-full px-3 py-2 bg-[#111217] border border-[#2A2D37] rounded-lg text-[#E6E7EB] text-sm focus:outline-none focus:border-[#6366F1]"
              />
            </div>
          )}

          {errorMsg && (
            <div className="text-xs text-[#EF4444] bg-[#EF4444]/10 border border-[#EF4444]/30 p-2.5 rounded-lg">
              {errorMsg}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !displayName.trim()}
            className="w-full py-2.5 bg-[#6366F1] hover:bg-[#4F46E5] disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
          >
            <UserCheck className="w-4 h-4" />
            {loading ? 'Signing in...' : 'Continue to Baton'}
          </button>
        </form>
      </div>
    </div>
  );
};
